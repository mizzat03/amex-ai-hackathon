"""Auditable technical-error and latency detector rules."""

from dataclasses import dataclass
from datetime import datetime
from math import erfc, sqrt

from backend.config.settings import Settings
from backend.contracts.enums import TelemetryState
from backend.metrics.aggregator import MetricSnapshot


@dataclass(frozen=True, slots=True)
class DetectionEvaluation:
    evaluation_id: str
    snapshot_version: int
    configuration_version: str
    evaluated_at: datetime
    bucket_evidence_end_at: datetime
    metric_family: str
    scope: str
    telemetry_state: TelemetryState
    evaluated: bool
    is_anomaly: bool
    current_attempts: int
    current_errors: int
    baseline_attempts: int
    baseline_errors: int
    current_value: float | None
    baseline_value: float | None
    absolute_increase: float | None
    z_statistic: float | None
    p_value: float | None
    practical_effect_met: bool
    reason_code: str


class TechnicalErrorDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, snapshot: MetricSnapshot, scope: str = "GLOBAL") -> DetectionEvaluation:
        current = snapshot.current
        baseline = snapshot.baseline
        base = self._base(snapshot, "technical_error_rate", scope)
        if snapshot.telemetry_state is not TelemetryState.HEALTHY:
            return DetectionEvaluation(
                **base,
                evaluated=False,
                is_anomaly=False,
                current_attempts=current.total_attempts,
                current_errors=current.technical_error_count,
                baseline_attempts=baseline.total_attempts,
                baseline_errors=baseline.technical_error_count,
                current_value=current.technical_error_rate,
                baseline_value=baseline.technical_error_rate,
                absolute_increase=None,
                z_statistic=None,
                p_value=None,
                practical_effect_met=False,
                reason_code=f"TELEMETRY_{snapshot.telemetry_state.value}",
            )
        if (
            current.total_attempts < self.settings.min_current_attempts
            or baseline.total_attempts < self.settings.min_baseline_attempts
        ):
            return self._unevaluated(base, snapshot, "INSUFFICIENT_VOLUME")
        if current.technical_error_count < self.settings.min_current_technical_errors:
            return self._unevaluated(base, snapshot, "INSUFFICIENT_CURRENT_ERRORS")

        current_rate = current.technical_error_count / current.total_attempts
        baseline_rate = baseline.technical_error_count / baseline.total_attempts
        delta = current_rate - baseline_rate
        pooled = (current.technical_error_count + baseline.technical_error_count) / (
            current.total_attempts + baseline.total_attempts
        )
        standard_error = sqrt(
            pooled
            * (1 - pooled)
            * (1 / current.total_attempts + 1 / baseline.total_attempts)
        )
        z_statistic = delta / standard_error if standard_error else 0.0
        p_value = 0.5 * erfc(z_statistic / sqrt(2))
        practical = delta >= self.settings.min_absolute_error_rate_increase
        anomaly = p_value < self.settings.anomaly_alpha and practical and delta > 0
        reason = "ANOMALY_CONFIRMED" if anomaly else (
            "PRACTICAL_EFFECT_NOT_MET" if not practical else "NOT_STATISTICALLY_SIGNIFICANT"
        )
        return DetectionEvaluation(
            **base,
            evaluated=True,
            is_anomaly=anomaly,
            current_attempts=current.total_attempts,
            current_errors=current.technical_error_count,
            baseline_attempts=baseline.total_attempts,
            baseline_errors=baseline.technical_error_count,
            current_value=current_rate,
            baseline_value=baseline_rate,
            absolute_increase=delta,
            z_statistic=z_statistic,
            p_value=p_value,
            practical_effect_met=practical,
            reason_code=reason,
        )

    def evaluate_latency(
        self, snapshot: MetricSnapshot, scope: str = "GLOBAL"
    ) -> DetectionEvaluation:
        current = snapshot.current
        baseline = snapshot.baseline
        base = self._base(snapshot, "p95_authorization_latency", scope)
        current_p95 = current.p95_authorization_latency_ms
        baseline_p95 = baseline.p95_authorization_latency_ms
        if snapshot.telemetry_state is not TelemetryState.HEALTHY:
            return self._unevaluated(base, snapshot, f"TELEMETRY_{snapshot.telemetry_state.value}")
        if current_p95 is None or baseline_p95 is None or baseline_p95 <= 0:
            return self._unevaluated(base, snapshot, "INSUFFICIENT_LATENCY_DATA")
        delta = current_p95 - baseline_p95
        relative = delta / baseline_p95
        practical = (
            delta >= self.settings.latency_min_absolute_increase_ms
            and relative >= self.settings.latency_min_relative_increase
        )
        return DetectionEvaluation(
            **base,
            evaluated=True,
            is_anomaly=practical,
            current_attempts=current.total_attempts,
            current_errors=0,
            baseline_attempts=baseline.total_attempts,
            baseline_errors=0,
            current_value=current_p95,
            baseline_value=baseline_p95,
            absolute_increase=delta,
            z_statistic=None,
            p_value=None,
            practical_effect_met=practical,
            reason_code="LATENCY_DEGRADED" if practical else "LATENCY_WITHIN_RANGE",
        )

    @staticmethod
    def _base(snapshot: MetricSnapshot, metric_family: str, scope: str) -> dict[str, object]:
        return {
            "evaluation_id": (
                f"eval:{metric_family}:{scope}:{snapshot.snapshot_version}:"
                f"{snapshot.bucket_evidence_end_at.isoformat()}"
            ),
            "snapshot_version": snapshot.snapshot_version,
            "configuration_version": snapshot.configuration_version,
            "evaluated_at": snapshot.generated_at,
            "bucket_evidence_end_at": snapshot.bucket_evidence_end_at,
            "metric_family": metric_family,
            "scope": scope,
            "telemetry_state": snapshot.telemetry_state,
        }

    @staticmethod
    def _unevaluated(
        base: dict[str, object], snapshot: MetricSnapshot, reason: str
    ) -> DetectionEvaluation:
        current = snapshot.current
        baseline = snapshot.baseline
        return DetectionEvaluation(
            **base,
            evaluated=False,
            is_anomaly=False,
            current_attempts=current.total_attempts,
            current_errors=current.technical_error_count,
            baseline_attempts=baseline.total_attempts,
            baseline_errors=baseline.technical_error_count,
            current_value=current.technical_error_rate,
            baseline_value=baseline.technical_error_rate,
            absolute_increase=None,
            z_statistic=None,
            p_value=None,
            practical_effect_met=False,
            reason_code=reason,
        )
