"""Application service implementing the frozen REST resources over typed projections."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
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
    CanonicalCopilotMessagePage,
    CopilotFeedbackRequest,
    CopilotInteractionView,
    CopilotMessage,
    CopilotMessagePage,
    CopilotThread,
    CopilotThreadResponse,
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
    SubmitCopilotMessageRequest,
    SubmitCopilotMessageResponse,
    SystemOverviewResponse,
)
from backend.contracts.enums import IncidentSeverity, MetricKey, SimulationAction
from backend.copilot.models import CopilotContext
from backend.copilot.orchestrator import CopilotOrchestrator
from backend.copilot.prompts import build_history_digest
from backend.evidence.builder import EvidenceBuilder, EvidencePackage
from backend.evidence.runbooks import RunbookRepository
from backend.persistence.runtime_store import RuntimeStore


class Simulator(Protocol):
    SCENARIO_ID: str

    async def status(self) -> SimulationStatus: ...

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

    async def initialize(self, *, migrate: bool = True) -> None:
        if migrate:
            await self.store.migrate()
        projection = None
        overview = await self.store.get_resource("overview", "current")
        if overview is None:
            projection = build_clean_projection(settings=self.settings)
            await self.store.put_resource(
                "overview", "current", projection.overview.model_dump(mode="json")
            )
            await self.store.put_resource(
                "metric_history",
                MetricKey.TECHNICAL_ERROR_RATE.value,
                projection.history.model_dump(mode="json"),
            )
        else:
            if "telemetry_stale_after_seconds" not in overview:
                overview = {
                    **overview,
                    "telemetry_stale_after_seconds": (
                        self.settings.telemetry_stale_after_seconds if self.settings else 30
                    ),
                }
                await self.store.put_resource("overview", "current", overview)
        if await self.store.get_resource("simulation", "current") is None:
            projection = projection or build_clean_projection(settings=self.settings)
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

    async def select_copilot_evidence_package(self, incident_id: str) -> dict[str, Any]:
        """Resolve one eligible incident-owned immutable package for a new request."""
        workspace = await self.incident(incident_id)
        current = await self.store.get_evidence_package(
            incident_id,
            workspace.evidence_package_id,
            workspace.evidence_package_version,
        )
        if current is None:
            projected = await self.store.get_resource("evidence", incident_id)
            if projected is not None:
                current = {
                    **projected,
                    "package_version": projected["evidence_package_version"],
                    "schema_version": "evidence-package.v1",
                    "builder_configuration_version": "legacy-projection",
                }
        eligible = {"COMPLETE", "PARTIAL"}
        lifecycle = workspace.incident.lifecycle
        if lifecycle in {"OPEN", "RECOVERY_CANDIDATE"} and current is not None:
            if current.get("completeness") in eligible:
                return current
        latest = await self.store.get_latest_evidence_package(incident_id)
        if latest is not None:
            return latest
        if current is not None and current.get("completeness") in eligible:
            return current
        raise ServiceError(
            409,
            "COPILOT_UNAVAILABLE",
            "No eligible evidence package is available for this incident",
        )

    async def copilot_thread(self, incident_id: str) -> CopilotThreadResponse:
        await self.incident(incident_id)
        thread_payload = await self.store.get_or_create_copilot_thread(
            incident_id, datetime.now(UTC)
        )
        rows, next_sequence = await self.store.list_copilot_messages(
            thread_payload["thread_id"],
            incident_id,
            after_sequence=None,
            limit=50,
        )
        return CopilotThreadResponse(
            thread=CopilotThread.model_validate(
                {
                    key: value
                    for key, value in thread_payload.items()
                    if key != "history_digest"
                }
            ),
            messages=CanonicalCopilotMessagePage(
                items=[CopilotMessage.model_validate(row) for row in rows],
                next_cursor=(
                    self._encode_copilot_cursor(thread_payload["thread_id"], next_sequence)
                    if next_sequence is not None
                    else None
                ),
            ),
        )

    async def canonical_copilot_messages(
        self, incident_id: str, cursor: str | None = None
    ) -> CanonicalCopilotMessagePage:
        await self.incident(incident_id)
        thread = await self.store.get_or_create_copilot_thread(incident_id, datetime.now(UTC))
        after_sequence = (
            self._decode_copilot_cursor(cursor, thread["thread_id"])
            if cursor
            else None
        )
        rows, next_sequence = await self.store.list_copilot_messages(
            thread["thread_id"],
            incident_id,
            after_sequence=after_sequence,
            limit=50,
        )
        return CanonicalCopilotMessagePage(
            items=[CopilotMessage.model_validate(row) for row in rows],
            next_cursor=(
                self._encode_copilot_cursor(thread["thread_id"], next_sequence)
                if next_sequence is not None
                else None
            ),
        )

    @staticmethod
    def _encode_copilot_cursor(thread_id: str, sequence: int) -> str:
        raw = json.dumps(
            {"thread_id": thread_id, "after_sequence": sequence},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_copilot_cursor(cursor: str, expected_thread_id: str) -> int:
        try:
            padding = "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if (
                not isinstance(payload, dict)
                or payload.get("thread_id") != expected_thread_id
                or not isinstance(payload.get("after_sequence"), int)
                or payload["after_sequence"] < 1
            ):
                raise ValueError("invalid cursor payload")
            return int(payload["after_sequence"])
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
            raise ServiceError(
                422, "VALIDATION_ERROR", "The supplied Copilot cursor is invalid"
            ) from exc

    async def submit_copilot_message(
        self, incident_id: str, request: SubmitCopilotMessageRequest
    ) -> SubmitCopilotMessageResponse:
        async with self._mutation_lock:
            thread_view = await self.copilot_thread(incident_id)
            thread = thread_view.thread
            command_scope = f"copilot-message:{incident_id}:{thread.thread_id}"
            cached = await self.store.get_command(command_scope, request.client_request_id)
            if cached is not None:
                return SubmitCopilotMessageResponse.model_validate(cached)

            for message_id in request.referenced_message_ids:
                referenced = await self.store.get_copilot_message(incident_id, message_id)
                if referenced is None or referenced["thread_id"] != thread.thread_id:
                    raise ServiceError(
                        422,
                        "VALIDATION_ERROR",
                        "A referenced Copilot message is not part of this incident thread",
                    )

            package = await self.select_copilot_evidence_package(incident_id)
            package_id = str(package["evidence_package_id"])
            package_version = int(
                package.get("package_version", package.get("evidence_package_version"))
            )
            accepted_at = datetime.now(UTC)
            interaction_id = f"int_{uuid4().hex}"
            user_message_id = f"msg_{uuid4().hex}"
            transition_message: dict[str, Any] | None = None
            if (
                thread.latest_evidence_package_id is not None
                and thread.latest_evidence_package_version is not None
                and (
                    thread.latest_evidence_package_id != package_id
                    or thread.latest_evidence_package_version != package_version
                )
            ):
                transition_key = (
                    f"{thread.thread_id}:{thread.latest_evidence_package_id}:"
                    f"{thread.latest_evidence_package_version}:{package_id}:{package_version}"
                )
                transition_message = {
                    "message_id": (
                        "msg_notice_" + sha256(transition_key.encode()).hexdigest()[:24]
                    ),
                    "role": "SYSTEM",
                    "content_type": "EVIDENCE_VERSION_NOTICE",
                    "content": {
                        "type": "EVIDENCE_VERSION_NOTICE",
                        "previous_evidence_package_id": thread.latest_evidence_package_id,
                        "previous_evidence_package_version": (
                            thread.latest_evidence_package_version
                        ),
                        "evidence_package_id": package_id,
                        "evidence_package_version": package_version,
                        "summary": (
                            "Newer incident evidence is available. New answers use the "
                            "updated snapshot; earlier answers keep their original evidence."
                        ),
                    },
                    "created_at": accepted_at,
                }
            user_message = {
                "message_id": user_message_id,
                "role": "USER",
                "content_type": "USER_QUESTION",
                "content": {
                    "type": "USER_QUESTION",
                    "question": request.question.strip(),
                    "referenced_message_ids": request.referenced_message_ids,
                },
                "client_request_id": request.client_request_id,
                "created_at": accepted_at,
            }
            interaction = CopilotInteractionView(
                interaction_id=interaction_id,
                incident_id=incident_id,
                thread_id=thread.thread_id,
                status="QUEUED",
                progress_stage="QUEUED",
                progress_updated_at=accepted_at,
                retry=RetryState(
                    eligible=False, unavailable_reason="Interaction is still queued"
                ),
            )
            response = SubmitCopilotMessageResponse(
                interaction_id=interaction_id,
                thread_id=thread.thread_id,
                user_message_id=user_message_id,
                accepted_at=accepted_at,
                evidence_package_id=package_id,
                evidence_package_version=package_version,
            )
            accepted_payload = await self.store.accept_copilot_request(
                thread_id=thread.thread_id,
                incident_id=incident_id,
                command_scope=command_scope,
                client_request_id=request.client_request_id,
                user_message=user_message,
                transition_message=transition_message,
                interaction=interaction.model_dump(mode="json"),
                request_record={
                    "incident_id": incident_id,
                    "thread_id": thread.thread_id,
                    "user_message_id": user_message_id,
                    "question": request.question.strip(),
                    "referenced_message_ids": request.referenced_message_ids,
                    "evidence_package_id": package_id,
                    "evidence_package_version": package_version,
                },
                response=response.model_dump(mode="json"),
                evidence_package_id=package_id,
                evidence_package_version=package_version,
                updated_at=accepted_at,
            )
            response = SubmitCopilotMessageResponse.model_validate(accepted_payload)
            newly_accepted = response.interaction_id == interaction_id
            if newly_accepted:
                await self.broker.publish(
                    "copilot.progress.updated",
                    {
                        "incident_id": incident_id,
                        "interaction_id": interaction_id,
                        "stage": "QUEUED",
                    },
                )
            if self.copilot is not None and newly_accepted:
                task = asyncio.create_task(
                    self._run_copilot(interaction_id, incident_id, request.question.strip()),
                    name=f"copilot-{interaction_id}",
                )
                self._copilot_tasks.add(task)
                task.add_done_callback(self._copilot_tasks.discard)
            return response

    async def copilot_messages(self, incident_id: str) -> CopilotMessagePage:
        await self.incident(incident_id)
        return CopilotMessagePage.model_validate(
            await self._required("copilot_messages", incident_id, "Copilot thread was not found")
        )

    async def submit_copilot_query(
        self, incident_id: str, request: SubmitCopilotQueryRequest
    ) -> SubmitCopilotQueryResponse:
        accepted = await self.submit_copilot_message(
            incident_id,
            SubmitCopilotMessageRequest(
                question=request.question,
                client_request_id=request.client_request_id,
            ),
        )
        return SubmitCopilotQueryResponse(
            interaction_id=accepted.interaction_id,
            accepted_at=accepted.accepted_at,
            evidence_package_id=accepted.evidence_package_id,
            evidence_package_version=accepted.evidence_package_version,
        )

    async def request_initial_copilot_report(self, incident_id: str) -> CopilotInteractionView:
        """Idempotently queue the automatic first thread message for a pinned package/config."""
        if self.copilot is None:
            raise ServiceError(503, "COPILOT_UNAVAILABLE", "Copilot orchestration is unavailable")
        async with self._mutation_lock:
            workspace = await self.incident(incident_id)
            thread = (await self.copilot_thread(incident_id)).thread
            package = await self.select_copilot_evidence_package(incident_id)
            package_id = str(package["evidence_package_id"])
            package_version = int(
                package.get("package_version", package.get("evidence_package_version"))
            )
            cache_material = (
                f"{incident_id}:{thread.thread_id}:{package_id}:"
                f"{package_version}:{self.copilot.configuration.version}"
            )
            interaction_id = f"int_initial_{sha256(cache_material.encode()).hexdigest()[:24]}"
            existing = await self.store.get_resource("copilot_interaction", interaction_id)
            if existing is not None:
                return CopilotInteractionView.model_validate(existing)
            queued = CopilotInteractionView(
                interaction_id=interaction_id,
                incident_id=incident_id,
                thread_id=thread.thread_id,
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
                    "thread_id": thread.thread_id,
                    "user_message_id": None,
                    "question": None,
                    "referenced_message_ids": [],
                    "evidence_package_id": package_id,
                    "evidence_package_version": package_version,
                },
            )
            await self.store.update_copilot_thread(
                thread.thread_id,
                incident_id,
                history_digest=(
                    (await self.store.get_copilot_thread(incident_id) or {}).get(
                        "history_digest", {}
                    )
                ),
                evidence_package_id=package_id,
                evidence_package_version=package_version,
                updated_at=datetime.now(UTC),
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
        payload = await self._required(
            "copilot_interaction", interaction_id, "Copilot interaction was not found"
        )
        owner = payload.get("incident_id")
        if owner is None:
            request = await self.store.get_resource("copilot_request", interaction_id)
            owner = request.get("incident_id") if request else None
        if owner is None:
            legacy = await self.store.get_resource("copilot_messages", incident_id)
            if not any(
                item.get("interaction_id") == interaction_id
                for item in (legacy or {}).get("items", [])
            ):
                raise ServiceError(
                    404, "RESOURCE_NOT_FOUND", "Copilot interaction was not found"
                )
        elif owner != incident_id:
            raise ServiceError(
                404, "RESOURCE_NOT_FOUND", "Copilot interaction was not found"
            )
        return CopilotInteractionView.model_validate(payload)

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
                    incident_id=incident_id,
                    thread_id=context.thread_id,
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
            request = await self._required(
                "copilot_request", interaction_id, "Original Copilot request was not found"
            )
            response_message_id = (
                "msg_response_" + sha256(interaction_id.encode()).hexdigest()[:24]
            )
            if result.message is not None:
                stored = await self.store.upsert_copilot_response(
                    context.thread_id or str(request["thread_id"]),
                    incident_id,
                    {
                        "message_id": response_message_id,
                        "role": "ASSISTANT",
                        "content_type": "COPILOT_ANSWER",
                        "content": result.message.model_dump(mode="json"),
                        "interaction_id": interaction_id,
                        "response_to_message_id": request.get("user_message_id"),
                        "evidence_package_id": context.evidence_package_id,
                        "evidence_package_version": context.evidence_package_version,
                        "created_at": datetime.now(UTC),
                    },
                )
                interaction = interaction.model_copy(
                    update={"validated_message_id": stored["message_id"]}
                )
                await self.broker.publish(
                    "copilot.message.validated",
                    {
                        "incident_id": incident_id,
                        "interaction_id": interaction_id,
                        "message_id": stored["message_id"],
                    },
                )
            else:
                fallback = interaction.deterministic_fallback or fallback_for(
                    "unexpected_internal_failure"
                )
                await self.store.upsert_copilot_response(
                    context.thread_id or str(request["thread_id"]),
                    incident_id,
                    {
                        "message_id": response_message_id,
                        "role": "ASSISTANT",
                        "content_type": "DETERMINISTIC_FALLBACK",
                        "content": {
                            "type": "DETERMINISTIC_FALLBACK",
                            "label": "Deterministic fallback",
                            "summary": fallback.summary,
                            "reason_code": fallback.reason_code,
                            "retry_eligible": interaction.retry.eligible,
                        },
                        "interaction_id": interaction_id,
                        "response_to_message_id": request.get("user_message_id"),
                        "evidence_package_id": context.evidence_package_id,
                        "evidence_package_version": context.evidence_package_version,
                        "created_at": datetime.now(UTC),
                    },
                )
                await self.broker.publish(
                    "copilot.fallback.ready",
                    {"incident_id": incident_id, "interaction_id": interaction_id},
                )
            await self.store.put_resource(
                "copilot_interaction",
                interaction_id,
                interaction.model_dump(mode="json"),
            )
            if question is None:
                await self._update_copilot_summary(incident_id, interaction)
        except Exception:
            request = await self.store.get_resource("copilot_request", interaction_id) or {}
            fallback = fallback_for("unexpected_internal_failure")
            failed = CopilotInteractionView(
                interaction_id=interaction_id,
                incident_id=incident_id,
                thread_id=request.get("thread_id"),
                status="FALLBACK",
                progress_updated_at=datetime.now(UTC),
                deterministic_fallback=fallback,
                retry=RetryState(eligible=True, unavailable_reason="One manual retry is available"),
            )
            if request.get("thread_id") is not None:
                await self.store.upsert_copilot_response(
                    str(request["thread_id"]),
                    incident_id,
                    {
                        "message_id": "msg_response_"
                        + sha256(interaction_id.encode()).hexdigest()[:24],
                        "role": "ASSISTANT",
                        "content_type": "DETERMINISTIC_FALLBACK",
                        "content": {
                            "type": "DETERMINISTIC_FALLBACK",
                            "label": "Deterministic fallback",
                            "summary": fallback.summary,
                            "reason_code": fallback.reason_code,
                            "retry_eligible": True,
                        },
                        "interaction_id": interaction_id,
                        "response_to_message_id": request.get("user_message_id"),
                        "evidence_package_id": request.get("evidence_package_id"),
                        "evidence_package_version": request.get("evidence_package_version"),
                        "created_at": datetime.now(UTC),
                    },
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
        request = await self._required(
            "copilot_request", interaction_id, "Original Copilot request was not found"
        )
        if request.get("incident_id") != incident_id:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Copilot request was not found")
        workspace = await self.incident(incident_id)
        package_id = str(request["evidence_package_id"])
        package_version = int(request["evidence_package_version"])
        package_payload = await self.store.get_evidence_package(
            incident_id, package_id, package_version
        )
        if package_payload is None:
            raise ServiceError(
                409,
                "COPILOT_UNAVAILABLE",
                "The pinned evidence package is unavailable",
            )
        if "evidence_catalogue" in package_payload:
            evidence = EvidenceBuilder(self.settings or Settings()).dashboard_projection(
                EvidencePackage.model_validate(package_payload)
            )
        else:
            evidence = EvidenceProjectionResponse.model_validate(
                {
                    key: value
                    for key, value in package_payload.items()
                    if key in EvidenceProjectionResponse.model_fields
                }
            )
        if (
            evidence.incident_id != incident_id
            or evidence.evidence_package_id != package_id
            or evidence.evidence_package_version != package_version
        ):
            raise ServiceError(
                409,
                "COPILOT_UNAVAILABLE",
                "The pinned evidence package failed ownership validation",
            )
        leading = next((item for item in evidence.hypotheses if item.is_leading), None)
        alternatives = [item for item in evidence.hypotheses if not item.is_leading]
        runbooks = RunbookRepository.from_directory(
            Path(__file__).resolve().parents[2] / "runbooks"
        ).search({"token-validation", "deployment", "gateway"}, limit=3)
        thread = await self.store.get_copilot_thread(incident_id)
        if thread is None:
            thread = await self.store.get_or_create_copilot_thread(incident_id, datetime.now(UTC))
        rows, _ = await self.store.list_copilot_messages(
            thread["thread_id"], incident_id, after_sequence=None, limit=100
        )
        digest = build_history_digest(rows, recent_limit=8)
        await self.store.update_copilot_thread(
            thread["thread_id"],
            incident_id,
            history_digest=digest,
            evidence_package_id=package_id,
            evidence_package_version=package_version,
            updated_at=datetime.now(UTC),
        )
        referenced_ids = set(request.get("referenced_message_ids", []))
        return CopilotContext(
            mode="FOLLOW_UP" if request.get("question") is not None else "INITIAL_ANALYSIS",
            interaction_id=interaction_id,
            incident_id=incident_id,
            thread_id=thread["thread_id"],
            question=(
                str(request["question"])
                if request.get("question") is not None
                else question
            ),
            evidence_package_id=evidence.evidence_package_id,
            evidence_package_version=evidence.evidence_package_version,
            evidence_completeness=evidence.completeness.value,
            leading_hypothesis_id=leading.hypothesis_id if leading else None,
            evidence_tier=(
                leading.evidence_tier if leading else workspace.rca_summary.overall_tier
            ),
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
            history_digest=digest,
            recent_history=rows[-8:],
            referenced_history=[
                row for row in rows if row["message_id"] in referenced_ids
            ][:8],
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
        self,
        message_id: str,
        request: CopilotFeedbackRequest,
        incident_id: str | None = None,
    ) -> ResourceVersion:
        if incident_id is not None:
            await self.incident(incident_id)
            known = await self.store.get_copilot_message(incident_id, message_id) is not None
        else:
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
            "incident_id": incident_id,
        }
        await self.store.put_resource("copilot_feedback", key, payload, version)
        await self.store.save_feedback(message_id, version, payload)
        return result

    async def simulation_status(self) -> SimulationStatus:
        payload = await self.store.get_resource("simulation", "current")
        if payload is not None:
            return SimulationStatus.model_validate(payload)
        if self.simulator is None:
            raise ServiceError(404, "RESOURCE_NOT_FOUND", "Simulation status is unavailable")
        try:
            status = await self.simulator.status()
        except SimulatorTransportError as exc:
            raise ServiceError(
                503,
                "DEPENDENCY_UNAVAILABLE",
                str(exc),
                retryable=True,
            ) from exc
        await self.store.put_resource(
            "simulation", "current", status.model_dump(mode="json")
        )
        return status

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
                await self.initialize(migrate=False)
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
