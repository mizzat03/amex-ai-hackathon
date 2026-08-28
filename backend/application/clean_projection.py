"""Typed projections for a fresh or fully reset synthetic runtime."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.config.settings import Settings
from backend.contracts.api import (
    BaselineStatus,
    DetectorSummary,
    MetricHistoryResponse,
    MetricValue,
    OverviewMetrics,
    Period,
    PunchlineMetric,
    SimulationStatus,
    SystemOverviewResponse,
)
from backend.contracts.enums import MetricKey

_NO_TELEMETRY = "No telemetry yet"


def _unavailable(unit: str) -> MetricValue:
    return MetricValue.model_validate(
        {
            "value": None,
            "unit": unit,
            "unavailable_reason": _NO_TELEMETRY,
        }
    )


@dataclass(frozen=True)
class CleanProjection:
    overview: SystemOverviewResponse
    history: MetricHistoryResponse
    simulation: SimulationStatus


def build_clean_projection(
    now: datetime | None = None, settings: Settings | None = None
) -> CleanProjection:
    """Return the minimum honest state needed by the live API on first run."""
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    rate = _unavailable("RATE")
    metrics = OverviewMetrics(
        approval_rate=_unavailable("RATE"),
        business_decline_rate=_unavailable("RATE"),
        technical_error_rate=rate,
        throughput=_unavailable("ATTEMPTS_PER_SECOND"),
        average_authorization_latency=_unavailable("MILLISECONDS"),
        p95_authorization_latency=_unavailable("MILLISECONDS"),
    )
    overview = SystemOverviewResponse(
        generated_at=generated_at,
        latest_sample_at=None,
        telemetry_stale_after_seconds=(settings.telemetry_stale_after_seconds if settings else 30),
        telemetry_state="UNKNOWN",
        baseline=BaselineStatus(
            ready=False,
            progress=0,
            current_samples=0,
            required_samples=settings.baseline_required_samples if settings else 1,
            unavailable_reason=_NO_TELEMETRY,
        ),
        metrics=metrics,
        punchline_metric=PunchlineMetric(
            label="Technical error rate",
            metric=rate,
            supporting_count=_unavailable("COUNT"),
        ),
        active_incident_count=0,
        active_incidents=[],
        detector_summary=DetectorSummary(
            global_technical_error_state="WARMING_UP",
            latency_state="WARMING_UP",
        ),
    )
    history = MetricHistoryResponse(
        metric_key=MetricKey.TECHNICAL_ERROR_RATE,
        unit="RATE",
        period=Period(start_at=generated_at - timedelta(minutes=1), end_at=generated_at),
        resolution_seconds=settings.bucket_duration_seconds if settings else 60,
        points=[],
        events=[],
    )
    simulation = SimulationStatus(
        state="STOPPED",
        baseline_ready=False,
        available_actions=["START", "RESET"],
        message="No telemetry yet. Start healthy traffic to warm the baseline.",
    )
    return CleanProjection(overview=overview, history=history, simulation=simulation)
