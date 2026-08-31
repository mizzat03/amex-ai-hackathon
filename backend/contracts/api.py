"""Frozen frontend-facing models from frontend-backend-contract.md v1.1."""

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import Field, model_validator

from backend.contracts.common import ContractModel
from backend.contracts.enums import (
    ClaimType,
    CopilotAssessment,
    EvidenceCategory,
    EvidenceCompleteness,
    EvidenceTier,
    HumanReviewStatus,
    HypothesisRelation,
    IncidentLifecycle,
    IncidentSeverity,
    MetricKey,
    SimulationAction,
    SimulationState,
    TelemetryState,
    TemporalScope,
)

T = TypeVar("T")


class Period(ContractModel):
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "Period":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class ScopedValue(ContractModel):
    processing_region: str | None = None
    payment_method: str | None = None
    service: str | None = None
    service_version: str | None = None


class MetricComparison(ContractModel):
    baseline_value: float | None
    absolute_change: float | None
    relative_change: float | None
    direction: Literal["UP", "DOWN", "UNCHANGED", "UNKNOWN"]
    interpretation: Literal["HEALTHY_RANGE", "DEGRADED", "IMPROVING", "UNKNOWN"]


class MetricValue(ContractModel):
    value: float | None
    unit: Literal["COUNT", "RATE", "MILLISECONDS", "ATTEMPTS_PER_SECOND"]
    display_precision: int | None = Field(default=None, ge=0, le=6)
    unavailable_reason: str | None = Field(default=None, max_length=240)
    comparison: MetricComparison | None = None

    @model_validator(mode="after")
    def preserve_unavailable_state(self) -> "MetricValue":
        if self.value is None and not self.unavailable_reason:
            raise ValueError("null metric values require unavailable_reason")
        return self


class CursorPage(ContractModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class IncidentTimelineItem(ContractModel):
    timeline_item_id: str
    occurred_at: datetime
    event_type: Literal[
        "OPERATIONAL_CHANGE", "INCIDENT_LIFECYCLE", "ROLLBACK", "RECOVERY"
    ]
    title: str
    summary: str
    operational_event_id: str | None = None
    lifecycle: IncidentLifecycle | None = None


class MetricHistoryQuery(ContractModel):
    metric_key: MetricKey
    start_at: datetime
    end_at: datetime
    incident_id: str | None = None


class MetricHistoryPoint(ContractModel):
    at: datetime
    value: float | None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def preserve_unavailable_state(self) -> "MetricHistoryPoint":
        if self.value is None and not self.unavailable_reason:
            raise ValueError("null history points require unavailable_reason")
        return self


class MetricHistoryResponse(ContractModel):
    metric_key: MetricKey
    unit: Literal["COUNT", "RATE", "MILLISECONDS", "ATTEMPTS_PER_SECOND"]
    period: Period
    resolution_seconds: int = Field(ge=1)
    points: list[MetricHistoryPoint]
    events: list[IncidentTimelineItem]


class EvidenceCitationRef(ContractModel):
    citation_type: Literal["EVIDENCE"] = "EVIDENCE"
    evidence_id: str
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)


class RunbookCitationRef(ContractModel):
    citation_type: Literal["RUNBOOK"] = "RUNBOOK"
    runbook_id: str
    runbook_version: str
    section_id: str


CitationRef = EvidenceCitationRef | RunbookCitationRef


class ResourceVersion(ContractModel):
    updated_at: datetime
    version: int = Field(ge=1)


class EvidenceVersionRef(ContractModel):
    incident_id: str
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)


class LeadingHypothesisSummary(ContractModel):
    hypothesis_id: str
    summary: str
    evidence_tier: EvidenceTier


class IncidentSummary(ContractModel):
    incident_id: str
    title: str
    lifecycle: Literal["OPEN", "RECOVERY_CANDIDATE", "RESOLVED"]
    severity: IncidentSeverity
    started_at: datetime
    updated_at: datetime
    affected_scope: ScopedValue | None = None
    dominant_error_signature: str | None = None
    leading_hypothesis: LeadingHypothesisSummary | None = None
    evidence_completeness: EvidenceCompleteness | None = None
    human_review_status: HumanReviewStatus


class BaselineStatus(ContractModel):
    ready: bool
    progress: float | None = Field(default=None, ge=0, le=1)
    current_samples: int = Field(ge=0)
    required_samples: int = Field(ge=1)
    unavailable_reason: str | None = None


class OverviewMetrics(ContractModel):
    approval_rate: MetricValue
    business_decline_rate: MetricValue
    technical_error_rate: MetricValue
    throughput: MetricValue
    average_authorization_latency: MetricValue
    p95_authorization_latency: MetricValue


class PunchlineMetric(ContractModel):
    metric_key: Literal["technical_error_rate"] = "technical_error_rate"
    label: str
    metric: MetricValue
    supporting_count: MetricValue | None = None


class DetectorSummary(ContractModel):
    global_technical_error_state: IncidentLifecycle
    latency_state: IncidentLifecycle


class SystemOverviewResponse(ContractModel):
    generated_at: datetime
    latest_sample_at: datetime | None = None
    telemetry_stale_after_seconds: int = Field(ge=1)
    telemetry_state: TelemetryState
    baseline: BaselineStatus
    metrics: OverviewMetrics
    punchline_metric: PunchlineMetric
    active_incident_count: int = Field(ge=0)
    active_incidents: list[IncidentSummary]
    detector_summary: DetectorSummary


class AffectedScopeView(ContractModel):
    label: str
    scope: ScopedValue
    traffic_share: MetricValue
    technical_error_rate: MetricValue
    complement_technical_error_rate: MetricValue
    excess_technical_errors: MetricValue
    caveats: list[str] = Field(default_factory=list)


class ErrorSignatureView(ContractModel):
    normalized_error_code: str
    label: str
    current_count: MetricValue
    share_of_technical_errors: MetricValue
    attempt_rate: MetricValue
    excess_count: MetricValue


class HypothesisRelationView(ContractModel):
    relation: HypothesisRelation
    evidence_id: str


class HypothesisView(ContractModel):
    hypothesis_id: str
    rank: int = Field(ge=1)
    summary: str
    candidate_type: Literal["DEPLOYMENT", "CONFIG_CHANGE", "ROLLBACK"]
    evidence_tier: EvidenceTier
    is_leading: bool
    operational_event_id: str
    relations: list[HypothesisRelationView]


class RcaSummaryView(ContractModel):
    result_version: int = Field(ge=1)
    overall_tier: EvidenceTier
    leading_hypothesis: HypothesisView | None = None
    alternatives: list[HypothesisView] = Field(default_factory=list)
    insufficient_evidence_reason: str | None = None


class EvidenceItemView(ContractModel):
    evidence_id: str
    stable_logical_key: str
    category: EvidenceCategory
    statement: str
    structured_value: dict[str, Any] | None = None
    unit: str | None = None
    period: Period | None = None
    scope: ScopedValue | None = None
    temporal_scope: TemporalScope
    provenance_label: str
    source_module: str
    source_version: str


class CopilotThreadSummary(ContractModel):
    thread_available: bool
    initial_analysis_status: Literal[
        "NOT_REQUESTED", "QUEUED", "IN_PROGRESS", "VALIDATED", "FALLBACK", "FAILED"
    ]
    latest_interaction_id: str | None = None
    latest_validated_message_id: str | None = None


class HumanReviewView(ResourceVersion):
    hypothesis_id: str | None = None
    status: HumanReviewStatus = HumanReviewStatus.UNREVIEWED
    note: str | None = None
    reviewed_by: Literal["demo-operator"] | None = None


class IncidentDetail(IncidentSummary):
    resolved_at: datetime | None = None
    impact_summary: str
    current_period: Period
    baseline_period: Period
    incident_period: Period
    closure_mode: Literal["AUTOMATIC_RECOVERY", "MANUAL"] | None = None
    manual_closure_reason: str | None = None


class EvidenceStatus(ContractModel):
    completeness: EvidenceCompleteness
    limitations: list[EvidenceItemView]
    validation_message: str | None = None


class IncidentWorkspaceResponse(EvidenceVersionRef):
    generated_at: datetime
    incident: IncidentDetail
    affected_scope: AffectedScopeView | None
    error_signature: ErrorSignatureView | None
    timeline: list[IncidentTimelineItem]
    rca_summary: RcaSummaryView
    evidence_status: EvidenceStatus
    copilot_summary: CopilotThreadSummary
    human_review: HumanReviewView


class IncidentListQuery(ContractModel):
    started_at_or_after: datetime | None = None
    started_before: datetime | None = None
    severity: list[IncidentSeverity] | None = None
    processing_region: list[str] | None = None
    payment_method: list[str] | None = None
    sort_by: Literal["started_at", "severity", "lifecycle"] | None = None
    sort_direction: Literal["asc", "desc"] | None = None
    cursor: str | None = None


class EvidenceProjectionResponse(EvidenceVersionRef):
    completeness: EvidenceCompleteness
    generated_at: datetime
    items: list[EvidenceItemView]
    hypotheses: list[HypothesisView]
    package_limitations: list[str]
    citation_allowlist: list[CitationRef]


class EvidenceDetailResponse(EvidenceVersionRef):
    item: EvidenceItemView
    hypothesis_relation: HypothesisRelation | None = None
    calculation_method: str | None = None
    calculation_lineage: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)


class CopilotCitationTechnicalDetails(ContractModel):
    evidence_id: str | None = None
    source_module: str | None = None
    source_version: str | None = None
    calculation_method: str | None = None
    calculation_lineage: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)


class CopilotEvidenceCitation(ContractModel):
    citation_type: Literal["EVIDENCE"] = "EVIDENCE"
    citation_number: int = Field(ge=1)
    statement: str = Field(min_length=1, max_length=1600)
    structured_value: dict[str, Any] | None = None
    unit: str | None = None
    scope: ScopedValue | None = None
    period: Period | None = None
    temporal_scope: TemporalScope
    provenance_label: str = Field(min_length=1, max_length=400)
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    technical_details: CopilotCitationTechnicalDetails


class CopilotRunbookCitation(ContractModel):
    citation_type: Literal["RUNBOOK"] = "RUNBOOK"
    citation_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=400)
    approved_guidance_excerpt: str = Field(min_length=1, max_length=1600)
    runbook_id: str
    runbook_version: str
    section_id: str
    guidance_not_incident_proof: Literal[True] = True


CopilotHydratedCitation = Annotated[
    CopilotEvidenceCitation | CopilotRunbookCitation,
    Field(discriminator="citation_type"),
]


class CopilotEvidencePoint(ContractModel):
    text: str = Field(min_length=1, max_length=1600)
    citation_numbers: list[int] = Field(default_factory=list, max_length=8)


class CopilotRecommendedCheck(ContractModel):
    title: str = Field(min_length=1, max_length=400)
    rationale: str = Field(min_length=1, max_length=1200)
    expected_signal: str = Field(min_length=1, max_length=1200)
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    requires_human_approval: Literal[True] = True
    citation_numbers: list[int] = Field(default_factory=list, max_length=8)


class UserQuestionContent(ContractModel):
    type: Literal["USER_QUESTION"] = "USER_QUESTION"
    question: str = Field(min_length=1, max_length=2000)
    referenced_message_ids: list[str] = Field(default_factory=list, max_length=8)


class CopilotAnswerContent(ContractModel):
    type: Literal["COPILOT_ANSWER"] = "COPILOT_ANSWER"
    schema_version: Literal["copilot-answer.v2"] = "copilot-answer.v2"
    answer_kind: Literal["initial_report", "follow_up"]
    headline: str = Field(min_length=1, max_length=400)
    direct_answer: str = Field(min_length=1, max_length=2400)
    confidence: Literal["LOW", "MODERATE", "HIGH"]
    supporting_points: list[CopilotEvidencePoint] = Field(default_factory=list, max_length=12)
    contradictory_points: list[CopilotEvidencePoint] = Field(default_factory=list, max_length=12)
    unknown_points: list[CopilotEvidencePoint] = Field(default_factory=list, max_length=12)
    recommended_checks: list[CopilotRecommendedCheck] = Field(default_factory=list, max_length=8)
    citations: list[CopilotHydratedCitation] = Field(default_factory=list, max_length=24)
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)
    validation_status: Literal["VALIDATED"] = "VALIDATED"

    @model_validator(mode="after")
    def validate_citation_numbers(self) -> "CopilotAnswerContent":
        numbers = [citation.citation_number for citation in self.citations]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("citations must be numbered consecutively from one")
        allowed = set(numbers)
        referenced = {
            number
            for point in (
                *self.supporting_points,
                *self.contradictory_points,
                *self.unknown_points,
            )
            for number in point.citation_numbers
        }
        referenced.update(
            number
            for check in self.recommended_checks
            for number in check.citation_numbers
        )
        if not referenced <= allowed:
            raise ValueError("answer content references an unknown citation number")
        return self


class DeterministicFallbackContent(ContractModel):
    type: Literal["DETERMINISTIC_FALLBACK"] = "DETERMINISTIC_FALLBACK"
    label: Literal["Deterministic fallback"] = "Deterministic fallback"
    summary: str = Field(min_length=1, max_length=1200)
    reason_code: Literal[
        "provider_disabled",
        "provider_timeout",
        "provider_http_failure",
        "provider_incomplete",
        "schema_validation_failed",
        "citation_validation_failed",
        "policy_validation_failed",
        "circuit_open",
        "evidence_unavailable",
        "unexpected_internal_failure",
    ]
    retry_eligible: bool


class EvidenceVersionNoticeContent(ContractModel):
    type: Literal["EVIDENCE_VERSION_NOTICE"] = "EVIDENCE_VERSION_NOTICE"
    previous_evidence_package_id: str
    previous_evidence_package_version: int = Field(ge=1)
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=800)


class LifecycleNoticeContent(ContractModel):
    type: Literal["LIFECYCLE_NOTICE"] = "LIFECYCLE_NOTICE"
    lifecycle: Literal["OPEN", "RECOVERY_CANDIDATE", "RESOLVED"]
    summary: str = Field(min_length=1, max_length=800)


CopilotMessageContent = Annotated[
    UserQuestionContent
    | CopilotAnswerContent
    | DeterministicFallbackContent
    | EvidenceVersionNoticeContent
    | LifecycleNoticeContent,
    Field(discriminator="type"),
]


class CopilotMessage(ContractModel):
    message_id: str
    thread_id: str
    incident_id: str
    sequence: int = Field(ge=1)
    role: Literal["USER", "ASSISTANT", "SYSTEM"]
    content_type: Literal[
        "USER_QUESTION",
        "COPILOT_ANSWER",
        "DETERMINISTIC_FALLBACK",
        "EVIDENCE_VERSION_NOTICE",
        "LIFECYCLE_NOTICE",
    ]
    content: CopilotMessageContent
    interaction_id: str | None = None
    client_request_id: str | None = None
    response_to_message_id: str | None = None
    evidence_package_id: str | None = None
    evidence_package_version: int | None = Field(default=None, ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_role_and_content(self) -> "CopilotMessage":
        if self.content.type != self.content_type:
            raise ValueError("content_type must match the typed message content")
        expected_role = {
            "USER_QUESTION": "USER",
            "COPILOT_ANSWER": "ASSISTANT",
            "DETERMINISTIC_FALLBACK": "ASSISTANT",
            "EVIDENCE_VERSION_NOTICE": "SYSTEM",
            "LIFECYCLE_NOTICE": "SYSTEM",
        }[self.content_type]
        if self.role != expected_role:
            raise ValueError("message role does not match its typed content")
        if self.role == "ASSISTANT" and (
            self.interaction_id is None
            or self.evidence_package_id is None
            or self.evidence_package_version is None
        ):
            raise ValueError("assistant messages require interaction and immutable evidence identity")
        return self


class CanonicalCopilotMessagePage(CursorPage[CopilotMessage]):
    pass


class CopilotThread(ContractModel):
    thread_id: str
    incident_id: str
    created_at: datetime
    updated_at: datetime
    latest_evidence_package_id: str | None = None
    latest_evidence_package_version: int | None = Field(default=None, ge=1)


class CopilotThreadResponse(ContractModel):
    thread: CopilotThread
    messages: CanonicalCopilotMessagePage


class SubmitCopilotMessageRequest(ContractModel):
    question: str = Field(min_length=1, max_length=2000)
    client_request_id: str = Field(min_length=1, max_length=128)
    referenced_message_ids: list[str] = Field(default_factory=list, max_length=8)


class SubmitCopilotMessageResponse(ContractModel):
    interaction_id: str
    thread_id: str
    user_message_id: str
    status: Literal["QUEUED"] = "QUEUED"
    accepted_at: datetime
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)


class SubmitCopilotQueryRequest(ContractModel):
    question: str = Field(min_length=1, max_length=2000)
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    client_request_id: str = Field(min_length=1, max_length=128)


class SubmitCopilotQueryResponse(ContractModel):
    interaction_id: str
    status: Literal["QUEUED"] = "QUEUED"
    accepted_at: datetime
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)


class DeterministicFallback(ContractModel):
    available: bool
    reason_code: Literal[
        "provider_disabled",
        "provider_timeout",
        "provider_http_failure",
        "provider_incomplete",
        "schema_validation_failed",
        "citation_validation_failed",
        "policy_validation_failed",
        "circuit_open",
        "evidence_unavailable",
        "unexpected_internal_failure",
    ]
    summary: str


class RetryState(ContractModel):
    eligible: bool
    unavailable_reason: str | None = None
    retry_after: datetime | None = None


class CopilotInteractionView(ContractModel):
    interaction_id: str
    incident_id: str | None = None
    thread_id: str | None = None
    status: Literal["QUEUED", "IN_PROGRESS", "VALIDATED", "FALLBACK", "FAILED"]
    progress_stage: Literal[
        "QUEUED",
        "ANALYSING_EVIDENCE",
        "COMPARING_HYPOTHESES",
        "CHECKING_RUNBOOKS",
        "VALIDATING_CITATIONS",
        "PREPARING_RESPONSE",
    ] | None = None
    progress_updated_at: datetime | None = None
    validated_message_id: str | None = None
    deterministic_fallback: DeterministicFallback | None = None
    retry: RetryState


class CopilotClaim(ContractModel):
    claim_id: str
    claim_type: ClaimType
    text: str
    citations: list[CitationRef]


class CopilotRecommendation(ContractModel):
    recommendation_id: str
    action_type: Literal["VERIFY", "CONTAIN", "REMEDIATE", "MONITOR"]
    title: str
    rationale: str
    expected_signal: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    requires_human_approval: Literal[True] = True
    citations: list[CitationRef]


class ValidatedCopilotMessage(EvidenceVersionRef):
    message_id: str
    interaction_id: str
    role: Literal["ASSISTANT"] = "ASSISTANT"
    mode: Literal["INITIAL_ANALYSIS", "FOLLOW_UP"]
    status: Literal["VALIDATED", "DETERMINISTIC_FALLBACK"]
    created_at: datetime
    summary: str | None = None
    claims: list[CopilotClaim]
    assessment: CopilotAssessment | None = None
    recommendations: list[CopilotRecommendation]
    limitations: list[str]
    suggested_questions: list[str]


class CopilotMessagePage(CursorPage[ValidatedCopilotMessage]):
    pass


class HumanReviewRequest(ContractModel):
    hypothesis_id: str
    status: Literal["ACKNOWLEDGED", "REJECTED", "INCONCLUSIVE"]
    note: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_required_note(self) -> "HumanReviewRequest":
        if self.status in {"REJECTED", "INCONCLUSIVE"} and not (self.note or "").strip():
            raise ValueError("a non-empty note is required for rejected or inconclusive reviews")
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip() or None)
        return self


class CopilotFeedbackRequest(ContractModel):
    rating: Literal["HELPFUL", "PARTIALLY_HELPFUL", "NOT_HELPFUL"]
    problem_types: list[
        Literal[
            "INCORRECT_CLAIM",
            "WEAK_EVIDENCE",
            "MISSED_ALTERNATIVE",
            "POOR_RECOMMENDATION",
            "UNNECESSARY_TOOL_CALL",
            "UNCLEAR_EXPLANATION",
            "UNSAFE_SUGGESTION",
        ]
    ] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=2000)


class SimulationStatus(ContractModel):
    state: SimulationState
    baseline_ready: bool
    active_scenario_id: str | None = None
    started_at: datetime | None = None
    available_actions: list[SimulationAction]
    message: str | None = None


class IdempotentCommandRequest(ContractModel):
    client_request_id: str = Field(min_length=1, max_length=128)


class InjectScenarioRequest(IdempotentCommandRequest):
    pass


class ResetSimulationRequest(IdempotentCommandRequest):
    confirmation: Literal["RESET_SYNTHETIC_DEMO"]


class HealthResponse(ContractModel):
    status: Literal["ok", "degraded"]
    generated_at: datetime
    backend: Literal["available"] = "available"
    datastore: Literal["available", "unavailable", "not_checked"]
    stream: Literal["available", "unavailable", "not_checked"]


class ErrorDetail(ContractModel):
    code: str
    message: str
    retryable: bool
    request_id: str
    details: dict[str, Any] | None = None


class ApiError(ContractModel):
    error: ErrorDetail


class WsEnvelope(ContractModel, Generic[T]):
    event_id: str
    event_type: Literal[
        "system.overview.updated",
        "baseline.readiness.updated",
        "incident.lifecycle.changed",
        "incident.updated",
        "evidence.package.created",
        "copilot.progress.updated",
        "copilot.message.validated",
        "copilot.fallback.ready",
        "human_review.updated",
        "simulation.status.changed",
    ]
    occurred_at: datetime
    sequence: int = Field(ge=1)
    payload: T
