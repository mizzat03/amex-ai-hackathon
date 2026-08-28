"""Statistical detector and incident lifecycle specifications."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from backend.anomaly_detection.detector import TechnicalErrorDetector
from backend.anomaly_detection.lifecycle import IncidentLifecycleManager
from backend.config.settings import Settings
from backend.contracts.enums import IncidentLifecycle, TelemetryState
from backend.metrics.aggregator import MetricSnapshot, WindowAggregate


def _snapshot(
    version: int,
    evidence_end: datetime,
    current_attempts: int,
    current_errors: int,
    baseline_attempts: int = 2000,
    baseline_errors: int = 10,
    current_p95: float = 90,
    baseline_p95: float = 80,
    state: TelemetryState = TelemetryState.HEALTHY,
) -> MetricSnapshot:
    current = WindowAggregate(
        total_attempts=current_attempts,
        approved_count=current_attempts - current_errors,
        technical_error_count=current_errors,
        latency_observations_ms=[current_p95] * current_attempts,
        start_at=evidence_end - timedelta(seconds=60),
        end_at=evidence_end,
        duration_seconds=60,
    )
    baseline = WindowAggregate(
        total_attempts=baseline_attempts,
        approved_count=baseline_attempts - baseline_errors,
        technical_error_count=baseline_errors,
        latency_observations_ms=[baseline_p95] * baseline_attempts,
        start_at=evidence_end - timedelta(seconds=360),
        end_at=evidence_end - timedelta(seconds=60),
        duration_seconds=300,
    )
    return MetricSnapshot(
        snapshot_version=version,
        generated_at=evidence_end,
        configuration_version="demo-config.v1",
        bucket_evidence_end_at=evidence_end,
        telemetry_state=state,
        baseline_ready=state is TelemetryState.HEALTHY,
        current=current,
        baseline=baseline,
        late_event_count=0,
    )


def test_healthy_traffic_does_not_create_false_incident() -> None:
    settings = Settings(min_current_attempts=100, min_baseline_attempts=500)
    detector = TechnicalErrorDetector(settings)
    manager = IncidentLifecycleManager(settings)
    at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    for version in range(1, 8):
        result = detector.evaluate(_snapshot(version, at + timedelta(seconds=10 * version), 500, 3))
        transition = manager.apply(result)
        assert not result.is_anomaly
        assert transition.lifecycle is IncidentLifecycle.HEALTHY
        assert transition.incident is None


def test_regression_advances_suspected_then_open_only_on_fresh_bucket_evidence() -> None:
    settings = Settings(
        min_current_attempts=100,
        min_baseline_attempts=500,
        min_current_technical_errors=8,
        detection_persistence_buckets=2,
    )
    detector = TechnicalErrorDetector(settings)
    manager = IncidentLifecycleManager(settings)
    at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    first = detector.evaluate(_snapshot(1, at, 500, 75))
    assert first.is_anomaly and first.p_value < settings.anomaly_alpha
    suspected = manager.apply(first)
    assert suspected.lifecycle is IncidentLifecycle.SUSPECTED

    duplicate = manager.apply(first)
    assert duplicate.lifecycle is IncidentLifecycle.SUSPECTED
    assert duplicate.incident is None

    second = detector.evaluate(_snapshot(2, at + timedelta(seconds=10), 500, 80))
    opened = manager.apply(second)
    assert opened.lifecycle is IncidentLifecycle.OPEN
    assert opened.incident is not None
    assert opened.incident.severity.value in {"MEDIUM", "HIGH"}


def test_improvement_alone_does_not_resolve_and_recovery_requires_stronger_persistence() -> None:
    settings = Settings(
        min_current_attempts=100,
        min_baseline_attempts=500,
        detection_persistence_buckets=2,
        recovery_persistence_buckets=4,
    )
    detector = TechnicalErrorDetector(settings)
    manager = IncidentLifecycleManager(settings)
    at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    manager.apply(detector.evaluate(_snapshot(1, at, 500, 80)))
    manager.apply(detector.evaluate(_snapshot(2, at + timedelta(seconds=10), 500, 85)))

    improved_but_unsafe = detector.evaluate(
        _snapshot(3, at + timedelta(seconds=20), 500, 20)
    )
    still_open = manager.apply(improved_but_unsafe)
    assert still_open.lifecycle is IncidentLifecycle.OPEN

    for offset in range(4):
        recovery = detector.evaluate(
            _snapshot(4 + offset, at + timedelta(seconds=30 + offset * 10), 1000, 5)
        )
        transition = manager.apply(recovery)
        expected = (
            IncidentLifecycle.RESOLVED
            if offset == 3
            else IncidentLifecycle.RECOVERY_CANDIDATE
        )
        assert transition.lifecycle is expected


def test_warming_stale_and_unknown_snapshots_never_become_healthy_zeroes() -> None:
    settings = Settings()
    detector = TechnicalErrorDetector(settings)
    at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    for state in (TelemetryState.WARMING_UP, TelemetryState.STALE, TelemetryState.UNKNOWN):
        result = detector.evaluate(_snapshot(1, at, 0, 0, state=state))
        assert not result.evaluated
        assert result.telemetry_state is state
        assert result.reason_code == f"TELEMETRY_{state.value}"


def test_incident_creation_is_idempotent_under_concurrent_duplicate_delivery() -> None:
    settings = Settings(detection_persistence_buckets=1)
    detector = TechnicalErrorDetector(settings)
    manager = IncidentLifecycleManager(settings)
    result = detector.evaluate(
        _snapshot(1, datetime(2026, 8, 27, 6, 0, tzinfo=UTC), 500, 90)
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        transitions = list(pool.map(lambda _: manager.apply(result), range(20)))
    incident_ids = {
        transition.incident.incident_id
        for transition in transitions
        if transition.incident is not None
    }
    assert len(incident_ids) == 1
    assert manager.incident_count == 1


def test_secondary_latency_detector_is_separate_from_error_proportion_rule() -> None:
    settings = Settings(min_current_attempts=100, min_baseline_attempts=500)
    detector = TechnicalErrorDetector(settings)
    result = detector.evaluate_latency(
        _snapshot(1, datetime(2026, 8, 27, 6, 0, tzinfo=UTC), 500, 3, current_p95=220)
    )
    assert result.metric_family == "p95_authorization_latency"
    assert result.is_anomaly
    assert result.p_value is None


def test_manual_closure_requires_reason_and_is_not_statistical_recovery() -> None:
    settings = Settings(detection_persistence_buckets=1)
    detector = TechnicalErrorDetector(settings)
    manager = IncidentLifecycleManager(settings)
    result = detector.evaluate(
        _snapshot(1, datetime(2026, 8, 27, 6, 0, tzinfo=UTC), 500, 90)
    )
    incident = manager.apply(result).incident
    assert incident is not None
    try:
        manager.manual_close(incident.incident_id, "   ")
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("blank manual closure reason should fail")

    closed = manager.manual_close(incident.incident_id, "False positive after maintenance review")
    assert closed.lifecycle is IncidentLifecycle.RESOLVED
    assert closed.closure_mode == "MANUAL"
