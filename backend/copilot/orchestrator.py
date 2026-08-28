"""Bounded copilot orchestration with repair, retry, circuit breaking, cache, and fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Awaitable, Callable

from backend.copilot.models import CopilotAudit, CopilotContext, CopilotDraft
from backend.copilot.prompts import provider_payload, system_prompt
from backend.copilot.provider import CopilotProvider, ProviderError, ProviderRequest, ProviderResponse
from backend.copilot.tools import ReadOnlyToolRegistry, ToolResult, projection_tools
from backend.copilot.validation import CopilotValidationError, CopilotValidator
from backend.contracts.api import (
    CopilotInteractionView,
    DeterministicFallback,
    RetryState,
    ValidatedCopilotMessage,
)


ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CopilotConfiguration:
    version: str = "copilot-config.v1"
    reasoning_profile: str = "BALANCED"
    initial_max_output_tokens: int = 1800
    follow_up_max_output_tokens: int = 1100
    max_context_characters: int = 60_000
    timeout_seconds: float = 15.0
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: int = 60
    max_estimated_cost_usd: float = 0.50


@dataclass(frozen=True, slots=True)
class CopilotRunResult:
    interaction: CopilotInteractionView
    message: ValidatedCopilotMessage | None
    audit: CopilotAudit
    raw_output: dict[str, object] | None
    tool_results: tuple[ToolResult, ...] = ()


class CircuitBreaker:
    def __init__(self, threshold: int, reset_seconds: int) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: datetime | None = None

    def permit(self, now: datetime) -> bool:
        if self.opened_at is None:
            return True
        if now - self.opened_at >= timedelta(seconds=self.reset_seconds):
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self, now: datetime) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = now


class CopilotOrchestrator:
    def __init__(
        self,
        provider: CopilotProvider,
        *,
        configuration: CopilotConfiguration | None = None,
        validator: CopilotValidator | None = None,
        tools: ReadOnlyToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.configuration = configuration or CopilotConfiguration()
        self.validator = validator or CopilotValidator()
        self.tools = tools or projection_tools()
        self.breaker = CircuitBreaker(
            self.configuration.circuit_failure_threshold,
            self.configuration.circuit_reset_seconds,
        )
        self._automatic_cache: dict[tuple[str, str, int, str], CopilotRunResult] = {}

    async def run(
        self,
        context: CopilotContext,
        *,
        progress: ProgressCallback | None = None,
    ) -> CopilotRunResult:
        cache_key = (
            context.incident_id,
            context.evidence_package_id,
            context.evidence_package_version,
            self.configuration.version,
        )
        if context.mode == "INITIAL_ANALYSIS" and cache_key in self._automatic_cache:
            return self._automatic_cache[cache_key]
        started_at = datetime.now(UTC)
        started_clock = monotonic()
        attempts = 0
        repair_attempted = False
        validation_errors: list[str] = []
        raw_output: dict[str, object] | None = None
        provider_response: ProviderResponse | None = None
        tool_results: tuple[ToolResult, ...] = ()

        async def emit(stage: str) -> None:
            if progress:
                await progress(stage)

        if context.evidence_completeness == "INVALID":
            return self._fallback(
                context, started_at, started_clock, "evidence_unavailable", attempts
            )
        if not self.breaker.permit(started_at):
            return self._fallback(context, started_at, started_clock, "circuit_open", attempts)
        try:
            await emit("ANALYSING_EVIDENCE")
            payload = provider_payload(context, self.configuration.max_context_characters)
            request = self._request(context, payload, ())
            provider_response, attempts = await self._call_with_retry(request)
            self._check_cost_budget(provider_response)
            if provider_response.tool_calls:
                await emit("CHECKING_RUNBOOKS")
                tool_results = tuple(
                    await self.tools.execute_many(
                        context,
                        [(call.name, call.arguments) for call in provider_response.tool_calls],
                    )
                )
                context = self._context_with_tool_results(context, tool_results)
                payload = provider_payload(context, self.configuration.max_context_characters)
                provider_response, extra_attempts = await self._call_with_retry(
                    self._request(context, payload, (), include_tools=False)
                )
                self._check_cost_budget(provider_response)
                attempts += extra_attempts
            raw_output = provider_response.output
            await emit("VALIDATING_CITATIONS")
            try:
                message = self.validator.validate(provider_response.output, context)
            except CopilotValidationError as first_error:
                repair_attempted = True
                validation_errors.extend(first_error.errors)
                await emit("PREPARING_RESPONSE")
                repair = self._request(context, payload, first_error.errors, include_tools=False)
                repaired = await asyncio.wait_for(
                    self.provider.generate(repair), timeout=self.configuration.timeout_seconds
                )
                attempts += 1
                raw_output = repaired.output
                provider_response = repaired
                self._check_cost_budget(provider_response)
                message = self.validator.validate(repaired.output, context)
            self.breaker.success()
            completed_at = datetime.now(UTC)
            audit = self._audit(
                context,
                "VALIDATED",
                started_at,
                completed_at,
                started_clock,
                attempts,
                repair_attempted,
                validation_errors,
                provider_response,
                len(tool_results),
            )
            interaction = CopilotInteractionView(
                interaction_id=context.interaction_id,
                status="VALIDATED",
                progress_updated_at=completed_at,
                validated_message_id=message.message_id,
                retry=RetryState(eligible=False),
            )
            result = CopilotRunResult(interaction, message, audit, raw_output, tool_results)
            if context.mode == "INITIAL_ANALYSIS":
                self._automatic_cache[cache_key] = result
            await emit("PREPARING_RESPONSE")
            return result
        except (ProviderError, TimeoutError, asyncio.TimeoutError, CopilotValidationError, ValueError) as exc:
            now = datetime.now(UTC)
            self.breaker.failure(now)
            if isinstance(exc, CopilotValidationError):
                validation_errors.extend(exc.errors)
            else:
                validation_errors.append(type(exc).__name__)
            reason_code = self._safe_reason_code(exc, validation_errors)
            return self._fallback(
                context,
                started_at,
                started_clock,
                reason_code,
                attempts,
                repair_attempted,
                validation_errors,
                raw_output,
                provider_response,
                tool_results,
            )
        except Exception as exc:
            now = datetime.now(UTC)
            self.breaker.failure(now)
            return self._fallback(
                context,
                started_at,
                started_clock,
                "unexpected_internal_failure",
                attempts,
                repair_attempted,
                [type(exc).__name__],
                raw_output,
                provider_response,
                tool_results,
            )

    @staticmethod
    def _safe_reason_code(exc: Exception, validation_errors: list[str]) -> str:
        if isinstance(exc, ProviderError):
            return exc.reason_code
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return "provider_timeout"
        if isinstance(exc, CopilotValidationError):
            errors = [*validation_errors, *exc.errors]
            lowered = " ".join(errors).lower()
            if "citation" in lowered or "runbook" in lowered:
                return "citation_validation_failed"
            if any(item.startswith("schema:") for item in errors):
                return "schema_validation_failed"
            return "policy_validation_failed"
        return "unexpected_internal_failure"

    def _request(
        self,
        context: CopilotContext,
        payload: dict[str, object],
        repair_errors: tuple[str, ...],
        include_tools: bool = True,
    ) -> ProviderRequest:
        max_tokens = (
            self.configuration.initial_max_output_tokens
            if context.mode == "INITIAL_ANALYSIS"
            else self.configuration.follow_up_max_output_tokens
        )
        return ProviderRequest(
            mode=context.mode,
            system_prompt=system_prompt(context.mode, repair_errors),
            input_payload=payload,
            response_schema=CopilotDraft.model_json_schema(),
            max_output_tokens=max_tokens,
            repair_errors=repair_errors,
            tools=self.tools.definitions() if include_tools and context.mode == "FOLLOW_UP" else (),
        )

    @staticmethod
    def _context_with_tool_results(
        context: CopilotContext, results: tuple[ToolResult, ...]
    ) -> CopilotContext:
        evidence_items = list(context.evidence_items)
        citation_manifest = list(context.citation_manifest)
        for result in results:
            evidence_items.append(
                {
                    "evidence_id": result.evidence_id,
                    "category": "OBSERVED_FACT",
                    "statement": f"Bounded read-only tool result from {result.tool_name}.",
                    "structured_value": result.payload,
                    "temporal_scope": result.temporal_scope,
                    "provenance_label": "Allowlisted read-only copilot tool",
                    "source_module": result.tool_name,
                    "source_version": ReadOnlyToolRegistry.TOOLSET_VERSION,
                }
            )
            citation_manifest.append(
                {
                    "citation_type": "EVIDENCE",
                    "evidence_id": result.evidence_id,
                    "evidence_package_id": context.evidence_package_id,
                    "evidence_package_version": context.evidence_package_version,
                }
            )
        return context.model_copy(
            update={"evidence_items": evidence_items, "citation_manifest": citation_manifest}
        )

    async def _call_with_retry(self, request: ProviderRequest) -> tuple[ProviderResponse, int]:
        attempts = 0
        for attempt in range(2):
            attempts += 1
            try:
                response = await asyncio.wait_for(
                    self.provider.generate(request), timeout=self.configuration.timeout_seconds
                )
                return response, attempts
            except ProviderError as exc:
                if attempt == 0 and exc.retryable:
                    continue
                raise
            except (TimeoutError, asyncio.TimeoutError):
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("unreachable retry state")

    def _check_cost_budget(self, response: ProviderResponse) -> None:
        if (
            response.estimated_cost_usd is not None
            and response.estimated_cost_usd > self.configuration.max_estimated_cost_usd
        ):
            raise ProviderError("Configured Copilot cost budget exceeded")

    def _fallback(
        self,
        context: CopilotContext,
        started_at: datetime,
        started_clock: float,
        reason_code: str,
        attempts: int,
        repair_attempted: bool = False,
        validation_errors: list[str] | None = None,
        raw_output: dict[str, object] | None = None,
        response: ProviderResponse | None = None,
        tool_results: tuple[ToolResult, ...] = (),
    ) -> CopilotRunResult:
        completed_at = datetime.now(UTC)
        explanations = {
            "provider_disabled": "AI generation is disabled; deterministic incident findings remain available.",
            "provider_timeout": "The AI provider timed out; deterministic incident findings remain available.",
            "provider_http_failure": "The AI provider is unavailable; deterministic incident findings remain available.",
            "schema_validation_failed": "The generated report failed schema validation and was not displayed.",
            "citation_validation_failed": "The generated report failed citation validation and was not displayed.",
            "policy_validation_failed": "The generated report failed safety validation and was not displayed.",
            "circuit_open": "AI generation is temporarily paused after repeated failures.",
            "evidence_unavailable": "The evidence package is not eligible for AI generation.",
            "unexpected_internal_failure": "AI generation could not complete; deterministic findings remain available.",
        }
        fallback = DeterministicFallback(
            available=True,
            reason_code=reason_code,
            summary=explanations[reason_code],
        )
        interaction = CopilotInteractionView(
            interaction_id=context.interaction_id,
            status="FALLBACK",
            progress_updated_at=completed_at,
            deterministic_fallback=fallback,
            retry=RetryState(
                eligible=reason_code
                in {"provider_timeout", "provider_http_failure", "unexpected_internal_failure"},
                unavailable_reason=(
                    "One manual retry is available"
                    if reason_code
                    in {"provider_timeout", "provider_http_failure", "unexpected_internal_failure"}
                    else "This fallback category is not retryable"
                ),
            ),
        )
        audit = self._audit(
            context,
            "FALLBACK",
            started_at,
            completed_at,
            started_clock,
            attempts,
            repair_attempted,
            validation_errors or [reason_code],
            response,
            len(tool_results),
        )
        return CopilotRunResult(interaction, None, audit, raw_output, tool_results)

    def _audit(
        self,
        context: CopilotContext,
        status: str,
        started_at: datetime,
        completed_at: datetime,
        started_clock: float,
        attempts: int,
        repair_attempted: bool,
        validation_errors: list[str],
        response: ProviderResponse | None,
        tool_call_count: int = 0,
    ) -> CopilotAudit:
        return CopilotAudit(
            interaction_id=context.interaction_id,
            incident_id=context.incident_id,
            evidence_package_id=context.evidence_package_id,
            evidence_package_version=context.evidence_package_version,
            configuration_version=self.configuration.version,
            provider=response.provider if response else self.provider.provider_name,
            model_id=response.model_id if response else self.provider.model_id,
            mode=context.mode,
            status=status,
            attempts=attempts,
            repair_attempted=repair_attempted,
            validation_errors=sorted(set(validation_errors)),
            context_item_count=len(context.evidence_items),
            tool_call_count=tool_call_count,
            input_tokens=response.input_tokens if response else None,
            output_tokens=response.output_tokens if response else None,
            estimated_cost_usd=response.estimated_cost_usd if response else None,
            latency_ms=max(0, round((monotonic() - started_clock) * 1000)),
            created_at=started_at,
            completed_at=completed_at,
        )
