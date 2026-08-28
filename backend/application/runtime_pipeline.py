"""Live synthetic ingestion pipeline using the deterministic domain modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.anomaly_detection.detector import DetectionEvaluation, TechnicalErrorDetector
from backend.anomaly_detection.lifecycle import Incident, IncidentLifecycleManager
from backend.config.settings import Settings
from backend.contracts.api import (
    AffectedScopeView,
    BaselineStatus,
    CopilotMessagePage,
    CopilotThreadSummary,
    DetectorSummary,
    ErrorSignatureView,
    EvidenceStatus,
    HumanReviewView,
    IncidentDetail,
    IncidentSummary,
    IncidentTimelineItem,
    IncidentWorkspaceResponse,
    MetricComparison,
    MetricHistoryPoint,
    MetricHistoryResponse,
    MetricValue,
    OverviewMetrics,
    Period,
    PunchlineMetric,
    RcaSummaryView,
    ScopedValue,
    SystemOverviewResponse,
)
from backend.contracts.enums import (
    EvidenceCategory,
    IncidentLifecycle,
    MetricKey,
    OperationalEventType,
)
from backend.contracts.events import OperationalEvent, PaymentEvent
from backend.dimensional_analysis.analyzer import CandidateFinding, DimensionalAnalyzer
from backend.evidence.builder import EvidenceBuilder, IncidentEvidenceInput
from backend.metrics.aggregator import EventTimeAggregator, MetricSnapshot
from backend.persistence.runtime_store import RuntimeStore
from backend.root_cause.engine import RootCauseEngine

PipelineNotifier = Callable[[str, dict[str, Any]], None | Awaitable[None]]


_METRIC_ATTRIBUTES: dict[MetricKey, tuple[str, str, int]] = {
    MetricKey.TECHNICAL_ERROR_RATE: ("technical_error_rate", "RATE", 4),
    MetricKey.APPROVAL_RATE: ("approval_rate", "RATE", 4),
    MetricKey.BUSINESS_DECLINE_RATE: ("business_decline_rate", "RATE", 4),
    MetricKey.THROUGHPUT: ("throughput", "ATTEMPTS_PER_SECOND", 1),
    MetricKey.AVERAGE_AUTHORIZATION_LATENCY: (
        "average_authorization_latency_ms",
        "MILLISECONDS",
        0,
    ),
    MetricKey.P95_AUTHORIZATION_LATENCY: (
        "p95_authorization_latency_ms",
        "MILLISECONDS",
        0,
    ),
}


class RuntimePipeline:
    """Consumes typed events and writes the projections served by the public API."""

    def __init__(
        self,
        store: RuntimeStore,
        settings: Settings,
        notifier: PipelineNotifier | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.notifier = notifier
        self.aggregator = EventTimeAggregator(settings)
        self.detector = TechnicalErrorDetector(settings)
        self.lifecycle = IncidentLifecycleManager(settings)
        self.analyzer = DimensionalAnalyzer(settings)
        self.rca = RootCauseEngine(settings)
        self.evidence_builder = EvidenceBuilder(settings)
        self.operational_events: list[OperationalEvent] = []
        self.timeline: list[IncidentTimelineItem] = []
        self._last_transition = IncidentLifecycle.WARMING_UP
        self._processed_event_ids: dict[str, datetime] = {}

    async def initialize(self) -> None:
        await self.store.migrate()
        payload = await self.store.get_resource("pipeline_state", "current")
        if payload is not None:
            self._restore_state(payload)

    async def process_operational(self, event: OperationalEvent) -> None:
        if not self._add_operational(event):
            return
        await self._persist_state()

    def _add_operational(self, event: OperationalEvent) -> bool:
        event_key = str(event.event_id)
        if event_key in self._processed_event_ids:
            return False
        if any(existing.event_id == event.event_id for existing in self.operational_events):
            return False
        self._processed_event_ids[event_key] = event.occurred_at
        self.operational_events.append(event)
        self.operational_events.sort(key=lambda item: item.occurred_at)
        event_type = (
            "ROLLBACK"
            if event.event_type is OperationalEventType.ROLLBACK
            else "OPERATIONAL_CHANGE"
        )
        version = event.new_version or event.to_version or "configured version"
        title = "Rollback completed" if event_type == "ROLLBACK" else "Deployment completed"
        self.timeline.append(
            IncidentTimelineItem(
                timeline_item_id=f"timeline:{event.event_id}",
                occurred_at=event.occurred_at,
                event_type=event_type,
                operational_event_id=str(event.event_id),
                title=title,
                summary=f"{event.component} changed to {version} with status {event.status.value}.",
            )
        )
        return True

    async def process_batch(
        self,
        payments: list[PaymentEvent],
        operations: list[OperationalEvent],
        *,
        as_of: datetime | None = None,
    ) -> MetricSnapshot | None:
        for operation in operations:
            self._add_operational(operation)
        new_payments = [
            event for event in payments if str(event.event_id) not in self._processed_event_ids
        ]
        if not new_payments:
            if operations:
                await self._persist_state()
            return None
        return await self.process_payments(new_payments, as_of=as_of)

    async def process_payments(
        self, events: Sequence[PaymentEvent], *, as_of: datetime | None = None
    ) -> MetricSnapshot:
        for event in events:
            self._processed_event_ids[str(event.event_id)] = event.occurred_at
            self.aggregator.ingest(event)
        generated_at = (as_of or datetime.now(UTC)).astimezone(UTC)
        snapshot = self.aggregator.snapshot(generated_at)
        evaluation = self.detector.evaluate(snapshot)
        transition = self.lifecycle.apply(evaluation)
        await self._persist_overview(snapshot, transition.lifecycle)
        await self._persist_history(snapshot)
        if transition.incident is not None:
            await self._persist_incident(snapshot, evaluation, transition.incident)
        self._last_transition = transition.lifecycle
        await self._persist_state()
        await self._notify("system.overview.updated", {"generated_at": generated_at.isoformat()})
        if transition.changed:
            await self._notify(
                "incident.lifecycle.changed",
                {
                    "incident_id": transition.incident.incident_id if transition.incident else None,
                    "lifecycle": transition.lifecycle.value,
                },
            )
        return snapshot

    def _restore_state(self, payload: dict[str, Any]) -> None:
        self.aggregator.import_state(dict(payload.get("aggregator", {})))
        self.lifecycle.import_state(dict(payload.get("lifecycle", {})))
        self.operational_events = [
            OperationalEvent.model_validate(item) for item in payload.get("operational_events", [])
        ]
        self.timeline = [
            IncidentTimelineItem.model_validate(item) for item in payload.get("timeline", [])
        ]
        self._last_transition = IncidentLifecycle(
            payload.get("last_transition", IncidentLifecycle.WARMING_UP.value)
        )
        self._processed_event_ids = {
            str(item["event_id"]): datetime.fromisoformat(item["occurred_at"])
            for item in payload.get("processed_events", [])
        }

    async def _persist_state(self) -> None:
        latest = self.aggregator.latest_event_at
        retention_seconds = (
            self.settings.baseline_window_seconds
            + self.settings.current_window_seconds
            + self.settings.allowed_lateness_seconds
            + self.settings.bucket_duration_seconds
        )
        cutoff = latest - timedelta(seconds=retention_seconds) if latest else None
        if cutoff is not None:
            self._processed_event_ids = {
                event_id: occurred_at
                for event_id, occurred_at in self._processed_event_ids.items()
                if occurred_at >= cutoff
            }
        payload = {
            "state_version": 1,
            "configuration_version": self.settings.configuration_version,
            "aggregator": self.aggregator.export_state(),
            "lifecycle": self.lifecycle.export_state(),
            "operational_events": [
                item.model_dump(mode="json") for item in self.operational_events[-100:]
            ],
            "timeline": [item.model_dump(mode="json") for item in self.timeline[-100:]],
            "last_transition": self._last_transition.value,
            "processed_events": [
                {"event_id": event_id, "occurred_at": occurred_at.isoformat()}
                for event_id, occurred_at in self._processed_event_ids.items()
            ],
        }
        await self.store.put_resource("pipeline_state", "current", payload)

    async def _persist_overview(
        self, snapshot: MetricSnapshot, detector_lifecycle: IncidentLifecycle
    ) -> None:
        incident_payloads = await self.store.list_resources("incident_summary")
        summaries = [IncidentSummary.model_validate(payload) for payload in incident_payloads]
        active = [item for item in summaries if item.lifecycle != "RESOLVED"]
        current = snapshot.current
        baseline = snapshot.baseline
        metrics = OverviewMetrics(
            **{
                key.value: self._metric(
                    getattr(current, attribute),
                    unit,
                    precision,
                    getattr(baseline, attribute),
                    current.unavailable_reason,
                )
                for key, (attribute, unit, precision) in _METRIC_ATTRIBUTES.items()
            }
        )
        baseline_rate = baseline.technical_error_rate
        excess = None
        if baseline_rate is not None:
            excess = max(
                0.0,
                current.technical_error_count - current.total_attempts * baseline_rate,
            )
        overview = SystemOverviewResponse(
            generated_at=snapshot.generated_at,
            latest_sample_at=self.aggregator.latest_event_at,
            telemetry_stale_after_seconds=self.settings.telemetry_stale_after_seconds,
            telemetry_state=snapshot.telemetry_state,
            baseline=BaselineStatus(
                ready=snapshot.baseline_ready,
                progress=min(
                    1.0,
                    baseline.total_attempts / self.settings.baseline_required_samples,
                ),
                current_samples=baseline.total_attempts,
                required_samples=self.settings.baseline_required_samples,
                unavailable_reason=None if snapshot.baseline_ready else "Baseline is prewarming",
            ),
            metrics=metrics,
            punchline_metric=PunchlineMetric(
                label="Technical error rate",
                metric=metrics.technical_error_rate,
                supporting_count=self._metric(
                    excess,
                    "COUNT",
                    0,
                    None,
                    current.unavailable_reason,
                ),
            ),
            active_incident_count=len(active),
            active_incidents=active,
            detector_summary=DetectorSummary(
                global_technical_error_state=detector_lifecycle,
                latency_state=(
                    IncidentLifecycle.OPEN
                    if self.detector.evaluate_latency(snapshot).is_anomaly
                    else IncidentLifecycle.HEALTHY
                    if snapshot.baseline_ready
                    else IncidentLifecycle.WARMING_UP
                ),
            ),
        )
        await self.store.put_resource("overview", "current", overview.model_dump(mode="json"))

    async def _persist_history(self, snapshot: MetricSnapshot) -> None:
        for metric_key, (attribute, unit, _) in _METRIC_ATTRIBUTES.items():
            existing_payload = await self.store.get_resource("metric_history", metric_key.value)
            existing = (
                MetricHistoryResponse.model_validate(existing_payload)
                if existing_payload is not None
                else None
            )
            point = MetricHistoryPoint(
                at=snapshot.generated_at,
                value=getattr(snapshot.current, attribute),
                unavailable_reason=snapshot.current.unavailable_reason,
            )
            points = [item for item in (existing.points if existing else []) if item.at != point.at]
            points.append(point)
            points = sorted(points, key=lambda item: item.at)[
                -self.settings.metric_history_max_points :
            ]
            start_at = points[0].at
            end_at = points[-1].at
            if end_at <= start_at:
                end_at = start_at + timedelta(microseconds=1)
            history = MetricHistoryResponse(
                metric_key=metric_key,
                unit=unit,
                period=Period(start_at=start_at, end_at=end_at),
                resolution_seconds=self.settings.bucket_duration_seconds,
                points=points,
                events=list(self.timeline),
            )
            await self.store.put_resource(
                "metric_history", metric_key.value, history.model_dump(mode="json")
            )

    async def _persist_incident(
        self,
        snapshot: MetricSnapshot,
        evaluation: DetectionEvaluation,
        incident: Incident,
    ) -> None:
        analysis = self.analyzer.analyze(incident.incident_id, snapshot, incident.version)
        recovery_confirmed = incident.lifecycle is IncidentLifecycle.RESOLVED
        rca = self.rca.run(
            incident.incident_id,
            incident.started_at,
            analysis,
            self.operational_events,
            recovery_confirmed=recovery_confirmed,
        )
        package = self.evidence_builder.build(
            IncidentEvidenceInput(
                incident_id=incident.incident_id,
                lifecycle=incident.lifecycle,
                severity=incident.severity,
                started_at=incident.started_at,
                updated_at=incident.updated_at,
            ),
            evaluation,
            analysis,
            rca,
            optional_missing=["Downstream issuer traces are unavailable in the synthetic demo."],
        )
        evidence = self.evidence_builder.dashboard_projection(package)
        scope = analysis.best_affected_scope
        signature = analysis.dominant_error_signature
        leading = next((item for item in evidence.hypotheses if item.is_leading), None)
        current_review_payload = await self.store.get_resource("human_review", incident.incident_id)
        current_workspace_payload = await self.store.get_resource("incident", incident.incident_id)
        current_workspace = (
            IncidentWorkspaceResponse.model_validate(current_workspace_payload)
            if current_workspace_payload
            else None
        )
        review = (
            HumanReviewView.model_validate(current_review_payload)
            if current_review_payload
            else HumanReviewView(updated_at=incident.updated_at, version=1)
        )
        affected_scope = self._scope_view(scope) if scope else None
        error_signature = (
            ErrorSignatureView(
                normalized_error_code=signature.normalized_error_code,
                label=signature.label,
                current_count=self._metric(signature.current_count, "COUNT", 0),
                share_of_technical_errors=self._metric(
                    signature.share_of_technical_errors, "RATE", 4
                ),
                attempt_rate=self._metric(
                    signature.current_attempt_rate,
                    "RATE",
                    4,
                    signature.baseline_attempt_rate,
                ),
                excess_count=self._metric(signature.excess_count, "COUNT", 0),
            )
            if signature
            else None
        )
        summary = IncidentSummary(
            incident_id=incident.incident_id,
            title="Elevated technical errors detected in synthetic authorization traffic",
            lifecycle=incident.lifecycle.value,
            severity=incident.severity,
            started_at=incident.started_at,
            updated_at=incident.updated_at,
            affected_scope=affected_scope.scope if affected_scope else None,
            dominant_error_signature=(
                signature.normalized_error_code if signature is not None else None
            ),
            leading_hypothesis=(
                {
                    "hypothesis_id": leading.hypothesis_id,
                    "summary": leading.summary,
                    "evidence_tier": leading.evidence_tier,
                }
                if leading
                else None
            ),
            evidence_completeness=evidence.completeness,
            human_review_status=review.status,
        )
        lifecycle_item = IncidentTimelineItem(
            timeline_item_id=f"timeline:{incident.incident_id}:{incident.version}",
            occurred_at=incident.updated_at,
            event_type=(
                "RECOVERY"
                if incident.lifecycle
                in {IncidentLifecycle.RECOVERY_CANDIDATE, IncidentLifecycle.RESOLVED}
                else "INCIDENT_LIFECYCLE"
            ),
            lifecycle=incident.lifecycle,
            title=incident.lifecycle.value.replace("_", " ").title(),
            summary="Lifecycle updated from measured synthetic telemetry.",
        )
        timeline = sorted(
            [*self.timeline, lifecycle_item],
            key=lambda item: item.occurred_at,
        )
        excess = max(
            0.0,
            evaluation.current_errors
            - evaluation.current_attempts * (evaluation.baseline_value or 0.0),
        )
        detail = IncidentDetail(
            **summary.model_dump(),
            resolved_at=incident.updated_at if recovery_confirmed else None,
            impact_summary=(
                f"Measured {evaluation.current_errors:,} technical errors and approximately "
                f"{excess:,.0f} excess errors in the current synthetic window."
            ),
            current_period=Period(
                start_at=snapshot.current.start_at, end_at=snapshot.current.end_at
            ),
            baseline_period=Period(
                start_at=snapshot.baseline.start_at, end_at=snapshot.baseline.end_at
            ),
            incident_period=Period(
                start_at=incident.started_at,
                end_at=max(
                    incident.updated_at,
                    incident.started_at + timedelta(microseconds=1),
                ),
            ),
            closure_mode=incident.closure_mode,
            manual_closure_reason=incident.manual_closure_reason,
        )
        limitations = [
            item
            for item in evidence.items
            if item.category in {EvidenceCategory.LIMITATION, EvidenceCategory.MISSING_EVIDENCE}
        ]
        workspace = IncidentWorkspaceResponse(
            incident_id=incident.incident_id,
            evidence_package_id=evidence.evidence_package_id,
            evidence_package_version=evidence.evidence_package_version,
            generated_at=snapshot.generated_at,
            incident=detail,
            affected_scope=affected_scope,
            error_signature=error_signature,
            timeline=timeline,
            rca_summary=RcaSummaryView(
                result_version=rca.result_version,
                overall_tier=rca.overall_tier,
                leading_hypothesis=leading,
                alternatives=[item for item in evidence.hypotheses if not item.is_leading],
                insufficient_evidence_reason=rca.insufficient_evidence_reason,
            ),
            evidence_status=EvidenceStatus(
                completeness=evidence.completeness,
                limitations=limitations,
                validation_message="Evidence package validated against evidence-package.v1.",
            ),
            copilot_summary=(
                current_workspace.copilot_summary
                if current_workspace
                else CopilotThreadSummary(
                    thread_available=True,
                    initial_analysis_status="NOT_REQUESTED",
                )
            ),
            human_review=review,
        )
        await self.store.put_resource(
            "incident_summary",
            incident.incident_id,
            summary.model_dump(mode="json"),
            incident.version,
        )
        await self.store.put_resource(
            "incident", incident.incident_id, workspace.model_dump(mode="json"), incident.version
        )
        await self.store.put_resource(
            "evidence",
            incident.incident_id,
            evidence.model_dump(mode="json"),
            package.package_version,
        )
        if await self.store.get_resource("copilot_messages", incident.incident_id) is None:
            await self.store.put_resource(
                "copilot_messages",
                incident.incident_id,
                CopilotMessagePage(items=[]).model_dump(mode="json"),
            )
        await self._notify(
            "evidence.package.created",
            {
                "incident_id": incident.incident_id,
                "evidence_package_id": evidence.evidence_package_id,
                "evidence_package_version": evidence.evidence_package_version,
            },
        )

    @staticmethod
    def _scope_view(scope: CandidateFinding) -> AffectedScopeView:
        scoped = ScopedValue(
            processing_region=scope.components.get("processing_region"),
            payment_method=scope.components.get("payment_method"),
            service="authorization-api",
            service_version=scope.components.get("service_version"),
        )
        return AffectedScopeView(
            label=scope.label,
            scope=scoped,
            traffic_share=RuntimePipeline._metric(scope.traffic_share, "RATE", 4),
            technical_error_rate=RuntimePipeline._metric(
                scope.technical_error_rate,
                "RATE",
                4,
                scope.baseline_technical_error_rate,
            ),
            complement_technical_error_rate=RuntimePipeline._metric(
                scope.complement_technical_error_rate,
                "RATE",
                4,
                None,
                "Complement has no attempts",
            ),
            excess_technical_errors=RuntimePipeline._metric(
                scope.excess_technical_errors, "COUNT", 0
            ),
            caveats=["Bounded dimensional ranking uses observed single, pair and triple scopes."],
        )

    @staticmethod
    def _metric(
        value: float | int | None,
        unit: str,
        precision: int,
        baseline: float | None = None,
        unavailable_reason: str | None = None,
    ) -> MetricValue:
        comparison = None
        if value is not None and baseline is not None:
            change = float(value) - baseline
            comparison = MetricComparison(
                baseline_value=baseline,
                absolute_change=change,
                relative_change=change / baseline if baseline else None,
                direction="UP" if change > 0 else "DOWN" if change < 0 else "UNCHANGED",
                interpretation="DEGRADED" if change > 0 else "HEALTHY_RANGE",
            )
        return MetricValue.model_validate(
            {
                "value": value,
                "unit": unit,
                "display_precision": precision,
                "unavailable_reason": unavailable_reason
                or ("No telemetry yet" if value is None else None),
                "comparison": comparison,
            }
        )

    async def _notify(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.notifier is None:
            return
        result = self.notifier(event_type, payload)
        if hasattr(result, "__await__"):
            await result
