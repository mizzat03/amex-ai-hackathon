"""Canonical evidence, provenance, runbook, and persistence specifications."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.anomaly_detection.detector import TechnicalErrorDetector
from backend.contracts.enums import EvidenceCompleteness
from backend.dimensional_analysis.analyzer import DimensionalAnalyzer
from backend.evidence.builder import (
    EvidenceBuilder,
    EvidencePackage,
    IncidentEvidenceInput,
    UnsafeEvidencePackage,
)
from backend.evidence.runbooks import RunbookRepository
from backend.persistence.evidence_repository import PostgresEvidencePackageRepository
from backend.root_cause.engine import RootCauseEngine
from backend.tests.test_dimensional_analysis import _primary_snapshot
from simulator.operational_events.generator import deployment_event


def _inputs(incident_id: str = "inc_primary"):
    settings, snapshot = _primary_snapshot()
    analysis = DimensionalAnalyzer(settings).analyze(incident_id, snapshot, 1)
    incident_start = datetime(2026, 8, 27, 6, 5, tzinfo=UTC)
    operation = deployment_event(incident_start - timedelta(seconds=45))
    rca = RootCauseEngine(settings).run(incident_id, incident_start, analysis, [operation])
    anomaly = TechnicalErrorDetector(settings).evaluate(snapshot)
    incident = IncidentEvidenceInput(
        incident_id=incident_id,
        lifecycle="OPEN",
        severity="HIGH",
        started_at=incident_start,
        updated_at=snapshot.generated_at,
    )
    return settings, incident, anomaly, analysis, rca


def test_canonical_package_resolves_every_hypothesis_relation_and_projection_citation() -> None:
    settings, incident, anomaly, analysis, rca = _inputs()
    builder = EvidenceBuilder(settings)
    package = builder.build(incident, anomaly, analysis, rca)
    assert package.completeness is EvidenceCompleteness.COMPLETE

    evidence_ids = {item.evidence_id for item in package.evidence_catalogue}
    assert evidence_ids
    for hypothesis in package.hypotheses:
        assert set(hypothesis.supporting) <= evidence_ids
        assert set(hypothesis.contradictory) <= evidence_ids
        assert set(hypothesis.missing) <= evidence_ids
        assert set(hypothesis.not_applicable) <= evidence_ids

    dashboard = builder.dashboard_projection(package)
    assert {ref.evidence_id for ref in dashboard.citation_allowlist if ref.citation_type == "EVIDENCE"} == evidence_ids
    assert dashboard.incident_id == incident.incident_id
    copilot = builder.copilot_projection(package)
    assert copilot.leading_hypothesis_id == rca.leading_hypothesis.hypothesis_id
    assert copilot.evidence_tier == rca.leading_hypothesis.evidence_tier


def test_package_creation_is_idempotent_immutable_and_new_inputs_create_new_version() -> None:
    settings, incident, anomaly, analysis, rca = _inputs()
    builder = EvidenceBuilder(settings)
    first = builder.build(incident, anomaly, analysis, rca)
    replay = builder.build(incident, anomaly, analysis, rca)
    assert replay is first
    with pytest.raises(ValidationError):
        first.package_version = 99

    rca.result_version += 1
    second = builder.build(incident, anomaly, analysis, rca)
    assert second.package_version == first.package_version + 1
    assert second.evidence_package_id == first.evidence_package_id
    assert first.package_version == 1


def test_partial_package_preserves_limitations_and_invalid_package_is_blocked() -> None:
    settings, incident, anomaly, analysis, rca = _inputs()
    builder = EvidenceBuilder(settings)
    partial = builder.build(
        incident,
        anomaly,
        analysis,
        rca,
        optional_missing=["Dependency health telemetry is unavailable for this synthetic scenario."],
    )
    assert partial.completeness is EvidenceCompleteness.PARTIAL
    assert partial.package_limitations
    assert builder.copilot_projection(partial).limitations == partial.package_limitations

    rca.incident_id = "inc_other"
    invalid = builder.build(incident, anomaly, analysis, rca)
    assert invalid.completeness is EvidenceCompleteness.INVALID
    with pytest.raises(UnsafeEvidencePackage):
        builder.dashboard_projection(invalid)
    with pytest.raises(UnsafeEvidencePackage):
        builder.copilot_projection(invalid)
    fallback = builder.deterministic_fallback_projection(invalid)
    assert fallback["incident_id"] == incident.incident_id
    assert fallback["ai_available"] is False


def test_provenance_contains_source_version_rule_version_and_lineage() -> None:
    settings, incident, anomaly, analysis, rca = _inputs()
    package = EvidenceBuilder(settings).build(incident, anomaly, analysis, rca)
    assert all(item.provenance.source_module for item in package.evidence_catalogue)
    assert all(item.provenance.source_version for item in package.evidence_catalogue)
    assert all(item.provenance.rule_version for item in package.evidence_catalogue)
    assert all(item.provenance.calculation_lineage for item in package.evidence_catalogue)


def test_versioned_runbook_citations_resolve_as_guidance_not_incident_proof() -> None:
    repository = RunbookRepository.from_directory("runbooks")
    matches = repository.search(tags={"token-validation"}, limit=2)
    assert matches
    citation = matches[0].citation
    resolved = repository.resolve(citation)
    assert resolved.citation.runbook_version == citation.runbook_version
    assert resolved.guidance_not_incident_proof
    assert resolved.approved_guidance_excerpt


def test_postgres_migration_uses_jsonb_with_indexed_package_metadata() -> None:
    migration = Path("backend/persistence/migrations/001_evidence_packages.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "jsonb" in migration
    assert "create unique index" in migration
    assert "incident_id" in migration
    assert "package_version" in migration


def test_evidence_repository_reads_exact_and_latest_eligible_immutable_packages() -> None:
    settings, incident, anomaly, analysis, rca = _inputs()
    builder = EvidenceBuilder(settings)
    first = builder.build(incident, anomaly, analysis, rca)
    rca.result_version += 1
    latest = builder.build(incident, anomaly, analysis, rca)

    class FakeConnection:
        def __init__(self, packages: list[EvidencePackage]) -> None:
            self.packages = packages
            self.queries: list[tuple[str, tuple[object, ...]]] = []

        async def execute(self, query: str, *args: object) -> str:
            self.queries.append((query, args))
            return "INSERT 0 1"

        async def fetchrow(self, query: str, *args: object):
            self.queries.append((query, args))
            if "evidence_package_id = $2" in query:
                incident_id, package_id, version = args
                package = next(
                    (
                        item
                        for item in self.packages
                        if item.incident_id == incident_id
                        and item.evidence_package_id == package_id
                        and item.package_version == version
                    ),
                    None,
                )
            else:
                incident_id, completeness = args
                package = next(
                    (
                        item
                        for item in reversed(self.packages)
                        if item.incident_id == incident_id
                        and item.completeness.value in completeness
                    ),
                    None,
                )
            return {"package_json": package.model_dump(mode="json")} if package else None

    connection = FakeConnection([first, latest])
    repository = PostgresEvidencePackageRepository(connection)

    exact = asyncio.run(
        repository.get_exact(first.incident_id, first.evidence_package_id, first.package_version)
    )
    selected = asyncio.run(repository.latest_eligible(first.incident_id))

    assert exact == first
    assert selected == latest
    assert exact is not selected
    assert any("ORDER BY package_version DESC" in query for query, _ in connection.queries)
