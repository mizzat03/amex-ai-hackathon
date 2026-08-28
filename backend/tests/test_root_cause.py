"""Observed-change-only deterministic RCA and human-review specifications."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.contracts.enums import EvidenceTier
from backend.contracts.events import OperationalEvent
from backend.dimensional_analysis.analyzer import DimensionalAnalyzer
from backend.root_cause.engine import RootCauseEngine
from backend.root_cause.review import HumanReviewStore, VersionConflict
from backend.tests.test_dimensional_analysis import _primary_snapshot
from simulator.operational_events.generator import deployment_event, rollback_event


def _analysis():
    settings, snapshot = _primary_snapshot()
    return settings, DimensionalAnalyzer(settings).analyze("inc_primary", snapshot, 1)


def test_primary_deployment_is_qualified_leader_with_alternatives_and_no_probability() -> None:
    settings, analysis = _analysis()
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)
    deployment = deployment_event(incident_start - timedelta(seconds=45))
    alternative = OperationalEvent.model_validate(
        deployment.model_dump()
        | {
            "event_id": "2f7b32d5-7713-5c72-a09b-19b5f993a0c1",
            "affected_service": "TOKEN_SERVICE",
            "component": "token-keys",
            "previous_version": "v1.8.0",
            "new_version": "v1.8.1",
            "change_categories": [],
            "correlation_id": "deploy-token-service",
        }
    )
    result = RootCauseEngine(settings).run(
        "inc_primary", incident_start, analysis, [deployment, alternative]
    )

    assert result.leading_hypothesis is not None
    assert result.leading_hypothesis.operational_event_id == str(deployment.event_id)
    assert result.leading_hypothesis.evidence_tier in {
        EvidenceTier.MODERATE_EVIDENCE,
        EvidenceTier.STRONG_EVIDENCE,
    }
    assert len(result.candidates) == 2
    assert result.leading_hypothesis.supporting
    assert result.leading_hypothesis.not_applicable == []
    serialized = repr(result).lower()
    assert "probability" not in serialized
    assert "confidence_percent" not in serialized


def test_no_eligible_observed_change_returns_insufficient_evidence() -> None:
    settings, analysis = _analysis()
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)
    result = RootCauseEngine(settings).run("inc_none", incident_start, analysis, [])
    assert result.overall_tier is EvidenceTier.INSUFFICIENT_EVIDENCE
    assert result.leading_hypothesis is None
    assert result.candidates == []


def test_missing_affected_scope_is_unknown_not_a_hard_contradiction() -> None:
    settings, analysis = _analysis()
    analysis = replace(analysis, best_affected_scope=None)
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)

    result = RootCauseEngine(settings).run(
        "inc_missing_scope",
        incident_start,
        analysis,
        [deployment_event(incident_start - timedelta(seconds=45))],
    )

    assert result.rejected_events == []
    assert result.leading_hypothesis is not None
    assert result.leading_hypothesis.scope_alignment.value == "UNKNOWN"


def test_hard_temporal_and_scope_contradictions_cannot_lead() -> None:
    settings, analysis = _analysis()
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)
    after_incident = deployment_event(incident_start + timedelta(minutes=2))
    original = deployment_event(incident_start - timedelta(minutes=1))
    disjoint = OperationalEvent.model_validate(
        original.model_dump()
        | {
            "event_id": "ab5c03b2-603e-5f43-a830-dcb9f4e84c71",
            "affected_regions": ["US"],
            "affected_payment_methods": ["CARD"],
            "correlation_id": "disjoint-change",
        }
    )
    result = RootCauseEngine(settings).run(
        "inc_contradiction", incident_start, analysis, [after_incident, disjoint]
    )
    assert result.leading_hypothesis is None
    assert result.overall_tier is EvidenceTier.INSUFFICIENT_EVIDENCE
    assert len(result.rejected_events) == 2
    assert all(item.hard_contradiction for item in result.rejected_events)


def test_rerun_is_idempotent_and_later_rollback_recovery_strengthens_new_version() -> None:
    settings, analysis = _analysis()
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)
    deployment = deployment_event(incident_start - timedelta(seconds=45))
    engine = RootCauseEngine(settings)
    first = engine.run("inc_primary", incident_start, analysis, [deployment])
    replay = engine.run("inc_primary", incident_start, analysis, [deployment])
    assert replay is first

    rollback = rollback_event(incident_start + timedelta(minutes=4))
    rerun = engine.run(
        "inc_primary",
        incident_start,
        analysis,
        [deployment, rollback],
        recovery_confirmed=True,
    )
    assert rerun.result_version == first.result_version + 1
    assert rerun.leading_hypothesis is not None
    assert any(
        item.code == "ROLLBACK_RECOVERY_SUPPORT" for item in rerun.leading_hypothesis.supporting
    )


def test_human_review_is_separate_note_validated_and_optimistically_versioned() -> None:
    store = HumanReviewStore()
    review = store.put(
        incident_id="inc_primary",
        hypothesis_id="hyp_1",
        status="ACKNOWLEDGED",
        note=None,
        expected_version=1,
    )
    assert review.version == 2
    assert review.reviewed_by == "demo-operator"

    with pytest.raises(VersionConflict):
        store.put("inc_primary", "hyp_1", "ACKNOWLEDGED", None, expected_version=1)
    with pytest.raises(ValueError):
        store.put("inc_primary", "hyp_1", "REJECTED", "  ", expected_version=2)

    rejected = store.put(
        "inc_primary", "hyp_1", "REJECTED", "Deployment owner disproved linkage", 2
    )
    assert rejected.version == 3
    assert rejected.note == "Deployment owner disproved linkage"
