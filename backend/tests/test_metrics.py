"""Event-time aggregation specifications for Stage 3."""

from datetime import UTC, datetime, timedelta

from backend.config.settings import Settings
from backend.contracts.enums import PaymentOutcome, TelemetryState
from backend.metrics.aggregator import EventTimeAggregator, IngestDisposition
from simulator.payment_events.generator import PaymentEventGenerator


def _events(count: int, at: datetime, seed: int = 11):
    return PaymentEventGenerator(seed=seed).generate_batch(count, at)


def test_counts_are_conserved_and_outcomes_remain_separate() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        min_current_attempts=1,
        min_baseline_attempts=1,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    boundary = datetime(2026, 8, 27, 6, 2, tzinfo=UTC)
    events = _events(200, boundary - timedelta(seconds=15))
    for event in events:
        aggregator.ingest(event)

    snapshot = aggregator.snapshot(boundary)
    current = snapshot.current
    assert current.total_attempts == len(events)
    assert (
        current.approved_count
        + current.business_decline_count
        + current.technical_error_count
        == current.total_attempts
    )
    assert abs(
        current.approval_rate + current.business_decline_rate + current.technical_error_rate - 1
    ) < 1e-12


def test_event_time_assignment_and_late_event_policy_are_explicit() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        allowed_lateness_seconds=5,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    base = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    newer, within_lateness, too_late = (
        _events(1, base + timedelta(seconds=20), seed=1)[0],
        _events(1, base + timedelta(seconds=16), seed=2)[0],
        _events(1, base + timedelta(seconds=14), seed=3)[0],
    )

    assert aggregator.ingest(newer) is IngestDisposition.ACCEPTED
    assert aggregator.ingest(within_lateness) is IngestDisposition.ACCEPTED_LATE
    assert aggregator.ingest(too_late) is IngestDisposition.DROPPED_TOO_LATE
    assert aggregator.bucket_start_for(newer.occurred_at) == base + timedelta(seconds=20)
    assert aggregator.bucket_start_for(within_lateness.occurred_at) == base + timedelta(seconds=10)
    assert aggregator.late_event_count == 1


def test_window_p95_uses_merged_observations_not_average_of_bucket_percentiles() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        min_current_attempts=1,
        min_baseline_attempts=1,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    boundary = datetime(2026, 8, 27, 6, 1, tzinfo=UTC)
    first = _events(20, boundary - timedelta(seconds=19), seed=4)
    second = _events(20, boundary - timedelta(seconds=9), seed=5)
    for index, event in enumerate(first):
        event.authorization_latency_ms = 1 if index < 19 else 100
        aggregator.ingest(event)
    for event in second:
        event.authorization_latency_ms = 50
        aggregator.ingest(event)

    snapshot = aggregator.snapshot(boundary)
    assert snapshot.current.p95_authorization_latency_ms == 50


def test_healthy_prewarm_becomes_baseline_ready_through_normal_aggregation() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        min_current_attempts=20,
        min_baseline_attempts=100,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    now = datetime(2026, 8, 27, 6, 2, tzinfo=UTC)
    prewarm = _events(140, now - timedelta(seconds=80), seed=20260827)
    live = _events(40, now - timedelta(seconds=15), seed=20260828)
    for event in prewarm + live:
        aggregator.ingest(event)

    snapshot = aggregator.snapshot(now)
    assert snapshot.telemetry_state is TelemetryState.HEALTHY
    assert snapshot.baseline_ready
    assert snapshot.baseline.total_attempts >= 100
    assert snapshot.current.total_attempts == 40


def test_missing_telemetry_is_unknown_not_a_healthy_zero() -> None:
    aggregator = EventTimeAggregator(Settings())
    snapshot = aggregator.snapshot(datetime(2026, 8, 27, 6, 2, tzinfo=UTC))
    assert snapshot.telemetry_state is TelemetryState.UNKNOWN
    assert snapshot.current.technical_error_rate is None
    assert snapshot.current.unavailable_reason == "no telemetry in window"


def test_dimensional_rollups_conserve_attempts_and_observed_combinations_only() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        min_current_attempts=1,
        min_baseline_attempts=1,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    boundary = datetime(2026, 8, 27, 6, 2, tzinfo=UTC)
    events = _events(100, boundary - timedelta(seconds=15))
    for event in events:
        aggregator.ingest(event)

    current = aggregator.snapshot(boundary).current
    assert sum(value.total_attempts for value in current.dimensions["processing_region"].values()) == 100
    assert sum(value.total_attempts for value in current.combinations.values()) == 100
    assert all(value.total_attempts > 0 for value in current.combinations.values())


def test_snapshots_and_history_are_versioned_at_authoritative_resolution() -> None:
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=20,
        baseline_window_seconds=60,
        min_current_attempts=1,
        min_baseline_attempts=1,
        baseline_required_samples=100,
    )
    aggregator = EventTimeAggregator(settings)
    boundary = datetime(2026, 8, 27, 6, 2, tzinfo=UTC)
    for event in _events(120, boundary - timedelta(seconds=70), seed=44):
        aggregator.ingest(event)
    for event in _events(40, boundary - timedelta(seconds=15), seed=45):
        aggregator.ingest(event)
    first = aggregator.snapshot(boundary)
    second = aggregator.snapshot(boundary + timedelta(seconds=10))

    history = aggregator.history(
        "technical_error_rate", boundary, boundary + timedelta(seconds=10)
    )
    assert (first.snapshot_version, second.snapshot_version) == (1, 2)
    assert history.resolution_seconds == 10
    assert [point.at for point in history.points] == [boundary, boundary + timedelta(seconds=10)]
