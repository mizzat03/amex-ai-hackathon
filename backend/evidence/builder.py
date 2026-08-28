"""Immutable evidence packages and traceable dashboard/copilot projections."""

from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import ConfigDict, Field

from backend.anomaly_detection.detector import DetectionEvaluation
from backend.config.settings import Settings
from backend.contracts.api import (
    EvidenceCitationRef,
    EvidenceItemView,
    EvidenceProjectionResponse,
    HypothesisRelationView,
    HypothesisView,
    Period,
    ScopedValue,
)
from backend.contracts.common import ContractModel
from backend.contracts.enums import (
    EvidenceCategory,
    EvidenceCompleteness,
    EvidenceTier,
    HypothesisRelation,
    IncidentLifecycle,
    IncidentSeverity,
    TemporalScope,
)
from backend.dimensional_analysis.analyzer import (
    AnalysisCompleteness,
    DimensionalAnalysisResult,
)
from backend.root_cause.engine import RootCauseHypothesis, RootCauseResult


class UnsafeEvidencePackage(RuntimeError):
    pass


class FrozenContractModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class IncidentEvidenceInput(ContractModel):
    incident_id: str
    lifecycle: IncidentLifecycle
    severity: IncidentSeverity
    started_at: datetime
    updated_at: datetime


class EvidencePeriod(FrozenContractModel):
    start_at: datetime
    end_at: datetime


class EvidenceProvenance(FrozenContractModel):
    source_module: str
    source_record_id: str
    source_version: str
    rule_version: str
    calculation_lineage: tuple[str, ...]


class CanonicalEvidenceItem(FrozenContractModel):
    evidence_id: str
    stable_logical_key: str
    category: EvidenceCategory
    statement: str
    structured_value: dict[str, Any] | None = None
    unit: str | None = None
    period: EvidencePeriod | None = None
    scope: dict[str, str] | None = None
    temporal_scope: TemporalScope
    provenance: EvidenceProvenance
    source_references: tuple[str, ...]


class CanonicalHypothesis(FrozenContractModel):
    hypothesis_id: str
    rank: int = Field(ge=1)
    summary: str
    candidate_type: Literal["DEPLOYMENT", "CONFIG_CHANGE", "ROLLBACK"]
    evidence_tier: EvidenceTier
    is_leading: bool
    operational_event_id: str
    supporting: tuple[str, ...]
    contradictory: tuple[str, ...]
    missing: tuple[str, ...]
    not_applicable: tuple[str, ...]


class EvidencePackage(FrozenContractModel):
    incident_id: str
    evidence_package_id: str
    package_version: int = Field(ge=1)
    schema_version: Literal["evidence-package.v1"] = "evidence-package.v1"
    builder_configuration_version: str
    generated_at: datetime
    completeness: EvidenceCompleteness
    validation_messages: tuple[str, ...]
    incident_snapshot: IncidentEvidenceInput
    current_period: EvidencePeriod | None
    baseline_period: EvidencePeriod | None
    anomaly_evaluation_id: str
    dimensional_analysis_version: int
    rca_result_version: int
    evidence_catalogue: tuple[CanonicalEvidenceItem, ...]
    hypotheses: tuple[CanonicalHypothesis, ...]
    package_limitations: tuple[str, ...]
    citation_allowlist: tuple[str, ...]


class CopilotEvidenceItem(FrozenContractModel):
    evidence_id: str
    category: EvidenceCategory
    statement: str
    structured_value: dict[str, Any] | None
    temporal_scope: TemporalScope


class CopilotProjection(FrozenContractModel):
    incident_id: str
    evidence_package_id: str
    evidence_package_version: int
    completeness: EvidenceCompleteness
    leading_hypothesis_id: str | None
    evidence_tier: EvidenceTier
    evidence: tuple[CopilotEvidenceItem, ...]
    limitations: tuple[str, ...]
    citation_allowlist: tuple[str, ...]


class EvidenceBuilder:
    SCHEMA_VERSION = "evidence-package.v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._packages: dict[str, list[EvidencePackage]] = {}
        self._idempotency: dict[str, EvidencePackage] = {}

    def build(
        self,
        incident: IncidentEvidenceInput,
        anomaly: DetectionEvaluation,
        analysis: DimensionalAnalysisResult,
        rca: RootCauseResult,
        optional_missing: list[str] | None = None,
    ) -> EvidencePackage:
        optional_missing = optional_missing or []
        input_key = "|".join(
            [
                incident.incident_id,
                anomaly.evaluation_id,
                str(analysis.analysis_version),
                str(rca.result_version),
                self.settings.configuration_version,
                *sorted(optional_missing),
            ]
        )
        if input_key in self._idempotency:
            return self._idempotency[input_key]
        package_id = f"pkg_{uuid5(NAMESPACE_URL, incident.incident_id + ':' + self.SCHEMA_VERSION).hex[:16]}"
        version = len(self._packages.get(incident.incident_id, [])) + 1
        validation_messages: list[str] = []
        invalid = False
        if analysis.incident_id != incident.incident_id or rca.incident_id != incident.incident_id:
            invalid = True
            validation_messages.append("Upstream incident ownership mismatch")
        if rca.analysis_version != analysis.analysis_version:
            invalid = True
            validation_messages.append("RCA and dimensional-analysis versions are incompatible")
        if not analysis.current_period[0] or not analysis.current_period[1]:
            invalid = True
            validation_messages.append("Current investigation period is unavailable")

        items: list[CanonicalEvidenceItem] = []
        hypotheses: list[CanonicalHypothesis] = []
        relations_by_hypothesis: dict[str, dict[str, list[str]]] = {}

        def add_item(
            logical_key: str,
            category: EvidenceCategory,
            statement: str,
            structured_value: dict[str, Any] | None,
            unit: str | None,
            period: tuple[datetime, datetime] | None,
            scope: dict[str, str] | None,
            temporal_scope: TemporalScope,
            source_module: str,
            source_record_id: str,
            source_version: str,
            rule_version: str,
            lineage: tuple[str, ...],
        ) -> str:
            evidence_id = f"ev_{uuid5(NAMESPACE_URL, f'{package_id}:{version}:{logical_key}').hex[:18]}"
            items.append(
                CanonicalEvidenceItem(
                    evidence_id=evidence_id,
                    stable_logical_key=logical_key,
                    category=category,
                    statement=statement,
                    structured_value=structured_value,
                    unit=unit,
                    period=EvidencePeriod(start_at=period[0], end_at=period[1]) if period else None,
                    scope=scope,
                    temporal_scope=temporal_scope,
                    provenance=EvidenceProvenance(
                        source_module=source_module,
                        source_record_id=source_record_id,
                        source_version=source_version,
                        rule_version=rule_version,
                        calculation_lineage=lineage,
                    ),
                    source_references=(source_record_id,),
                )
            )
            return evidence_id

        if not invalid:
            add_item(
                "metric.current.technical_error_rate",
                EvidenceCategory.OBSERVED_FACT,
                "The current window contains an elevated technical-error rate.",
                {
                    "attempts": anomaly.current_attempts,
                    "technical_errors": anomaly.current_errors,
                    "rate": anomaly.current_value,
                },
                "RATE",
                analysis.current_period,
                None,
                TemporalScope.INCIDENT_SNAPSHOT,
                "anomaly_detection",
                anomaly.evaluation_id,
                str(anomaly.snapshot_version),
                anomaly.configuration_version,
                ("metric_snapshot", "technical_error_detector"),
            )
            add_item(
                "metric.baseline.technical_error_rate",
                EvidenceCategory.OBSERVED_FACT,
                "The non-overlapping healthy baseline technical-error rate is lower.",
                {
                    "attempts": anomaly.baseline_attempts,
                    "technical_errors": anomaly.baseline_errors,
                    "rate": anomaly.baseline_value,
                },
                "RATE",
                analysis.baseline_period,
                None,
                TemporalScope.HISTORICAL_BASELINE,
                "anomaly_detection",
                anomaly.evaluation_id,
                str(anomaly.snapshot_version),
                anomaly.configuration_version,
                ("healthy_baseline", "two_proportion_input"),
            )
            if analysis.best_affected_scope:
                add_item(
                    "scope.best_supported",
                    EvidenceCategory.DERIVED_FINDING,
                    analysis.best_affected_scope.label,
                    {
                        "technical_error_rate": analysis.best_affected_scope.technical_error_rate,
                        "excess_technical_errors": analysis.best_affected_scope.excess_technical_errors,
                        "complement_technical_error_rate": analysis.best_affected_scope.complement_technical_error_rate,
                    },
                    "RATE",
                    analysis.current_period,
                    analysis.best_affected_scope.components,
                    TemporalScope.INCIDENT_SNAPSHOT,
                    "dimensional_analysis",
                    f"analysis:{analysis.analysis_version}",
                    str(analysis.analysis_version),
                    analysis.configuration_version,
                    ("bucket_rollups", "eligibility_gates", "complement_comparison"),
                )
            if analysis.dominant_error_signature:
                add_item(
                    "error_signature.dominant",
                    EvidenceCategory.DERIVED_FINDING,
                    analysis.dominant_error_signature.label,
                    {
                        "normalized_error_code": analysis.dominant_error_signature.normalized_error_code,
                        "count": analysis.dominant_error_signature.current_count,
                        "share": analysis.dominant_error_signature.share_of_technical_errors,
                    },
                    "COUNT",
                    analysis.current_period,
                    analysis.best_affected_scope.components if analysis.best_affected_scope else None,
                    TemporalScope.INCIDENT_SNAPSHOT,
                    "dimensional_analysis",
                    f"analysis:{analysis.analysis_version}",
                    str(analysis.analysis_version),
                    analysis.configuration_version,
                    ("technical_error_code_rollup", "dominant_signature_ranking"),
                )

            for candidate in rca.candidates:
                groups = {"supporting": [], "contradictory": [], "missing": [], "not_applicable": []}
                for group_name, category, relation_items in (
                    ("supporting", EvidenceCategory.DERIVED_FINDING, candidate.supporting),
                    ("contradictory", EvidenceCategory.DERIVED_FINDING, candidate.contradictory),
                    ("missing", EvidenceCategory.MISSING_EVIDENCE, candidate.missing),
                    ("not_applicable", EvidenceCategory.LIMITATION, candidate.not_applicable),
                ):
                    for relation in relation_items:
                        evidence_id = add_item(
                            f"hypothesis.{candidate.hypothesis_id}.{relation.code.lower()}",
                            category,
                            relation.statement,
                            relation.raw_values,
                            None,
                            analysis.current_period,
                            analysis.best_affected_scope.components if analysis.best_affected_scope else None,
                            TemporalScope.INCIDENT_SNAPSHOT,
                            "root_cause",
                            rca.result_id,
                            str(rca.result_version),
                            rca.rules_version,
                            ("observed_operational_event", relation.code.lower()),
                        )
                        groups[group_name].append(evidence_id)
                relations_by_hypothesis[candidate.hypothesis_id] = groups
                hypotheses.append(self._canonical_hypothesis(candidate, groups))

            for index, limitation in enumerate(optional_missing, start=1):
                add_item(
                    f"limitation.optional.{index}",
                    EvidenceCategory.MISSING_EVIDENCE,
                    limitation,
                    None,
                    None,
                    analysis.current_period,
                    None,
                    TemporalScope.INCIDENT_SNAPSHOT,
                    "evidence_builder",
                    f"optional-missing:{index}",
                    self.SCHEMA_VERSION,
                    self.settings.configuration_version,
                    ("explicit_missing_input",),
                )

        evidence_ids = {item.evidence_id for item in items}
        relation_ids = {
            evidence_id
            for hypothesis in hypotheses
            for evidence_id in (
                *hypothesis.supporting,
                *hypothesis.contradictory,
                *hypothesis.missing,
                *hypothesis.not_applicable,
            )
        }
        if not relation_ids <= evidence_ids:
            invalid = True
            validation_messages.append("Hypothesis relation references do not resolve")
        if rca.leading_hypothesis:
            packaged_leader = next((item for item in hypotheses if item.is_leading), None)
            if (
                packaged_leader is None
                or packaged_leader.hypothesis_id != rca.leading_hypothesis.hypothesis_id
                or packaged_leader.evidence_tier != rca.leading_hypothesis.evidence_tier
            ):
                invalid = True
                validation_messages.append("Authoritative RCA leader/tier was not preserved")

        limitations = list(optional_missing) + list(analysis.caveats)
        if invalid:
            completeness = EvidenceCompleteness.INVALID
        elif optional_missing or analysis.completeness is not AnalysisCompleteness.COMPLETE:
            completeness = EvidenceCompleteness.PARTIAL
        else:
            completeness = EvidenceCompleteness.COMPLETE
        package = EvidencePackage(
            incident_id=incident.incident_id,
            evidence_package_id=package_id,
            package_version=version,
            builder_configuration_version=self.settings.configuration_version,
            generated_at=incident.updated_at,
            completeness=completeness,
            validation_messages=tuple(validation_messages),
            incident_snapshot=incident,
            current_period=(
                EvidencePeriod(start_at=analysis.current_period[0], end_at=analysis.current_period[1])
                if analysis.current_period[0] and analysis.current_period[1]
                else None
            ),
            baseline_period=(
                EvidencePeriod(start_at=analysis.baseline_period[0], end_at=analysis.baseline_period[1])
                if analysis.baseline_period[0] and analysis.baseline_period[1]
                else None
            ),
            anomaly_evaluation_id=anomaly.evaluation_id,
            dimensional_analysis_version=analysis.analysis_version,
            rca_result_version=rca.result_version,
            evidence_catalogue=tuple(items),
            hypotheses=tuple(hypotheses),
            package_limitations=tuple(dict.fromkeys(limitations)),
            citation_allowlist=tuple(sorted(evidence_ids)),
        )
        self._packages.setdefault(incident.incident_id, []).append(package)
        self._idempotency[input_key] = package
        return package

    def dashboard_projection(self, package: EvidencePackage) -> EvidenceProjectionResponse:
        self._require_usable(package)
        item_views = [self._item_view(item) for item in package.evidence_catalogue]
        hypotheses = [
            HypothesisView(
                hypothesis_id=item.hypothesis_id,
                rank=item.rank,
                summary=item.summary,
                candidate_type=item.candidate_type,
                evidence_tier=item.evidence_tier,
                is_leading=item.is_leading,
                operational_event_id=item.operational_event_id,
                relations=[
                    *[
                        HypothesisRelationView(relation=HypothesisRelation.SUPPORTING, evidence_id=value)
                        for value in item.supporting
                    ],
                    *[
                        HypothesisRelationView(relation=HypothesisRelation.CONTRADICTORY, evidence_id=value)
                        for value in item.contradictory
                    ],
                    *[
                        HypothesisRelationView(relation=HypothesisRelation.MISSING, evidence_id=value)
                        for value in item.missing
                    ],
                    *[
                        HypothesisRelationView(relation=HypothesisRelation.NOT_APPLICABLE, evidence_id=value)
                        for value in item.not_applicable
                    ],
                ],
            )
            for item in package.hypotheses
        ]
        return EvidenceProjectionResponse(
            incident_id=package.incident_id,
            evidence_package_id=package.evidence_package_id,
            evidence_package_version=package.package_version,
            completeness=package.completeness,
            generated_at=package.generated_at,
            items=item_views,
            hypotheses=hypotheses,
            package_limitations=list(package.package_limitations),
            citation_allowlist=[
                EvidenceCitationRef(
                    evidence_id=evidence_id,
                    evidence_package_id=package.evidence_package_id,
                    evidence_package_version=package.package_version,
                )
                for evidence_id in package.citation_allowlist
            ],
        )

    def copilot_projection(self, package: EvidencePackage) -> CopilotProjection:
        self._require_usable(package)
        leader = next((item for item in package.hypotheses if item.is_leading), None)
        return CopilotProjection(
            incident_id=package.incident_id,
            evidence_package_id=package.evidence_package_id,
            evidence_package_version=package.package_version,
            completeness=package.completeness,
            leading_hypothesis_id=leader.hypothesis_id if leader else None,
            evidence_tier=leader.evidence_tier if leader else EvidenceTier.INSUFFICIENT_EVIDENCE,
            evidence=tuple(
                CopilotEvidenceItem(
                    evidence_id=item.evidence_id,
                    category=item.category,
                    statement=item.statement,
                    structured_value=item.structured_value,
                    temporal_scope=item.temporal_scope,
                )
                for item in package.evidence_catalogue
            ),
            limitations=package.package_limitations,
            citation_allowlist=package.citation_allowlist,
        )

    @staticmethod
    def deterministic_fallback_projection(package: EvidencePackage) -> dict[str, object]:
        return {
            "incident_id": package.incident_id,
            "lifecycle": package.incident_snapshot.lifecycle.value,
            "severity": package.incident_snapshot.severity.value,
            "ai_available": False,
            "reason": "Evidence package is invalid; authoritative upstream incident facts remain available.",
        }

    @staticmethod
    def _canonical_hypothesis(
        candidate: RootCauseHypothesis, groups: dict[str, list[str]]
    ) -> CanonicalHypothesis:
        return CanonicalHypothesis(
            hypothesis_id=candidate.hypothesis_id,
            rank=candidate.rank,
            summary=candidate.summary,
            candidate_type=candidate.candidate_type,
            evidence_tier=candidate.evidence_tier,
            is_leading=candidate.is_leading,
            operational_event_id=candidate.operational_event_id,
            supporting=tuple(groups["supporting"]),
            contradictory=tuple(groups["contradictory"]),
            missing=tuple(groups["missing"]),
            not_applicable=tuple(groups["not_applicable"]),
        )

    @staticmethod
    def _item_view(item: CanonicalEvidenceItem) -> EvidenceItemView:
        return EvidenceItemView(
            evidence_id=item.evidence_id,
            stable_logical_key=item.stable_logical_key,
            category=item.category,
            statement=item.statement,
            structured_value=item.structured_value,
            unit=item.unit,
            period=(
                Period(start_at=item.period.start_at, end_at=item.period.end_at)
                if item.period
                else None
            ),
            scope=ScopedValue(**item.scope) if item.scope else None,
            temporal_scope=item.temporal_scope,
            provenance_label=f"{item.provenance.source_module} · {item.provenance.source_version}",
            source_module=item.provenance.source_module,
            source_version=item.provenance.source_version,
        )

    @staticmethod
    def _require_usable(package: EvidencePackage) -> None:
        if package.completeness is EvidenceCompleteness.INVALID:
            raise UnsafeEvidencePackage("invalid packages cannot enter authoritative presentation")
