"""Provider-neutral model boundary with fake, disabled, Anthropic, and OpenAI adapters."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from backend.copilot.models import CopilotMode
from backend.config.settings import Settings


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        reason_code: str = "provider_http_failure",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    mode: CopilotMode
    system_prompt: str
    input_payload: dict[str, Any]
    response_schema: dict[str, Any]
    max_output_tokens: int
    reasoning_profile: str = "BALANCED"
    repair_errors: tuple[str, ...] = ()
    tools: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    output: dict[str, Any]
    provider: str
    model_id: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    tool_calls: tuple[ProviderToolCall, ...] = ()


class CopilotProvider(Protocol):
    provider_name: str
    model_id: str

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class DisabledProvider:
    provider_name = "disabled"
    model_id = "none"

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        del request
        raise ProviderError(
            "Copilot provider is disabled",
            reason_code="provider_disabled",
        )


class FakeProvider:
    """Deterministic scripted provider used by safety, repair, and regression tests."""

    provider_name = "fake"
    model_id = "fake-copilot-v1"

    def __init__(self, outcomes: list[dict[str, Any] | ProviderResponse | Exception], *, delay_seconds: float = 0) -> None:
        self._outcomes = deque(outcomes)
        self.delay_seconds = delay_seconds
        self.requests: list[ProviderRequest] = []

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not self._outcomes:
            raise ProviderError("Fake provider has no scripted outcome")
        outcome = self._outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ProviderResponse):
            return outcome
        return ProviderResponse(output=outcome, provider=self.provider_name, model_id=self.model_id)


@dataclass(slots=True)
class _HttpProvider:
    model_id: str
    api_key: str
    endpoint: str
    timeout_seconds: float
    client: httpx.AsyncClient | None = None
    provider_name: str = field(init=False)

    def _client(self) -> httpx.AsyncClient:
        return self.client or httpx.AsyncClient(timeout=self.timeout_seconds)

    @staticmethod
    def _status_error(response: httpx.Response) -> ProviderError:
        retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
        return ProviderError(
            "Provider HTTP request failed",
            retryable=retryable,
            reason_code="provider_http_failure",
        )


class OpenAIResponsesProvider(_HttpProvider):
    provider_name = "openai"

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        client = self._client()
        owns_client = self.client is None
        try:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_id,
                    "instructions": request.system_prompt,
                    "input": json.dumps(request.input_payload, separators=(",", ":")),
                    "reasoning": {"effort": "medium"},
                    "max_output_tokens": request.max_output_tokens,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "copilot_response",
                            "strict": True,
                            "schema": request.response_schema,
                        }
                    },
                    "tools": [
                        {
                            "type": "function",
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["input_schema"],
                            "strict": True,
                        }
                        for tool in request.tools
                    ],
                },
            )
            if not response.is_success:
                raise self._status_error(response)
            payload = response.json()
            raw_text = payload.get("output_text")
            if not raw_text:
                raw_text = next(
                    (
                        content.get("text")
                        for item in payload.get("output", [])
                        for content in item.get("content", [])
                        if content.get("type") in {"output_text", "text"}
                    ),
                    None,
                )
            tool_calls = tuple(
                ProviderToolCall(
                    call_id=str(item.get("call_id") or item.get("id")),
                    name=str(item.get("name")),
                    arguments=json.loads(item.get("arguments", "{}")),
                )
                for item in payload.get("output", [])
                if item.get("type") == "function_call"
            )
            if not isinstance(raw_text, str) and not tool_calls:
                raise ProviderError(
                    "Provider response did not contain structured output",
                    reason_code="schema_validation_failed",
                )
            usage = payload.get("usage", {})
            return ProviderResponse(
                output=json.loads(raw_text) if isinstance(raw_text, str) else {},
                provider=self.provider_name,
                model_id=self.model_id,
                request_id=payload.get("id"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                tool_calls=tool_calls,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            reason = "provider_timeout" if isinstance(exc, httpx.TimeoutException) else "provider_http_failure"
            raise ProviderError(
                "Provider request timed out or was unreachable",
                retryable=True,
                reason_code=reason,
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "Provider output was not valid JSON",
                reason_code="schema_validation_failed",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


class AnthropicMessagesProvider(_HttpProvider):
    provider_name = "anthropic"

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        client = self._client()
        owns_client = self.client is None
        try:
            response = await client.post(
                self.endpoint,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model_id,
                    "system": request.system_prompt,
                    "messages": [{"role": "user", "content": json.dumps(request.input_payload, separators=(",", ":"))}],
                    "max_tokens": request.max_output_tokens,
                    "output_config": {
                        "effort": "medium",
                        "format": {"type": "json_schema", "schema": request.response_schema},
                    },
                    "tools": list(request.tools),
                },
            )
            if not response.is_success:
                raise self._status_error(response)
            payload = response.json()
            raw_text = next(
                (item.get("text") for item in payload.get("content", []) if item.get("type") == "text"),
                None,
            )
            tool_calls = tuple(
                ProviderToolCall(
                    call_id=str(item.get("id")),
                    name=str(item.get("name")),
                    arguments=dict(item.get("input", {})),
                )
                for item in payload.get("content", [])
                if item.get("type") == "tool_use"
            )
            if not isinstance(raw_text, str) and not tool_calls:
                raise ProviderError(
                    "Provider response did not contain structured output",
                    reason_code="schema_validation_failed",
                )
            usage = payload.get("usage", {})
            return ProviderResponse(
                output=json.loads(raw_text) if isinstance(raw_text, str) else {},
                provider=self.provider_name,
                model_id=self.model_id,
                request_id=payload.get("id"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                tool_calls=tool_calls,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            reason = "provider_timeout" if isinstance(exc, httpx.TimeoutException) else "provider_http_failure"
            raise ProviderError(
                "Provider request timed out or was unreachable",
                retryable=True,
                reason_code=reason,
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "Provider output was not valid JSON",
                reason_code="schema_validation_failed",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


def provider_from_settings(settings: Settings) -> CopilotProvider:
    """Build exactly one configured provider; never fall through to another provider."""
    provider = settings.copilot_provider.strip().lower()
    if provider == "disabled":
        return DisabledProvider()
    if not settings.copilot_model.strip():
        raise ValueError("AMEX_COPILOT_MODEL is required when the copilot provider is enabled")
    if provider == "openai":
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for the configured provider")
        return OpenAIResponsesProvider(
            model_id=settings.copilot_model,
            api_key=settings.openai_api_key.get_secret_value(),
            endpoint=settings.openai_endpoint,
            timeout_seconds=settings.copilot_timeout_seconds,
        )
    if provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required for the configured provider")
        return AnthropicMessagesProvider(
            model_id=settings.copilot_model,
            api_key=settings.anthropic_api_key.get_secret_value(),
            endpoint=settings.anthropic_endpoint,
            timeout_seconds=settings.copilot_timeout_seconds,
        )
    raise ValueError("AMEX_COPILOT_PROVIDER must be disabled, openai, or anthropic")
