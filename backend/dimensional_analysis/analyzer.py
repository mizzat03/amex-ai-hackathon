"""Bounded single-dimension, pair, triple, complement, and error-signature analysis."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import combinations
from backend.config.settings import Settings
from backend.metrics.aggregator import AggregateCounter, MetricSnapshot, WindowAggregate

DIMENSION_ORDER = ("processing_region", "payment_method", "service_version")


class AnalysisCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(slots=True)
class CandidateFinding:
    candidate_id: str
    components: dict[str, str]
    label: str
    current_attempts: int
    current_technical_errors: int
    technical_error_rate: float
    baseline_attempts: int
    baseline_technical_errors: int
    baseline_technical_error_rate: float
    expected_current_errors: float
    excess_technical_errors: float
    global_excess_share: float
    traffic_share: float
    absolute_rate_increase: float
    rate_lift: float | None
    newly_observed_pattern: bool
    complement_attempts: int
    complement_technical_errors: int
    complement_technical_error_rate: float | None
    complement_interpretation: str
    eligible: bool
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DominantErrorSignature:
    normalized_error_code: str
    label: str
    current_count: int
    share_of_technical_errors: float
    current_attempt_rate: float
    baseline_attempt_rate: float
    expected_count: float
    excess_count: float


@dataclass(slots=True)
class DimensionalAnalysisResult:
    incident_id: str
    analysis_version: int
    configuration_version: str
    current_period: tuple[datetime, datetime]
    baseline_period: tuple[datetime, datetime]
    completeness: AnalysisCompleteness
    ranked_dimensions: dict[str, list[CandidateFinding]]
    ranked_combinations: list[CandidateFinding]
    best_affected_scope: CandidateFinding | None
    dominant_error_signature: DominantErrorSignature | None
    rejected_candidates: list[CandidateFinding]
    caveats: list[str]


class DimensionalAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(
        self, incident_id: str, snapshot: MetricSnapshot, analysis_version: int
    ) -> DimensionalAnalysisResult:
        return self.analyze_windows(
            incident_id,
            snapshot.current,
            snapshot.baseline,
            analysis_version,
        )

    def analyze_windows(
        self,
        incident_id: str,
        current: WindowAggregate,
        baseline: WindowAggregate,
        analysis_version: int,
    ) -> DimensionalAnalysisResult:
        caveats: list[str] = []
        rejected: list[CandidateFinding] = []
        global_baseline_rate = (
            baseline.technical_error_count / baseline.total_attempts
            if baseline.total_attempts
            else 0.0
        )
        global_excess = max(
            0.0,
            current.technical_error_count - current.total_attempts * global_baseline_rate,
        )
        ranked_dimensions: dict[str, list[CandidateFinding]] = {}
        individual_lookup: dict[tuple[tuple[str, str], ...], CandidateFinding] = {}
        seeds: dict[str, set[str]] = {}

        for dimension in DIMENSION_ORDER:
            candidates: list[CandidateFinding] = []
            current_values = current.dimensions.get(dimension, {})
            baseline_values = baseline.dimensions.get(dimension, {})
            for value, current_counter in current_values.items():
                finding = self._candidate(
                    {dimension: value},
                    current_counter,
                    baseline_values.get(value),
                    current,
                    global_excess,
                )
                individual_lookup[self._key(finding.components)] = finding
                if finding.eligible:
                    candidates.append(finding)
                else:
                    rejected.append(finding)
            candidates.sort(key=self._rank_key, reverse=True)
            ranked_dimensions[dimension] = candidates[: self.settings.dimension_seed_top_n]
            seeds[dimension] = {
                candidate.components[dimension]
                for candidate in ranked_dimensions[dimension]
            }

        if not current.combinations or not baseline.combinations:
            caveats.append(
                "Required observed-combination rollups are unavailable; no combination is declared unaffected."
            )
            completeness = AnalysisCompleteness.INCOMPLETE
            combination_findings: list[CandidateFinding] = []
        else:
            combination_findings = self._combination_candidates(
                current, baseline, global_excess, seeds, individual_lookup, rejected
            )
            completeness = AnalysisCompleteness.COMPLETE

        eligible_individuals = [
            item for values in ranked_dimensions.values() for item in values if item.eligible
        ]
        all_eligible = eligible_individuals + combination_findings
        if not all_eligible:
            completeness = (
                AnalysisCompleteness.INCOMPLETE
                if completeness is AnalysisCompleteness.INCOMPLETE
                else AnalysisCompleteness.INSUFFICIENT_DATA
            )
            caveats.append("No affected segment met the configured volume and practical-effect gates.")
        if any(
            "MIN_CURRENT_ATTEMPTS" in item.rejection_reasons
            or "MIN_BASELINE_ATTEMPTS" in item.rejection_reasons
            for item in rejected
        ):
            caveats.append(
                "Low-volume correlations were retained in the audit record but excluded from affected scope."
            )

        best = None
        if all_eligible:
            best = max(
                all_eligible,
                key=lambda item: (
                    len(item.components),
                    item.excess_technical_errors,
                    item.absolute_rate_increase,
                    item.current_attempts,
                ),
            )
        signature = self._dominant_signature(current, baseline)
        combination_findings.sort(key=self._rank_key, reverse=True)
        return DimensionalAnalysisResult(
            incident_id=incident_id,
            analysis_version=analysis_version,
            configuration_version=self.settings.configuration_version,
            current_period=(current.start_at, current.end_at),
            baseline_period=(baseline.start_at, baseline.end_at),
            completeness=completeness,
            ranked_dimensions=ranked_dimensions,
            ranked_combinations=combination_findings,
            best_affected_scope=best,
            dominant_error_signature=signature,
            rejected_candidates=rejected,
            caveats=caveats,
        )

    def _combination_candidates(
        self,
        current: WindowAggregate,
        baseline: WindowAggregate,
        global_excess: float,
        seeds: dict[str, set[str]],
        individual_lookup: dict[tuple[tuple[str, str], ...], CandidateFinding],
        rejected: list[CandidateFinding],
    ) -> list[CandidateFinding]:
        accepted_lookup = dict(individual_lookup)
        accepted: list[CandidateFinding] = []
        for size in (2, 3):
            for dimensions in combinations(DIMENSION_ORDER, size):
                current_rollup = self._rollup_combinations(current, dimensions)
                baseline_rollup = self._rollup_combinations(baseline, dimensions)
                for values, current_counter in current_rollup.items():
                    components = dict(zip(dimensions, values, strict=True))
                    if any(value not in seeds[dimension] for dimension, value in components.items()):
                        continue
                    finding = self._candidate(
                        components,
                        current_counter,
                        baseline_rollup.get(values),
                        current,
                        global_excess,
                    )
                    if not finding.eligible:
                        rejected.append(finding)
                        continue
                    parents = [
                        accepted_lookup.get(self._key({key: value for key, value in components.items() if key != removed}))
                        for removed in components
                    ]
                    parents = [parent for parent in parents if parent is not None and parent.eligible]
                    if parents:
                        parent = max(parents, key=lambda item: item.excess_technical_errors)
                        retains = finding.excess_technical_errors >= (
                            parent.excess_technical_errors
                            * self.settings.dimension_child_excess_retention
                        )
                        concentrates = finding.technical_error_rate >= (
                            parent.technical_error_rate
                            * (1 + self.settings.dimension_concentration_improvement)
                        )
                        if not retains or not concentrates:
                            finding.eligible = False
                            finding.rejection_reasons.append("NO_MEANINGFUL_NARROWING")
                            rejected.append(finding)
                            continue
                    accepted.append(finding)
                    accepted_lookup[self._key(components)] = finding
        return accepted

    def _candidate(
        self,
        components: dict[str, str],
        current_counter: AggregateCounter,
        baseline_counter: AggregateCounter | None,
        current_global: WindowAggregate,
        global_excess: float,
    ) -> CandidateFinding:
        baseline_counter = baseline_counter or AggregateCounter()
        current_rate = (
            current_counter.technical_error_count / current_counter.total_attempts
            if current_counter.total_attempts
            else 0.0
        )
        baseline_rate = (
            baseline_counter.technical_error_count / baseline_counter.total_attempts
            if baseline_counter.total_attempts
            else 0.0
        )
        expected = current_counter.total_attempts * baseline_rate
        excess = current_counter.technical_error_count - expected
        delta = current_rate - baseline_rate
        reasons: list[str] = []
        if current_counter.total_attempts < self.settings.dimension_min_current_attempts:
            reasons.append("MIN_CURRENT_ATTEMPTS")
        if baseline_counter.total_attempts < self.settings.dimension_min_baseline_attempts:
            reasons.append("MIN_BASELINE_ATTEMPTS")
        if current_counter.technical_error_count < self.settings.dimension_min_current_errors:
            reasons.append("MIN_CURRENT_TECHNICAL_ERRORS")
        if excess < self.settings.dimension_min_excess_errors:
            reasons.append("MIN_POSITIVE_EXCESS_ERRORS")
        if delta < self.settings.dimension_min_rate_increase:
            reasons.append("MIN_PRACTICAL_RATE_INCREASE")
        complement_attempts = current_global.total_attempts - current_counter.total_attempts
        complement_errors = (
            current_global.technical_error_count - current_counter.technical_error_count
        )
        complement_rate = (
            complement_errors / complement_attempts if complement_attempts > 0 else None
        )
        interpretation = (
            "CONCENTRATED"
            if complement_rate is not None
            and current_rate > complement_rate + self.settings.dimension_min_rate_increase
            else "NOT_CONCENTRATED"
        )
        label = " + ".join(components[dimension] for dimension in DIMENSION_ORDER if dimension in components)
        candidate_id = "segment:" + "|".join(
            f"{dimension}={components[dimension]}" for dimension in DIMENSION_ORDER if dimension in components
        )
        return CandidateFinding(
            candidate_id=candidate_id,
            components=dict(components),
            label=f"Affected scope: {label}",
            current_attempts=current_counter.total_attempts,
            current_technical_errors=current_counter.technical_error_count,
            technical_error_rate=current_rate,
            baseline_attempts=baseline_counter.total_attempts,
            baseline_technical_errors=baseline_counter.technical_error_count,
            baseline_technical_error_rate=baseline_rate,
            expected_current_errors=expected,
            excess_technical_errors=excess,
            global_excess_share=max(0.0, excess) / global_excess if global_excess else 0.0,
            traffic_share=(
                current_counter.total_attempts / current_global.total_attempts
                if current_global.total_attempts
                else 0.0
            ),
            absolute_rate_increase=delta,
            rate_lift=current_rate / baseline_rate if baseline_rate > 0 else None,
            newly_observed_pattern=baseline_rate == 0 and current_counter.technical_error_count > 0,
            complement_attempts=complement_attempts,
            complement_technical_errors=complement_errors,
            complement_technical_error_rate=complement_rate,
            complement_interpretation=interpretation,
            eligible=not reasons,
            rejection_reasons=reasons,
        )

    @staticmethod
    def _rollup_combinations(
        window: WindowAggregate, dimensions: tuple[str, ...]
    ) -> dict[tuple[str, ...], AggregateCounter]:
        indices = tuple(DIMENSION_ORDER.index(dimension) for dimension in dimensions)
        result: dict[tuple[str, ...], AggregateCounter] = {}
        for triple, counter in window.combinations.items():
            key = tuple(triple[index] for index in indices)
            result.setdefault(key, AggregateCounter()).merge(counter)
        return result

    @staticmethod
    def _dominant_signature(
        current: WindowAggregate, baseline: WindowAggregate
    ) -> DominantErrorSignature | None:
        if not current.error_code_counts or current.technical_error_count <= 0:
            return None
        code, count = max(current.error_code_counts.items(), key=lambda item: (item[1], item[0]))
        baseline_count = baseline.error_code_counts.get(code, 0)
        baseline_rate = baseline_count / baseline.total_attempts if baseline.total_attempts else 0.0
        expected = current.total_attempts * baseline_rate
        return DominantErrorSignature(
            normalized_error_code=code,
            label=f"Dominant error signature (symptom): {code}",
            current_count=count,
            share_of_technical_errors=count / current.technical_error_count,
            current_attempt_rate=count / current.total_attempts if current.total_attempts else 0.0,
            baseline_attempt_rate=baseline_rate,
            expected_count=expected,
            excess_count=count - expected,
        )

    @staticmethod
    def _key(components: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple((dimension, components[dimension]) for dimension in DIMENSION_ORDER if dimension in components)

    @staticmethod
    def _rank_key(item: CandidateFinding) -> tuple[float, float, int]:
        return (
            item.excess_technical_errors,
            item.absolute_rate_increase,
            item.current_attempts,
        )
