"""Deterministic validated projections used to seed the local synthetic demo."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.contracts.api import (
    AffectedScopeView,
    BaselineStatus,
    CopilotClaim,
    CopilotInteractionView,
    CopilotMessagePage,
    CopilotRecommendation,
    CopilotThreadSummary,
    CursorPage,
    DetectorSummary,
    DeterministicFallback,
    ErrorSignatureView,
    EvidenceCitationRef,
    EvidenceItemView,
    EvidenceProjectionResponse,
    EvidenceStatus,
    HumanReviewView,
    HypothesisRelationView,
    HypothesisView,
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
    RetryState,
    ScopedValue,
    SimulationStatus,
    SystemOverviewResponse,
    ValidatedCopilotMessage,
)
from backend.contracts.enums import MetricKey


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, second, tzinfo=UTC)


def _comparison(
    baseline: float, value: float, interpretation: str = "DEGRADED"
) -> MetricComparison:
    change = value - baseline
    return MetricComparison(
        baseline_value=baseline,
        absolute_change=change,
        relative_change=change / baseline if baseline else None,
        direction="UP" if change > 0 else "DOWN" if change < 0 else "UNCHANGED",
        interpretation=interpretation,
    )


def _metric(
    value: float,
    unit: str,
    baseline: float | None = None,
    interpretation: str = "DEGRADED",
) -> MetricValue:
    return MetricValue(
        value=value,
        unit=unit,
        display_precision=4 if unit == "RATE" else 0,
        comparison=(
            _comparison(baseline, value, interpretation) if baseline is not None else None
        ),
    )


@dataclass(frozen=True)
class DemoProjection:
    overview: SystemOverviewResponse
    history: MetricHistoryResponse
    incidents: CursorPage[IncidentSummary]
    workspace: IncidentWorkspaceResponse
    evidence: EvidenceProjectionResponse
    messages: CopilotMessagePage
    interaction: CopilotInteractionView
    simulation: SimulationStatus


def build_demo_projection() -> DemoProjection:
    now = _at(11, 53)
    current_period = Period(start_at=_at(11, 48), end_at=now)
    baseline_period = Period(start_at=_at(11, 18), end_at=_at(11, 48))
    scope = ScopedValue(
        processing_region="SG",
        payment_method="MOBILE_WALLET",
        service="authorization-api",
        service_version="v2.4.1",
    )
    leading_summary = {
        "hypothesis_id": "HYP-DEPLOY-241",
        "summary": "authorization-api v2.4.1 deployment is temporally and dimensionally aligned",
        "evidence_tier": "STRONG_EVIDENCE",
    }
    incident = IncidentSummary(
        incident_id="INC-2026-0827-017",
        title="Elevated technical errors after authorization deployment",
        lifecycle="OPEN",
        severity="HIGH",
        started_at=_at(11, 44),
        updated_at=now,
        affected_scope=scope,
        dominant_error_signature="UPSTREAM_TIMEOUT",
        leading_hypothesis=leading_summary,
        evidence_completeness="COMPLETE",
        human_review_status="UNREVIEWED",
    )
    older_incidents = [
        IncidentSummary.model_validate(
            {
                **incident.model_dump(),
                "incident_id": "INC-2026-0826-004",
                "title": "Issuer latency elevated in AU card-present traffic",
                "lifecycle": "RECOVERY_CANDIDATE",
                "severity": "MEDIUM",
                "started_at": datetime(2026, 8, 26, 8, 15, tzinfo=UTC),
                "updated_at": datetime(2026, 8, 26, 8, 42, tzinfo=UTC),
                "affected_scope": ScopedValue(
                    processing_region="AU",
                    payment_method="CARD",
                    service="authorization-api",
                    service_version="v2.4.0",
                ),
                "dominant_error_signature": "ISSUER_TIMEOUT",
                "evidence_completeness": "PARTIAL",
                "human_review_status": "INCONCLUSIVE",
            }
        ),
        IncidentSummary.model_validate(
            {
                **incident.model_dump(),
                "incident_id": "INC-2026-0825-011",
                "title": "Gateway configuration caused transient routing failures",
                "lifecycle": "RESOLVED",
                "severity": "LOW",
                "started_at": datetime(2026, 8, 25, 3, 10, tzinfo=UTC),
                "updated_at": datetime(2026, 8, 25, 3, 31, tzinfo=UTC),
                "affected_scope": ScopedValue(
                    processing_region="US",
                    payment_method="CARD",
                    service="payment-gateway",
                    service_version="v7.8.2",
                ),
                "dominant_error_signature": "ROUTE_UNAVAILABLE",
                "evidence_completeness": "COMPLETE",
                "human_review_status": "ACKNOWLEDGED",
            }
        ),
    ]
    overview = SystemOverviewResponse(
        generated_at=now,
        latest_sample_at=now,
        telemetry_stale_after_seconds=30,
        telemetry_state="HEALTHY",
        baseline=BaselineStatus(
            ready=True,
            progress=1,
            current_samples=17940,
            required_samples=6000,
        ),
        metrics=OverviewMetrics(
            technical_error_rate=_metric(0.0837, "RATE", 0.0061),
            approval_rate=_metric(0.7912, "RATE", 0.8814),
            business_decline_rate=_metric(0.1251, "RATE", 0.1125, "HEALTHY_RANGE"),
            throughput=_metric(988, "ATTEMPTS_PER_SECOND", 1004, "HEALTHY_RANGE"),
            average_authorization_latency=_metric(714, "MILLISECONDS", 238),
            p95_authorization_latency=_metric(1842, "MILLISECONDS", 612),
        ),
        punchline_metric=PunchlineMetric(
            label="Technical error rate",
            metric=_metric(0.0837, "RATE", 0.0061),
            supporting_count=_metric(3831, "COUNT", 279),
        ),
        active_incident_count=1,
        active_incidents=[incident],
        detector_summary=DetectorSummary(
            global_technical_error_state="OPEN",
            latency_state="OPEN",
        ),
    )
    history_values = [
        0.0058,
        0.0062,
        0.0059,
        0.0064,
        0.0061,
        0.0060,
        0.0063,
        0.0062,
        0.0065,
        0.0071,
        0.0138,
        0.0287,
        0.0512,
        0.0764,
        0.0861,
        0.0892,
        0.0851,
        0.0837,
    ]
    history_start = _at(11, 36)
    timeline = [
        IncidentTimelineItem(
            timeline_item_id="TL-001",
            occurred_at=_at(11, 43),
            event_type="OPERATIONAL_CHANGE",
            operational_event_id="DEPLOY-241",
            title="Deployment completed",
            summary="authorization-api v2.4.1 reached 100% of SG traffic",
        ),
        IncidentTimelineItem(
            timeline_item_id="TL-002",
            occurred_at=_at(11, 46),
            event_type="INCIDENT_LIFECYCLE",
            lifecycle="OPEN",
            title="Incident opened",
            summary="Technical error persistence threshold crossed",
        ),
    ]
    history = MetricHistoryResponse(
        metric_key=MetricKey.TECHNICAL_ERROR_RATE,
        unit="RATE",
        period=Period(start_at=history_start, end_at=now),
        resolution_seconds=60,
        points=[
            MetricHistoryPoint(at=history_start + timedelta(minutes=index), value=value)
            for index, value in enumerate(history_values)
        ],
        events=timeline,
    )
    evidence_items = [
        EvidenceItemView(
            evidence_id="EV-SCOPE-001",
            stable_logical_key="affected-scope-sg-wallet-v241",
            category="DERIVED_FINDING",
            statement="SG mobile-wallet traffic on v2.4.1 carries 91.8% of excess technical errors.",
            structured_value={"traffic_share": 0.184, "excess_error_share": 0.918},
            unit="RATE",
            period=current_period,
            scope=scope,
            temporal_scope="INCIDENT_SNAPSHOT",
            provenance_label="Deterministic scope comparison",
            source_module="dimensional-analysis",
            source_version="1.0.0",
        ),
        EvidenceItemView(
            evidence_id="EV-TIME-001",
            stable_logical_key="deploy-precedes-error-rise",
            category="OBSERVED_FACT",
            statement="Deployment completed 63 seconds before the sustained technical-error rise.",
            structured_value={"elapsed_seconds": 63},
            unit="SECONDS",
            period=current_period,
            scope=scope,
            temporal_scope="INCIDENT_SNAPSHOT",
            provenance_label="Operational-event correlation",
            source_module="operational-events",
            source_version="1.0.0",
        ),
        EvidenceItemView(
            evidence_id="EV-ERROR-001",
            stable_logical_key="upstream-timeout-dominant",
            category="DERIVED_FINDING",
            statement="UPSTREAM_TIMEOUT represents 78.4% of current technical errors.",
            structured_value={"share": 0.784, "count": 3492},
            unit="RATE",
            period=current_period,
            scope=scope,
            temporal_scope="INCIDENT_SNAPSHOT",
            provenance_label="Normalized error signature",
            source_module="error-signatures",
            source_version="1.0.0",
        ),
        EvidenceItemView(
            evidence_id="EV-LIMIT-001",
            stable_logical_key="downstream-trace-gap",
            category="LIMITATION",
            statement="Downstream issuer traces are not available in this synthetic environment.",
            temporal_scope="INCIDENT_SNAPSHOT",
            provenance_label="Evidence availability check",
            source_module="evidence-builder",
            source_version="1.0.0",
        ),
    ]
    leading = HypothesisView(
        **leading_summary,
        rank=1,
        candidate_type="DEPLOYMENT",
        is_leading=True,
        operational_event_id="DEPLOY-241",
        relations=[
            HypothesisRelationView(relation="SUPPORTING", evidence_id=evidence_id)
            for evidence_id in ("EV-SCOPE-001", "EV-TIME-001", "EV-ERROR-001")
        ],
    )
    alternative = HypothesisView(
        hypothesis_id="HYP-CONFIG-552",
        rank=2,
        summary="Gateway timeout threshold change preceded the incident but affects all regions",
        candidate_type="CONFIG_CHANGE",
        evidence_tier="WEAK_EVIDENCE",
        is_leading=False,
        operational_event_id="CONFIG-552",
        relations=[
            HypothesisRelationView(relation="SUPPORTING", evidence_id="EV-TIME-001"),
            HypothesisRelationView(relation="CONTRADICTORY", evidence_id="EV-SCOPE-001"),
        ],
    )
    review = HumanReviewView(updated_at=now, version=1)
    workspace = IncidentWorkspaceResponse(
        incident_id=incident.incident_id,
        evidence_package_id="EP-INC-017",
        evidence_package_version=3,
        generated_at=now,
        incident=IncidentDetail(
            **incident.model_dump(),
            impact_summary="An estimated 3,831 excess technical errors affected SG mobile-wallet authorizations; business declines remained within baseline range.",
            current_period=current_period,
            baseline_period=baseline_period,
            incident_period=Period(start_at=_at(11, 44), end_at=now),
        ),
        affected_scope=AffectedScopeView(
            label="SG · Mobile wallet · authorization-api v2.4.1",
            scope=scope,
            traffic_share=_metric(0.184, "RATE"),
            technical_error_rate=_metric(0.312, "RATE", 0.0057),
            complement_technical_error_rate=_metric(0.0112, "RATE", 0.0062),
            excess_technical_errors=_metric(3517, "COUNT"),
            caveats=["Scope ranking compares bounded dimensions and up to three-way combinations."],
        ),
        error_signature=ErrorSignatureView(
            normalized_error_code="UPSTREAM_TIMEOUT",
            label="Upstream timeout",
            current_count=_metric(3492, "COUNT"),
            share_of_technical_errors=_metric(0.784, "RATE"),
            attempt_rate=_metric(0.0656, "RATE", 0.0009),
            excess_count=_metric(3246, "COUNT"),
        ),
        timeline=timeline,
        rca_summary=RcaSummaryView(
            result_version=3,
            overall_tier="STRONG_EVIDENCE",
            leading_hypothesis=leading,
            alternatives=[alternative],
        ),
        evidence_status=EvidenceStatus(
            completeness="COMPLETE",
            limitations=[evidence_items[-1]],
            validation_message="Package validated against evidence schema v1.",
        ),
        copilot_summary=CopilotThreadSummary(
            thread_available=True,
            initial_analysis_status="VALIDATED",
            latest_interaction_id="COP-INT-017",
            latest_validated_message_id="COP-MSG-017",
        ),
        human_review=review,
    )
    citations = [
        EvidenceCitationRef(
            evidence_id=item.evidence_id,
            evidence_package_id="EP-INC-017",
            evidence_package_version=3,
        )
        for item in evidence_items[:3]
    ]
    evidence = EvidenceProjectionResponse(
        incident_id=incident.incident_id,
        evidence_package_id="EP-INC-017",
        evidence_package_version=3,
        completeness="COMPLETE",
        generated_at=now,
        items=evidence_items,
        hypotheses=[leading, alternative],
        package_limitations=["Downstream issuer traces are unavailable in the synthetic demo."],
        citation_allowlist=citations,
    )
    message = ValidatedCopilotMessage(
        message_id="COP-MSG-017",
        interaction_id="COP-INT-017",
        incident_id=incident.incident_id,
        evidence_package_id="EP-INC-017",
        evidence_package_version=3,
        mode="INITIAL_ANALYSIS",
        status="VALIDATED",
        created_at=_at(11, 53, 30),
        assessment="SUPPORTED",
        summary="The v2.4.1 deployment is the strongest available explanation, with temporal, scope, and error-signature agreement.",
        claims=[
            CopilotClaim(
                claim_id="CLM-001",
                claim_type="DETERMINISTIC_FINDING",
                text="The affected scope carries 91.8% of excess technical errors.",
                citations=[citations[0]],
            )
        ],
        recommendations=[
            CopilotRecommendation(
                recommendation_id="REC-001",
                action_type="VERIFY",
                title="Compare v2.4.0 and v2.4.1 timeout paths",
                rationale="The error signature and version scope align tightly.",
                expected_signal="Timeouts fall back toward baseline on the previous version.",
                risk_level="LOW",
                citations=[citations[2]],
            )
        ],
        limitations=["Causality is not proven; downstream issuer traces are unavailable."],
        suggested_questions=["What evidence weakens this hypothesis?"],
    )
    interaction = CopilotInteractionView(
        interaction_id="COP-INT-017",
        status="VALIDATED",
        progress_updated_at=_at(11, 54, 2),
        validated_message_id=message.message_id,
        deterministic_fallback=None,
        retry=RetryState(eligible=False),
    )
    simulation = SimulationStatus(
        state="STOPPED",
        baseline_ready=False,
        active_scenario_id=None,
        started_at=None,
        available_actions=["START", "RESET"],
        message="Synthetic simulator is ready to start.",
    )
    return DemoProjection(
        overview=overview,
        history=history,
        incidents=CursorPage[IncidentSummary](items=[incident, *older_incidents]),
        workspace=workspace,
        evidence=evidence,
        messages=CopilotMessagePage(items=[message]),
        interaction=interaction,
        simulation=simulation,
    )
