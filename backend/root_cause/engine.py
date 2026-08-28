"""Rule-based RCA with qualitative evidence tiers and explicit contradictions."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from backend.config.settings import Settings
from backend.contracts.enums import EvidenceTier, OperationalEventType, OperationalStatus
from backend.contracts.events import OperationalEvent
from backend.dimensional_analysis.analyzer import DimensionalAnalysisResult


class ServiceRelevance(StrEnum):
    EXACT_SERVICE = "EXACT_SERVICE"
    KNOWN_DEPENDENCY = "KNOWN_DEPENDENCY"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


class VersionAlignment(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScopeAlignment(StrEnum):
    EXACT = "EXACT"
    CONTAINS_AFFECTED_SCOPE = "CONTAINS_AFFECTED_SCOPE"
    PARTIAL = "PARTIAL"
    DISJOINT = "DISJOINT"
    UNKNOWN = "UNKNOWN"


class ErrorRelevance(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RcaEvidence:
    code: str
    statement: str
    raw_values: dict[str, object]


@dataclass(slots=True)
class RootCauseHypothesis:
    hypothesis_id: str
    operational_event_id: str
    candidate_type: str
    summary: str
    rank: int
    evidence_tier: EvidenceTier
    is_leading: bool
    service_relevance: ServiceRelevance
    version_alignment: VersionAlignment
    scope_alignment: ScopeAlignment
    error_relevance: ErrorRelevance
    seconds_before_incident: float
    supporting: list[RcaEvidence] = field(default_factory=list)
    contradictory: list[RcaEvidence] = field(default_factory=list)
    missing: list[RcaEvidence] = field(default_factory=list)
    not_applicable: list[RcaEvidence] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RejectedOperationalEvent:
    operational_event_id: str
    reason: str
    hard_contradiction: bool


@dataclass(slots=True)
class RootCauseResult:
    result_id: str
    incident_id: str
    result_version: int
    analysis_version: int
    rules_version: str
    overall_tier: EvidenceTier
    leading_hypothesis: RootCauseHypothesis | None
    candidates: list[RootCauseHypothesis]
    rejected_events: list[RejectedOperationalEvent]
    insufficient_evidence_reason: str | None


class RootCauseEngine:
    RULES_VERSION = "rca-rules.v1"
    DEPENDENCIES = {
        "PAYMENT_GATEWAY": {"TOKEN_SERVICE", "NETWORK_CONNECTOR"},
    }
    ERROR_RELEVANCE = {
        "TOKEN_VALIDATION_FAILED": {
            "services": {"PAYMENT_GATEWAY", "TOKEN_SERVICE"},
            "categories": {
                "TOKEN_VALIDATION",
                "TOKEN_CONFIGURATION",
                "TOKEN_KEY_MANAGEMENT",
            },
        }
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._latest: dict[str, RootCauseResult] = {}
        self._input_keys: dict[str, str] = {}

    def run(
        self,
        incident_id: str,
        incident_start: datetime,
        analysis: DimensionalAnalysisResult,
        operational_events: list[OperationalEvent],
        recovery_confirmed: bool = False,
    ) -> RootCauseResult:
        input_key = "|".join(
            [
                str(analysis.analysis_version),
                *(sorted(str(event.event_id) for event in operational_events)),
                str(recovery_confirmed),
                self.settings.configuration_version,
            ]
        )
        if self._input_keys.get(incident_id) == input_key:
            return self._latest[incident_id]
        previous = self._latest.get(incident_id)
        result_version = previous.result_version + 1 if previous else 1
        candidates: list[RootCauseHypothesis] = []
        rejected: list[RejectedOperationalEvent] = []
        later_rollbacks: list[OperationalEvent] = []
        affected_service = "PAYMENT_GATEWAY"
        affected_scope = (
            analysis.best_affected_scope.components if analysis.best_affected_scope else {}
        )
        signature = (
            analysis.dominant_error_signature.normalized_error_code
            if analysis.dominant_error_signature
            else None
        )
        earliest = incident_start - timedelta(seconds=self.settings.rca_lookback_seconds)
        latest = incident_start + timedelta(seconds=self.settings.rca_clock_skew_seconds)

        for event in operational_events:
            if event.event_type is OperationalEventType.ROLLBACK and event.occurred_at > latest:
                later_rollbacks.append(event)
                continue
            if event.occurred_at > latest:
                rejected.append(
                    RejectedOperationalEvent(
                        str(event.event_id),
                        "Event occurred after the incident start beyond allowed clock skew",
                        True,
                    )
                )
                continue
            if event.occurred_at < earliest:
                rejected.append(
                    RejectedOperationalEvent(
                        str(event.event_id), "Event is outside the configured RCA lookback", False
                    )
                )
                continue
            service_relevance = self._service_relevance(affected_service, event.affected_service)
            if service_relevance is ServiceRelevance.UNRELATED:
                rejected.append(
                    RejectedOperationalEvent(
                        str(event.event_id), "Changed service is outside the dependency map", True
                    )
                )
                continue
            scope_alignment = self._scope_alignment(affected_scope, event)
            if scope_alignment is ScopeAlignment.DISJOINT:
                rejected.append(
                    RejectedOperationalEvent(
                        str(event.event_id), "Operational and incident scopes are disjoint", True
                    )
                )
                continue
            candidate = self._build_candidate(
                incident_id,
                incident_start,
                event,
                affected_service,
                affected_scope,
                signature,
                analysis,
                service_relevance,
                scope_alignment,
            )
            candidates.append(candidate)

        if recovery_confirmed:
            for candidate in candidates:
                event = next(
                    item
                    for item in operational_events
                    if str(item.event_id) == candidate.operational_event_id
                )
                for rollback in later_rollbacks:
                    if (
                        rollback.status is OperationalStatus.SUCCEEDED
                        and event.new_version
                        and rollback.from_version == event.new_version
                    ):
                        candidate.supporting.append(
                            RcaEvidence(
                                "ROLLBACK_RECOVERY_SUPPORT",
                                "A later successful rollback of the changed version was "
                                "followed by statistically confirmed recovery.",
                                {
                                    "rollback_event_id": str(rollback.event_id),
                                    "from_version": rollback.from_version,
                                    "to_version": rollback.to_version,
                                },
                            )
                        )
                        candidate.evidence_tier = self._tier(candidate, recovery_support=True)

        tier_order = {
            EvidenceTier.STRONG_EVIDENCE: 3,
            EvidenceTier.MODERATE_EVIDENCE: 2,
            EvidenceTier.WEAK_EVIDENCE: 1,
            EvidenceTier.INSUFFICIENT_EVIDENCE: 0,
        }
        candidates.sort(
            key=lambda candidate: (
                tier_order[candidate.evidence_tier],
                candidate.version_alignment is VersionAlignment.MATCH,
                candidate.scope_alignment
                in {ScopeAlignment.EXACT, ScopeAlignment.CONTAINS_AFFECTED_SCOPE},
                candidate.error_relevance is ErrorRelevance.MATCH,
                any(item.code == "COUNTERFACTUAL_SUPPORT" for item in candidate.supporting),
                -candidate.seconds_before_incident,
            ),
            reverse=True,
        )
        candidates = candidates[: self.settings.rca_shortlist_size]
        for rank, candidate in enumerate(candidates, start=1):
            candidate.rank = rank
            candidate.is_leading = False
        leading = next(
            (
                candidate
                for candidate in candidates
                if candidate.evidence_tier
                in {EvidenceTier.STRONG_EVIDENCE, EvidenceTier.MODERATE_EVIDENCE}
            ),
            None,
        )
        if leading:
            leading.is_leading = True
            overall = leading.evidence_tier
            insufficient_reason = None
        else:
            overall = EvidenceTier.INSUFFICIENT_EVIDENCE
            insufficient_reason = "No observed operational change reached MODERATE_EVIDENCE"
        result_identity = f"{incident_id}:{result_version}:{input_key}"
        result = RootCauseResult(
            result_id=f"rca_{uuid5(NAMESPACE_URL, result_identity).hex[:16]}",
            incident_id=incident_id,
            result_version=result_version,
            analysis_version=analysis.analysis_version,
            rules_version=self.RULES_VERSION,
            overall_tier=overall,
            leading_hypothesis=leading,
            candidates=candidates,
            rejected_events=rejected,
            insufficient_evidence_reason=insufficient_reason,
        )
        self._latest[incident_id] = result
        self._input_keys[incident_id] = input_key
        return result

    def _build_candidate(
        self,
        incident_id: str,
        incident_start: datetime,
        event: OperationalEvent,
        affected_service: str,
        affected_scope: dict[str, str],
        signature: str | None,
        analysis: DimensionalAnalysisResult,
        service_relevance: ServiceRelevance,
        scope_alignment: ScopeAlignment,
    ) -> RootCauseHypothesis:
        seconds = (incident_start - event.occurred_at).total_seconds()
        version_alignment = self._version_alignment(
            affected_service, affected_scope.get("service_version"), event, service_relevance
        )
        error_relevance = self._error_relevance(signature, event)
        supporting = [
            RcaEvidence(
                "VALID_TIMING",
                "The observed change preceded incident onset within the configured lookback.",
                {"seconds_before_incident": seconds, "occurred_at": event.occurred_at.isoformat()},
            ),
            RcaEvidence(
                "SERVICE_RELEVANCE",
                "The changed service has "
                f"{service_relevance.value.lower().replace('_', ' ')} relevance.",
                {"service": event.affected_service, "relevance": service_relevance.value},
            ),
        ]
        contradictory: list[RcaEvidence] = []
        missing: list[RcaEvidence] = []
        not_applicable: list[RcaEvidence] = []
        if version_alignment is VersionAlignment.MATCH:
            supporting.append(
                RcaEvidence(
                    "VERSION_MATCH",
                    "The direct deployment version matches the affected service version.",
                    {
                        "event_version": event.new_version,
                        "affected_version": affected_scope.get("service_version"),
                    },
                )
            )
        elif version_alignment is VersionAlignment.NO_MATCH:
            contradictory.append(
                RcaEvidence(
                    "VERSION_MISMATCH",
                    "The direct deployment version does not match the affected version.",
                    {
                        "event_version": event.new_version,
                        "affected_version": affected_scope.get("service_version"),
                    },
                )
            )
        elif version_alignment is VersionAlignment.NOT_APPLICABLE:
            not_applicable.append(
                RcaEvidence(
                    "VERSION_NOT_APPLICABLE",
                    "Direct version comparison does not apply to a dependency change.",
                    {"changed_service": event.affected_service},
                )
            )
        else:
            missing.append(
                RcaEvidence(
                    "VERSION_UNKNOWN", "Direct version-alignment evidence is unavailable.", {}
                )
            )
        if scope_alignment in {ScopeAlignment.EXACT, ScopeAlignment.CONTAINS_AFFECTED_SCOPE}:
            supporting.append(
                RcaEvidence(
                    "SCOPE_ALIGNMENT",
                    "The observed change scope aligns with the affected traffic scope.",
                    {"scope_alignment": scope_alignment.value},
                )
            )
        elif scope_alignment is ScopeAlignment.PARTIAL:
            contradictory.append(
                RcaEvidence(
                    "PARTIAL_SCOPE_ALIGNMENT",
                    "Only part of the observed change scope aligns with affected traffic.",
                    {"scope_alignment": scope_alignment.value},
                )
            )
        else:
            missing.append(
                RcaEvidence("SCOPE_UNKNOWN", "Change-scope evidence is unavailable.", {})
            )
        if error_relevance is ErrorRelevance.MATCH:
            supporting.append(
                RcaEvidence(
                    "ERROR_RELEVANCE_MATCH",
                    "The controlled error signature is broadly relevant to the changed "
                    "service/category.",
                    {
                        "error_signature": signature,
                        "change_categories": [item.value for item in event.change_categories],
                    },
                )
            )
        elif error_relevance is ErrorRelevance.NO_MATCH:
            contradictory.append(
                RcaEvidence(
                    "ERROR_RELEVANCE_MISMATCH",
                    "The controlled error signature does not align with the change metadata.",
                    {"error_signature": signature},
                )
            )
        else:
            missing.append(
                RcaEvidence(
                    "ERROR_RELEVANCE_UNKNOWN",
                    "Controlled change-category evidence is missing, so error relevance "
                    "is unknown.",
                    {"error_signature": signature},
                )
            )
        if (
            analysis.best_affected_scope
            and analysis.best_affected_scope.complement_interpretation == "CONCENTRATED"
            and version_alignment is VersionAlignment.MATCH
        ):
            supporting.append(
                RcaEvidence(
                    "COUNTERFACTUAL_SUPPORT",
                    "Affected-version traffic is degraded while its complement remains "
                    "materially healthier.",
                    {
                        "affected_rate": analysis.best_affected_scope.technical_error_rate,
                        "complement_rate": (
                            analysis.best_affected_scope.complement_technical_error_rate
                        ),
                    },
                )
            )
        summary = self._summary(event, signature)
        hypothesis_identity = f"{incident_id}:{event.event_id}"
        hypothesis = RootCauseHypothesis(
            hypothesis_id=f"hyp_{uuid5(NAMESPACE_URL, hypothesis_identity).hex[:16]}",
            operational_event_id=str(event.event_id),
            candidate_type=event.event_type.value,
            summary=summary,
            rank=0,
            evidence_tier=EvidenceTier.WEAK_EVIDENCE,
            is_leading=False,
            service_relevance=service_relevance,
            version_alignment=version_alignment,
            scope_alignment=scope_alignment,
            error_relevance=error_relevance,
            seconds_before_incident=seconds,
            supporting=supporting,
            contradictory=contradictory,
            missing=missing,
            not_applicable=not_applicable,
        )
        hypothesis.evidence_tier = self._tier(hypothesis, recovery_support=False)
        return hypothesis

    @staticmethod
    def _tier(candidate: RootCauseHypothesis, recovery_support: bool) -> EvidenceTier:
        codes = {item.code for item in candidate.supporting}
        strong = {
            "VERSION_MATCH",
            "SCOPE_ALIGNMENT",
            "ERROR_RELEVANCE_MATCH",
            "COUNTERFACTUAL_SUPPORT",
        }
        if strong <= codes or (recovery_support and len(strong & codes) >= 2):
            return EvidenceTier.STRONG_EVIDENCE
        if strong & codes:
            return EvidenceTier.MODERATE_EVIDENCE
        return EvidenceTier.WEAK_EVIDENCE

    def _service_relevance(self, affected_service: str, changed_service: str) -> ServiceRelevance:
        if changed_service == affected_service:
            return ServiceRelevance.EXACT_SERVICE
        if changed_service in self.DEPENDENCIES.get(affected_service, set()):
            return ServiceRelevance.KNOWN_DEPENDENCY
        return ServiceRelevance.UNRELATED

    @staticmethod
    def _version_alignment(
        affected_service: str,
        affected_version: str | None,
        event: OperationalEvent,
        relevance: ServiceRelevance,
    ) -> VersionAlignment:
        if relevance is ServiceRelevance.KNOWN_DEPENDENCY:
            return VersionAlignment.NOT_APPLICABLE
        event_version = event.new_version or event.to_version
        if not affected_version or not event_version:
            return VersionAlignment.UNKNOWN
        return (
            VersionAlignment.MATCH
            if event_version == affected_version
            else VersionAlignment.NO_MATCH
        )

    @staticmethod
    def _scope_alignment(affected_scope: dict[str, str], event: OperationalEvent) -> ScopeAlignment:
        region = affected_scope.get("processing_region")
        method = affected_scope.get("payment_method")
        region_known = bool(event.affected_regions)
        method_known = bool(event.affected_payment_methods)
        if not region and not method:
            return ScopeAlignment.UNKNOWN
        if not region_known and not method_known:
            return ScopeAlignment.UNKNOWN
        if region and region_known and region not in event.affected_regions:
            return ScopeAlignment.DISJOINT
        if (
            method
            and method_known
            and method not in {item.value for item in event.affected_payment_methods}
        ):
            return ScopeAlignment.DISJOINT
        if region and method and region_known and method_known:
            exact = len(event.affected_regions) == 1 and len(event.affected_payment_methods) == 1
            return ScopeAlignment.EXACT if exact else ScopeAlignment.CONTAINS_AFFECTED_SCOPE
        return ScopeAlignment.PARTIAL

    def _error_relevance(self, signature: str | None, event: OperationalEvent) -> ErrorRelevance:
        if not signature or signature not in self.ERROR_RELEVANCE:
            return ErrorRelevance.UNKNOWN
        mapping = self.ERROR_RELEVANCE[signature]
        if event.affected_service not in mapping["services"]:
            return ErrorRelevance.NO_MATCH
        if not event.change_categories:
            return ErrorRelevance.UNKNOWN
        categories = {item.value for item in event.change_categories}
        return (
            ErrorRelevance.MATCH if categories & mapping["categories"] else ErrorRelevance.NO_MATCH
        )

    @staticmethod
    def _summary(event: OperationalEvent, signature: str | None) -> str:
        if event.event_type is OperationalEventType.DEPLOYMENT:
            return (
                f"The observed {event.affected_service} {event.new_version} deployment may have "
                f"introduced the {signature or 'technical-error'} regression."
            )
        if event.event_type is OperationalEventType.CONFIG_CHANGE:
            return (
                f"The observed {event.affected_service} configuration change may explain "
                "the incident."
            )
        return (
            f"The observed {event.affected_service} rollback may explain a later worsening phase."
        )
