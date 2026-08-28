"""Application service implementing the frozen REST resources over typed projections."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from backend.application.clean_projection import build_clean_projection
from backend.application.live_updates import LiveUpdateBroker
from backend.application.simulator_client import SimulatorTransportError
from backend.config.settings import Settings
from backend.contracts.api import (
    CopilotFeedbackRequest,
    CopilotInteractionView,
    CopilotMessagePage,
    CopilotThreadSummary,
    CursorPage,
    DeterministicFallback,
    EvidenceDetailResponse,
    EvidenceProjectionResponse,
    HumanReviewRequest,
    HumanReviewView,
    IncidentDetail,
    IncidentSummary,
    IncidentWorkspaceResponse,
    MetricHistoryResponse,
    ResourceVersion,
    RetryState,
    SimulationStatus,
    SubmitCopilotQueryRequest,
    SubmitCopilotQueryResponse,
    SystemOverviewResponse,
)
from backend.contracts.enums import IncidentSeverity, MetricKey, SimulationAction
from backend.copilot.models import CopilotContext
from backend.copilot.orchestrator import CopilotOrchestrator
from backend.evidence.runbooks import RunbookRepository
from backend.persistence.runtime_store import RuntimeStore


class Simulator(Protocol):
    SCENARIO_ID: str

    async def start(self, client_request_id: str) -> SimulationStatus: ...

    async def inject(self, client_request_id: str) -> SimulationStatus: ...

    async def recover(self, client_request_id: str) -> SimulationStatus: ...

    async def stop(self, client_request_id: str) -> SimulationStatus: ...

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus: ...


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


class InvestigatorService:
    def __init__(
        self,
        store: RuntimeStore,
        simulator: Simulator | None = None,
        copilot: CopilotOrchestrator | None = None,
        runtime_reset: Callable[[], Awaitable[None]] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.store = store
        self.simulator = simulator
        self.copilot = copilot
        self.runtime_reset = runtime_reset
        self.settings = settings
        self.broker = LiveUpdateBroker(store)
        self._mutation_lock = asyncio.Lock()
        self._copilot_tasks: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        await self.store.migrate()
        if await self.store.get_resource("overview", "current") is not None:
            return
        projection = build_clean_projection(settings=self.settings)
        await self.store.put_resource(
            "overview", "current", projection.overview.model_dump(mode="json")
        )
        await self.store.put_resource(
            "metric_history",
            MetricKey.TECHNICAL_ERROR_RATE.value,
            projection.history.model_dump(mode="json"),
        )
        await self.store.put_resource(
            "simulation", "current", projection.simulation.model_dump(mode="json")
        )

    async def wait_for_copilot_tasks(self) -> None:
        """Drain bounded background work during tests and graceful application shutdown."""
        while self._copilot_tasks:
            await asyncio.gather(*tuple(self._copilot_tasks), return_exceptions=True)

    async def overview(self) -> SystemOverviewResponse:
        return SystemOverviewResponse.model_validate(
            await self._required("overview", "current", "System overview is unavailable")
        )

    async def metric_history(
        self, metric_key: MetricKey, start_at: datetime, end_at: datetime
    ) -> MetricHistoryResponse:
        if end_at <= start_at:
            raise ServiceError(422, "VALIDATION_ERROR", "end_at must be after start_at")
        payload = await self.store.get_resource("metric_history", metric_key.value)
        if payload is None:
            technical = MetricHistoryResponse.model_validate(
                await self._required(
                    "metric_history",
                    MetricKey.TECHNICAL_ERROR_RATE.value,
                    "Metric history unavailable",
                )
            )
            overview = await self.overview()
            metric_value = getattr(overview.metrics, metric_key.value)
            payload = technical.model_copy(
                update={
                    "metric_key": metric_key,
                    "unit": metric_value.unit,
                    "points": [
                        point.model_copy(update={"value": metric_value.value})
                        for point in technical.points
                    ],
                }
            ).model_dump(mode="json")
        result = MetricHistoryResponse.model_validate(payload)
        return result.model_copy(
            update={
                "period": result.period.model_copy(update={"start_at": start_at, "end_at": end_at}),
                "points": [point for point in result.points if start_at <= point.at <= end_at],
            }
        )

    async def list_incidents(
        self,
        *,
        started_at_or_after: datetime | None = None,
        started_before: datetime | None = None,
        severity: list[IncidentSeverity] | None = None,
        processing_region: list[str] | None = None,
        payment_method: list[str] | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        cursor: str | None = None,
    ) -> CursorPage[IncidentSummary]:
        if cursor not in {None, ""}:
            raise ServiceError(422, "VALIDATION_ERROR", "The supplied cursor is invalid")
        items = [
            IncidentSummary.model_validate(payload)
            for payload in await self.store.list_resources("incident_summary")
        ]
        if started_at_or_after:
            items = [item for item in items if item.started_at >= started_at_or_after]
        if started_before:
            items = [item for item in items if item.started_at < started_before]
        if severity:
            items = [item for item in items if item.severity in severity]
        if processing_region:
            items = [
                item
                for item in items
                if item.affected_scope
                and item.affected_scope.processing_region in processing_region
            ]
        if payment_method:
            items = [
                item
                for item in items
                if item.affected_scope and item.affected_scope.payment_method in payment_method
            ]
        key_name = sort_by or "started_at"
        if key_name not in {"started_at", "severity", "lifecycle"}:
            raise ServiceError(422, "VALIDATION_ERROR", "Unsupported incident sort field")
        items.sort(
            key=lambda item: getattr(item, key_name),
            reverse=sort_direction != "asc",
        )
        return CursorPage[IncidentSummary](items=items, next_cursor=None)

    async def incident(self, incident_id: str) -> IncidentWorkspaceResponse:
        return IncidentWorkspaceResponse.model_validate(
            await self._required("incident", incident_id, "Incident was not found")
        )

    async def evidence(
        self,
        incident_id: str,
        evidence_package_id: str | None = None,
        evidence_package_version: int | None = None,
    ) -> EvidenceProjectionResponse:
        result = EvidenceProjectionResponse.model_validate(
            await self._required("evidence", incident_id, "Evidence package was not found")
        )
        if evidence_package_id and evidence_package_id != result.evidence_package_id:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Evidence package was not found")
        if evidence_package_version and evidence_package_version != result.evidence_package_version:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Evidence package version was not found")
        return result

    async def evidence_detail(self, incident_id: str, evidence_id: str) -> EvidenceDetailResponse:
        package = await self.evidence(incident_id)
        item = next(
            (candidate for candidate in package.items if candidate.evidence_id == evidence_id), None
        )
        if item is None:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Evidence item was not found")
        return EvidenceDetailResponse(
            incident_id=incident_id,
            evidence_package_id=package.evidence_package_id,
            evidence_package_version=package.evidence_package_version,
            item=item,
            calculation_method=(
                "Deterministic bounded comparison"
                if item.category.value == "DERIVED_FINDING"
                else None
            ),
            calculation_lineage=[item.source_module, item.source_version],
            source_references=[item.stable_logical_key],
        )

    async def copilot_messages(self, incident_id: str) -> CopilotMessagePage:
        await self.incident(incident_id)
        return CopilotMessagePage.model_validate(
            await self._required("copilot_messages", incident_id, "Copilot thread was not found")
        )

    async def submit_copilot_query(
        self, incident_id: str, request: SubmitCopilotQueryRequest
    ) -> SubmitCopilotQueryResponse:
        workspace = await self.incident(incident_id)
        if (
            request.evidence_package_id != workspace.evidence_package_id
            or request.evidence_package_version != workspace.evidence_package_version
        ):
            raise ServiceError(
                409, "VERSION_CONFLICT", "The evidence package version is no longer active"
            )
        cached = await self.store.get_command("copilot-query", request.client_request_id)
        if cached:
            return SubmitCopilotQueryResponse.model_validate(cached)
        accepted_at = datetime.now(UTC)
        interaction_id = f"int_{uuid4().hex}"
        interaction = CopilotInteractionView(
            interaction_id=interaction_id,
            status="QUEUED",
            progress_stage="QUEUED",
            progress_updated_at=accepted_at,
            retry=RetryState(eligible=False, unavailable_reason="Interaction is still queued"),
        )
        response = SubmitCopilotQueryResponse(
            interaction_id=interaction_id,
            accepted_at=accepted_at,
            evidence_package_id=request.evidence_package_id,
            evidence_package_version=request.evidence_package_version,
        )
        await self.store.put_resource(
            "copilot_interaction", interaction_id, interaction.model_dump(mode="json")
        )
        await self.store.put_command(
            "copilot-query", request.client_request_id, response.model_dump(mode="json")
        )
        await self.broker.publish(
            "copilot.progress.updated",
            {"incident_id": incident_id, "interaction_id": interaction_id, "stage": "QUEUED"},
        )
        await self.store.put_resource(
            "copilot_request",
            interaction_id,
            {
                "incident_id": incident_id,
                "question": request.question,
                "evidence_package_id": request.evidence_package_id,
                "evidence_package_version": request.evidence_package_version,
            },
        )
        if self.copilot is not None:
            task = asyncio.create_task(
                self._run_copilot(interaction_id, incident_id, request.question),
                name=f"copilot-{interaction_id}",
            )
            self._copilot_tasks.add(task)
            task.add_done_callback(self._copilot_tasks.discard)
        return response

    async def request_initial_copilot_report(self, incident_id: str) -> CopilotInteractionView:
        """Idempotently queue the automatic first thread message for a pinned package/config."""
        if self.copilot is None:
            raise ServiceError(503, "COPILOT_UNAVAILABLE", "Copilot orchestration is unavailable")
        async with self._mutation_lock:
            workspace = await self.incident(incident_id)
            cache_material = (
                f"{incident_id}:{workspace.evidence_package_id}:"
                f"{workspace.evidence_package_version}:{self.copilot.configuration.version}"
            )
            interaction_id = f"int_initial_{sha256(cache_material.encode()).hexdigest()[:24]}"
            existing = await self.store.get_resource("copilot_interaction", interaction_id)
            if existing is not None:
                return CopilotInteractionView.model_validate(existing)
            queued = CopilotInteractionView(
                interaction_id=interaction_id,
                status="QUEUED",
                progress_stage="QUEUED",
                progress_updated_at=datetime.now(UTC),
                retry=RetryState(eligible=False, unavailable_reason="Interaction is still queued"),
            )
            await self.store.put_resource(
                "copilot_interaction", interaction_id, queued.model_dump(mode="json")
            )
            await self.store.put_resource(
                "copilot_request",
                interaction_id,
                {
                    "incident_id": incident_id,
                    "question": None,
                    "evidence_package_id": workspace.evidence_package_id,
                    "evidence_package_version": workspace.evidence_package_version,
                },
            )
            await self._update_copilot_summary(incident_id, queued)
            task = asyncio.create_task(
                self._run_copilot(interaction_id, incident_id, None),
                name=f"copilot-initial-{interaction_id}",
            )
            self._copilot_tasks.add(task)
            task.add_done_callback(self._copilot_tasks.discard)
            return queued

    async def copilot_interaction(
        self, incident_id: str, interaction_id: str
    ) -> CopilotInteractionView:
        await self.incident(incident_id)
        return CopilotInteractionView.model_validate(
            await self._required(
                "copilot_interaction", interaction_id, "Copilot interaction was not found"
            )
        )

    async def retry_copilot(self, incident_id: str, interaction_id: str) -> CopilotInteractionView:
        interaction = await self.copilot_interaction(incident_id, interaction_id)
        if not interaction.retry.eligible:
            raise ServiceError(
                409,
                "COPILOT_UNAVAILABLE",
                interaction.retry.unavailable_reason or "This interaction cannot be retried",
            )
        if self.copilot is None:
            raise ServiceError(503, "COPILOT_UNAVAILABLE", "Copilot provider is unavailable")
        request = await self._required(
            "copilot_request", interaction_id, "Original Copilot request was not found"
        )
        queued = interaction.model_copy(
            update={
                "status": "QUEUED",
                "progress_stage": "QUEUED",
                "progress_updated_at": datetime.now(UTC),
                "retry": RetryState(eligible=False, unavailable_reason="Manual retry already used"),
            }
        )
        await self.store.put_resource(
            "copilot_interaction", interaction_id, queued.model_dump(mode="json")
        )
        await self.store.put_resource(
            "copilot_retry_used", interaction_id, {"used_at": datetime.now(UTC).isoformat()}
        )
        original_question = request.get("question")
        task = asyncio.create_task(
            self._run_copilot(
                interaction_id,
                incident_id,
                str(original_question) if original_question is not None else None,
            ),
            name=f"copilot-retry-{interaction_id}",
        )
        self._copilot_tasks.add(task)
        task.add_done_callback(self._copilot_tasks.discard)
        return queued

    async def _run_copilot(
        self, interaction_id: str, incident_id: str, question: str | None
    ) -> None:
        if self.copilot is None:
            return
        try:
            context = await self._copilot_context(interaction_id, incident_id, question)

            async def progress(stage: str) -> None:
                current = CopilotInteractionView(
                    interaction_id=interaction_id,
                    status="IN_PROGRESS",
                    progress_stage=stage,
                    progress_updated_at=datetime.now(UTC),
                    retry=RetryState(
                        eligible=False, unavailable_reason="Interaction is still in progress"
                    ),
                )
                await self.store.put_resource(
                    "copilot_interaction", interaction_id, current.model_dump(mode="json")
                )
                if question is None:
                    await self._update_copilot_summary(incident_id, current)
                await self.broker.publish(
                    "copilot.progress.updated",
                    {"incident_id": incident_id, "interaction_id": interaction_id, "stage": stage},
                )

            result = await self.copilot.run(context, progress=progress)
            interaction = result.interaction
            if await self.store.get_resource("copilot_retry_used", interaction_id) is not None:
                interaction = interaction.model_copy(
                    update={
                        "retry": RetryState(
                            eligible=False, unavailable_reason="Manual retry already used"
                        )
                    }
                )
            await self.store.put_resource(
                "copilot_interaction",
                interaction_id,
                interaction.model_dump(mode="json"),
            )
            if question is None:
                await self._update_copilot_summary(incident_id, interaction)
            validated = result.message.model_dump(mode="json") if result.message else None
            await self.store.save_copilot_interaction(
                result.audit.model_dump(mode="json"), result.raw_output, validated
            )
            for tool_result in result.tool_results:
                await self.store.put_resource(
                    "copilot_tool_evidence",
                    tool_result.evidence_id,
                    {
                        "evidence_id": tool_result.evidence_id,
                        "incident_id": incident_id,
                        "evidence_package_id": context.evidence_package_id,
                        "evidence_package_version": context.evidence_package_version,
                        "tool_name": tool_result.tool_name,
                        "arguments": tool_result.arguments,
                        "occurred_at": tool_result.occurred_at.isoformat(),
                        "temporal_scope": tool_result.temporal_scope,
                        "payload": tool_result.payload,
                    },
                )
            if result.message is not None:
                page = await self.copilot_messages(incident_id)
                items = [
                    item for item in page.items if item.message_id != result.message.message_id
                ]
                items.append(result.message)
                updated_page = CopilotMessagePage(items=items[-8:], next_cursor=None)
                await self.store.put_resource(
                    "copilot_messages", incident_id, updated_page.model_dump(mode="json")
                )
                await self.broker.publish(
                    "copilot.message.validated",
                    {
                        "incident_id": incident_id,
                        "interaction_id": interaction_id,
                        "message_id": result.message.message_id,
                    },
                )
            else:
                await self.broker.publish(
                    "copilot.fallback.ready",
                    {"incident_id": incident_id, "interaction_id": interaction_id},
                )
        except Exception:
            failed = CopilotInteractionView(
                interaction_id=interaction_id,
                status="FAILED",
                progress_updated_at=datetime.now(UTC),
                deterministic_fallback=fallback_for("ORCHESTRATION_FAILURE"),
                retry=RetryState(eligible=True, unavailable_reason="One manual retry is available"),
            )
            await self.store.put_resource(
                "copilot_interaction", interaction_id, failed.model_dump(mode="json")
            )
            if question is None:
                await self._update_copilot_summary(incident_id, failed)
            await self.broker.publish(
                "copilot.fallback.ready",
                {"incident_id": incident_id, "interaction_id": interaction_id},
            )

    async def _copilot_context(
        self, interaction_id: str, incident_id: str, question: str | None
    ) -> CopilotContext:
        workspace = await self.incident(incident_id)
        evidence = await self.evidence(incident_id)
        leading = workspace.rca_summary.leading_hypothesis
        alternatives = workspace.rca_summary.alternatives
        runbooks = RunbookRepository.from_directory(
            Path(__file__).resolve().parents[2] / "runbooks"
        ).search({"token-validation", "deployment", "gateway"}, limit=3)
        messages = await self.copilot_messages(incident_id)
        return CopilotContext(
            mode="FOLLOW_UP" if question else "INITIAL_ANALYSIS",
            interaction_id=interaction_id,
            incident_id=incident_id,
            question=question,
            evidence_package_id=evidence.evidence_package_id,
            evidence_package_version=evidence.evidence_package_version,
            evidence_completeness=evidence.completeness.value,
            leading_hypothesis_id=leading.hypothesis_id if leading else None,
            evidence_tier=workspace.rca_summary.overall_tier,
            strongest_alternative_id=alternatives[0].hypothesis_id if alternatives else None,
            evidence_items=[item.model_dump(mode="json") for item in evidence.items],
            citation_manifest=[
                item.model_dump(mode="json") for item in evidence.citation_allowlist
            ],
            runbook_sections=[
                {
                    **section.citation.model_dump(mode="json"),
                    "section_title": section.section_title,
                    "approved_guidance_excerpt": section.approved_guidance_excerpt,
                    "guidance_not_incident_proof": True,
                }
                for section in runbooks
            ],
            recent_history=[item.model_dump(mode="json") for item in messages.items[-8:]],
        )

    async def update_human_review(
        self, incident_id: str, request: HumanReviewRequest
    ) -> HumanReviewView:
        async with self._mutation_lock:
            workspace = await self.incident(incident_id)
            summary = IncidentSummary.model_validate(
                await self._required(
                    "incident_summary",
                    incident_id,
                    "Incident summary was not found",
                )
            )
            if workspace.human_review.version != request.expected_version:
                raise ServiceError(
                    409,
                    "VERSION_CONFLICT",
                    "Human review changed; refresh and retry with the latest version",
                    details={"current_version": workspace.human_review.version},
                )
            updated = HumanReviewView(
                hypothesis_id=request.hypothesis_id,
                status=request.status,
                note=request.note,
                reviewed_by="demo-operator",
                updated_at=datetime.now(UTC),
                version=request.expected_version + 1,
            )
            updated_incident = IncidentDetail.model_validate(
                {
                    **workspace.incident.model_dump(),
                    "human_review_status": request.status,
                    "updated_at": updated.updated_at,
                }
            )
            updated_summary = summary.model_copy(
                update={
                    "human_review_status": updated.status,
                    "updated_at": updated.updated_at,
                }
            )
            updated_workspace = workspace.model_copy(
                update={
                    "human_review": updated,
                    "incident": updated_incident,
                    "generated_at": updated.updated_at,
                }
            )
            await self.store.put_resource(
                "incident", incident_id, updated_workspace.model_dump(mode="json"), updated.version
            )
            await self.store.put_resource(
                "incident_summary",
                incident_id,
                updated_summary.model_dump(mode="json"),
                updated.version,
            )
            await self.store.save_human_review(incident_id, updated.model_dump(mode="json"))
            await self.broker.publish(
                "human_review.updated",
                {"incident_id": incident_id, "version": updated.version},
            )
            return updated

    async def submit_feedback(
        self, message_id: str, request: CopilotFeedbackRequest
    ) -> ResourceVersion:
        messages = await self.store.list_resources("copilot_messages")
        known = any(
            message.get("message_id") == message_id
            for page in messages
            for message in page.get("items", [])
        )
        if not known:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Copilot message was not found")
        key = f"{message_id}:latest"
        current = await self.store.get_resource("copilot_feedback", key)
        version = int(current["version"]) + 1 if current else 1
        result = ResourceVersion(updated_at=datetime.now(UTC), version=version)
        payload = {
            **request.model_dump(mode="json"),
            **result.model_dump(mode="json"),
            "message_id": message_id,
        }
        await self.store.put_resource("copilot_feedback", key, payload, version)
        await self.store.save_feedback(message_id, version, payload)
        return result

    async def simulation_status(self) -> SimulationStatus:
        return SimulationStatus.model_validate(
            await self._required("simulation", "current", "Simulation status is unavailable")
        )

    async def simulation_command(
        self,
        action: SimulationAction,
        client_request_id: str,
        *,
        scenario_id: str | None = None,
        confirmation: str | None = None,
    ) -> SimulationStatus:
        if self.simulator is None:
            raise ServiceError(
                503,
                "DEPENDENCY_UNAVAILABLE",
                "Simulator dependency is unavailable",
                retryable=True,
            )
        scope = f"simulation:{action.value}"
        cached = await self.store.get_command(scope, client_request_id)
        if cached:
            return SimulationStatus.model_validate(cached)
        try:
            if action == SimulationAction.START:
                result = await self.simulator.start(client_request_id)
            elif action == SimulationAction.INJECT_DEPLOYMENT_REGRESSION:
                if scenario_id != self.simulator.SCENARIO_ID:
                    raise ServiceError(
                        400, "SCENARIO_NOT_ALLOWED", "The requested scenario is not allowlisted"
                    )
                result = await self.simulator.inject(client_request_id)
            elif action == SimulationAction.TRIGGER_ROLLBACK_RECOVERY:
                result = await self.simulator.recover(client_request_id)
            elif action == SimulationAction.STOP:
                result = await self.simulator.stop(client_request_id)
            elif action == SimulationAction.RESET:
                if confirmation != "RESET_SYNTHETIC_DEMO":
                    raise ServiceError(
                        400, "VALIDATION_ERROR", "Synthetic reset confirmation is required"
                    )
                result = await self.simulator.reset(client_request_id, confirmation)
                await self.store.reset_synthetic_data()
                await self.initialize()
                if self.runtime_reset is not None:
                    await self.runtime_reset()
            else:
                raise ServiceError(400, "VALIDATION_ERROR", "Unsupported simulation action")
        except SimulatorTransportError as exc:
            raise ServiceError(
                503,
                "DEPENDENCY_UNAVAILABLE",
                str(exc),
                retryable=True,
            ) from exc
        payload = result.model_dump(mode="json")
        await self.store.put_resource("simulation", "current", payload)
        await self.store.put_command(scope, client_request_id, payload)
        await self.broker.publish(
            "simulation.status.changed",
            {"state": result.state.value, "active_scenario_id": result.active_scenario_id},
        )
        await self.broker.publish("system.overview.updated", {"resource": "system/overview"})
        return result

    async def _update_copilot_summary(
        self, incident_id: str, interaction: CopilotInteractionView
    ) -> None:
        payload = await self.store.get_resource("incident", incident_id)
        if payload is None:
            return
        workspace = IncidentWorkspaceResponse.model_validate(payload)
        existing = workspace.copilot_summary
        summary = CopilotThreadSummary(
            thread_available=True,
            initial_analysis_status=interaction.status,
            latest_interaction_id=interaction.interaction_id,
            latest_validated_message_id=(
                interaction.validated_message_id or existing.latest_validated_message_id
            ),
        )
        updated = workspace.model_copy(update={"copilot_summary": summary})
        await self.store.put_resource("incident", incident_id, updated.model_dump(mode="json"))

    async def _required(
        self, resource_type: str, resource_key: str, message: str
    ) -> dict[str, Any]:
        payload = await self.store.get_resource(resource_type, resource_key)
        if payload is None:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", message)
        return payload


def fallback_for(reason_code: str) -> DeterministicFallback:
    controlled = {
        "provider_disabled",
        "provider_timeout",
        "provider_http_failure",
        "schema_validation_failed",
        "citation_validation_failed",
        "policy_validation_failed",
        "circuit_open",
        "evidence_unavailable",
        "unexpected_internal_failure",
    }
    return DeterministicFallback(
        available=True,
        reason_code=(reason_code if reason_code in controlled else "unexpected_internal_failure"),
        summary="Validated deterministic incident findings remain available.",
    )
