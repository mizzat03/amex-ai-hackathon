"""Affected-scope, complement, and dominant-symptom specifications."""

from datetime import UTC, datetime, timedelta

from backend.config.settings import Settings
from backend.dimensional_analysis.analyzer import AnalysisCompleteness, DimensionalAnalyzer
from backend.metrics.aggregator import AggregateCounter, EventTimeAggregator, WindowAggregate
from simulator.payment_events.generator import PaymentEventGenerator


def _primary_snapshot():
    settings = Settings(
        bucket_duration_seconds=10,
        current_window_seconds=60,
        baseline_window_seconds=300,
        allowed_lateness_seconds=15,
        baseline_required_samples=1000,
        min_current_attempts=100,
        min_baseline_attempts=500,
        dimension_min_current_attempts=20,
        dimension_min_baseline_attempts=50,
        dimension_min_current_errors=4,
        dimension_min_excess_errors=2,
        dimension_min_rate_increase=0.02,
        dimension_child_excess_retention=0.50,
        dimension_concentration_improvement=0.05,
    )
    aggregator = EventTimeAggregator(settings)
    now = datetime(2026, 8, 27, 6, 6, tzinfo=UTC)
    baseline = PaymentEventGenerator(seed=100).generate_batch(3000, now - timedelta(seconds=360))
    current = PaymentEventGenerator(seed=101, injected=True).generate_batch(
        1800, now - timedelta(seconds=60)
    )
    for event in baseline + current:
        aggregator.ingest(event)
    return settings, aggregator.snapshot(now)


def test_primary_scenario_finds_triple_scope_and_dominant_symptom_without_causal_claim() -> None:
    settings, snapshot = _primary_snapshot()
    result = DimensionalAnalyzer(settings).analyze("inc_primary", snapshot, analysis_version=1)

    assert result.completeness is AnalysisCompleteness.COMPLETE
    assert result.best_affected_scope is not None
    assert result.best_affected_scope.components == {
        "processing_region": "SG",
        "payment_method": "MOBILE_WALLET",
        "service_version": "v2.4.1",
    }
    assert result.dominant_error_signature is not None
    assert result.dominant_error_signature.normalized_error_code == "TOKEN_VALIDATION_FAILED"
    assert "cause" not in result.best_affected_scope.label.lower()
    assert "cause" not in result.dominant_error_signature.label.lower()


def test_reported_candidates_include_current_complement_comparisons() -> None:
    settings, snapshot = _primary_snapshot()
    result = DimensionalAnalyzer(settings).analyze("inc_primary", snapshot, analysis_version=1)
    assert result.best_affected_scope is not None
    scope = result.best_affected_scope
    assert scope.complement_attempts > 0
    assert scope.complement_technical_error_rate is not None
    assert scope.technical_error_rate > scope.complement_technical_error_rate
    assert scope.complement_interpretation == "CONCENTRATED"


def test_low_volume_perfect_correlation_is_rejected_with_visible_caveat() -> None:
    settings = Settings(
        dimension_min_current_attempts=30,
        dimension_min_baseline_attempts=100,
        dimension_min_current_errors=5,
    )
    current = WindowAggregate(
        total_attempts=1000,
        approved_count=998,
        technical_error_count=2,
        start_at=datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 27, 6, 1, tzinfo=UTC),
        duration_seconds=60,
    )
    baseline = WindowAggregate(
        total_attempts=5000,
        approved_count=5000,
        start_at=datetime(2026, 8, 27, 5, 55, tzinfo=UTC),
        end_at=datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
        duration_seconds=300,
    )
    tiny_current = AggregateCounter(total_attempts=2, technical_error_count=2)
    tiny_baseline = AggregateCounter(total_attempts=1)
    current.dimensions["service_version"]["v9.9.9"] = tiny_current
    baseline.dimensions["service_version"]["v9.9.9"] = tiny_baseline

    result = DimensionalAnalyzer(settings).analyze_windows(
        "inc_tiny", current, baseline, analysis_version=1
    )
    rejected = [item for item in result.rejected_candidates if "v9.9.9" in item.label]
    assert rejected
    assert "MIN_CURRENT_ATTEMPTS" in rejected[0].rejection_reasons
    assert "MIN_BASELINE_ATTEMPTS" in rejected[0].rejection_reasons
    assert any("low-volume" in caveat.lower() for caveat in result.caveats)


def test_missing_combination_rollups_produce_incomplete_not_unaffected() -> None:
    settings, snapshot = _primary_snapshot()
    snapshot.current.combinations.clear()
    result = DimensionalAnalyzer(settings).analyze("inc_missing", snapshot, analysis_version=1)
    assert result.completeness is AnalysisCompleteness.INCOMPLETE
    assert any("combination" in caveat.lower() for caveat in result.caveats)
