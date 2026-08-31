"""Deterministic schema, grounding, numerical, citation, and policy validation."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.copilot.models import (
    CopilotContext,
    CopilotDraft,
    DraftEvidencePoint,
    confidence_for_evidence_tier,
)
from backend.contracts.api import (
    CitationRef,
    CopilotAnswerContent,
    CopilotCitationTechnicalDetails,
    CopilotEvidenceCitation,
    CopilotEvidencePoint,
    CopilotRecommendedCheck,
    CopilotRunbookCitation,
)


class CopilotValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


_PROHIBITED = (
    re.compile(r"\b\d+(?:\.\d+)?%\s+(?:causal\s+)?confidence\b", re.IGNORECASE),
    re.compile(r"\b(?:i|we|the system)\s+(?:executed|deployed|restarted|rolled back|remediated)\b", re.IGNORECASE),
    re.compile(r"\b(?:automatically|already)\s+(?:executed|rolled back|remediated)\b", re.IGNORECASE),
)
_NUMBER = re.compile(r"(?<![\w.-])-?\d+(?:\.\d+)?%?")
_SEMVER = re.compile(r"\bv?\d+(?:\.\d+){1,3}\b", re.IGNORECASE)


class CopilotValidator:
    POLICY_VERSION = "copilot-validation.v1"

    def validate(self, raw: dict[str, Any], context: CopilotContext) -> CopilotAnswerContent:
        try:
            draft = CopilotDraft.model_validate(raw)
        except ValidationError as exc:
            raise CopilotValidationError([f"schema:{error['loc']}:{error['msg']}" for error in exc.errors()]) from exc

        errors: list[str] = []
        if draft.incident_id != context.incident_id:
            errors.append("cross-incident output rejected")
        if (
            draft.evidence_package_id != context.evidence_package_id
            or draft.evidence_package_version != context.evidence_package_version
        ):
            errors.append("evidence package ownership/version mismatch")
        if context.evidence_completeness == "INVALID":
            errors.append("invalid evidence packages cannot invoke the copilot")
        if draft.leading_hypothesis_id != context.leading_hypothesis_id:
            errors.append("deterministic leading hypothesis changed")
        if draft.evidence_tier != context.evidence_tier:
            errors.append("deterministic evidence tier changed")
        if draft.mode == "INITIAL_ANALYSIS" and context.strongest_alternative_id:
            if draft.strongest_alternative_id != context.strongest_alternative_id:
                errors.append("strongest alternative was omitted or relabelled")

        evidence = {item["evidence_id"]: item for item in context.evidence_items}
        evidence_manifest = {
            (item.get("evidence_id"), item.get("evidence_package_id"), item.get("evidence_package_version"))
            for item in context.citation_manifest
            if item.get("citation_type") == "EVIDENCE"
        }
        runbook_manifest = {
            (
                item.get("runbook_id"),
                item.get("runbook_version"),
                item.get("section_id"),
            )
            for item in context.runbook_sections
        }
        point_groups = (
            draft.supporting_points,
            draft.contradictory_points,
            draft.unknown_points,
        )
        for points in point_groups:
            for point in points:
                self._check_policy(point.text, errors)
                self._check_numbers(point.text, point.numeric_assertions, evidence, errors)
                self._check_citations(
                    point.citations,
                    evidence,
                    evidence_manifest,
                    runbook_manifest,
                    errors,
                    "evidence point",
                )
        for point in (*draft.supporting_points, *draft.contradictory_points):
            if not point.citations:
                errors.append("supporting and contradictory points require citations")

        self._check_policy(draft.headline, errors)
        self._check_policy(draft.direct_answer, errors)
        for recommendation in draft.recommended_checks:
            self._check_policy(
                f"{recommendation.title} {recommendation.rationale} {recommendation.expected_signal}",
                errors,
            )
            if not recommendation.requires_human_approval:
                errors.append("recommended check bypasses human control")
            if not recommendation.citations:
                errors.append("recommended check is uncited")
            self._check_citations(
                recommendation.citations,
                evidence,
                evidence_manifest,
                runbook_manifest,
                errors,
                "recommended check",
            )

        if errors:
            raise CopilotValidationError(sorted(set(errors)))

        citation_numbers: dict[tuple[object, ...], int] = {}
        hydrated: list[CopilotEvidenceCitation | CopilotRunbookCitation] = []
        ordered_citations = [
            citation
            for point in (
                *draft.supporting_points,
                *draft.contradictory_points,
                *draft.unknown_points,
            )
            for citation in point.citations
        ]
        ordered_citations.extend(
            citation
            for recommendation in draft.recommended_checks
            for citation in recommendation.citations
        )
        for citation in ordered_citations:
            key = self._citation_key(citation)
            if key in citation_numbers:
                continue
            number = len(citation_numbers) + 1
            citation_numbers[key] = number
            if citation.citation_type == "EVIDENCE":
                item = evidence[citation.evidence_id]
                hydrated.append(
                    CopilotEvidenceCitation(
                        citation_number=number,
                        statement=str(item["statement"]),
                        structured_value=item.get("structured_value"),
                        unit=item.get("unit"),
                        scope=item.get("scope"),
                        period=item.get("period"),
                        temporal_scope=item.get("temporal_scope", "INCIDENT_SNAPSHOT"),
                        provenance_label=str(
                            item.get("provenance_label", "Validated incident evidence")
                        ),
                        evidence_package_id=context.evidence_package_id,
                        evidence_package_version=context.evidence_package_version,
                        technical_details=CopilotCitationTechnicalDetails(
                            evidence_id=citation.evidence_id,
                            source_module=item.get("source_module"),
                            source_version=item.get("source_version"),
                            calculation_method=item.get("calculation_method"),
                            calculation_lineage=list(item.get("calculation_lineage", [])),
                            source_references=list(item.get("source_references", [])),
                        ),
                    )
                )
            else:
                section = next(
                    item
                    for item in context.runbook_sections
                    if (
                        item.get("runbook_id"),
                        item.get("runbook_version"),
                        item.get("section_id"),
                    )
                    == key[1:]
                )
                hydrated.append(
                    CopilotRunbookCitation(
                        citation_number=number,
                        title=str(section.get("section_title", citation.section_id)),
                        approved_guidance_excerpt=str(
                            section.get(
                                "approved_guidance_excerpt",
                                "Approved runbook guidance is available for human review.",
                            )
                        ),
                        runbook_id=citation.runbook_id,
                        runbook_version=citation.runbook_version,
                        section_id=citation.section_id,
                    )
                )

        def present(points: list[DraftEvidencePoint]) -> list[CopilotEvidencePoint]:
            return [
                CopilotEvidencePoint(
                    text=point.text,
                    citation_numbers=[
                        citation_numbers[self._citation_key(citation)]
                        for citation in point.citations
                    ],
                )
                for point in points
            ]

        return CopilotAnswerContent(
            answer_kind=(
                "initial_report" if draft.mode == "INITIAL_ANALYSIS" else "follow_up"
            ),
            headline=draft.headline,
            direct_answer=draft.direct_answer,
            confidence=confidence_for_evidence_tier(context.evidence_tier),
            supporting_points=present(draft.supporting_points),
            contradictory_points=present(draft.contradictory_points),
            unknown_points=present(draft.unknown_points),
            recommended_checks=[
                CopilotRecommendedCheck(
                    title=item.title,
                    rationale=item.rationale,
                    expected_signal=item.expected_signal,
                    risk=item.risk,
                    citation_numbers=[
                        citation_numbers[self._citation_key(citation)]
                        for citation in item.citations
                    ],
                )
                for item in draft.recommended_checks
            ],
            citations=hydrated,
            suggested_questions=draft.suggested_questions,
        )

    @staticmethod
    def _citation_key(citation: CitationRef) -> tuple[object, ...]:
        if citation.citation_type == "EVIDENCE":
            return (
                "EVIDENCE",
                citation.evidence_id,
                citation.evidence_package_id,
                citation.evidence_package_version,
            )
        return (
            "RUNBOOK",
            citation.runbook_id,
            citation.runbook_version,
            citation.section_id,
        )

    @staticmethod
    def _check_citations(
        citations: list[CitationRef],
        evidence: dict[str, dict[str, Any]],
        evidence_manifest: set[tuple[Any, Any, Any]],
        runbook_manifest: set[tuple[Any, Any, Any]],
        errors: list[str],
        label: str,
    ) -> None:
        for citation in citations:
                payload = citation.model_dump(mode="json")
                if payload["citation_type"] == "EVIDENCE":
                    key = (
                        payload["evidence_id"],
                        payload["evidence_package_id"],
                        payload["evidence_package_version"],
                    )
                    if key not in evidence_manifest or payload["evidence_id"] not in evidence:
                        errors.append(f"unauthorised evidence citation in {label}")
                else:
                    key = (payload["runbook_id"], payload["runbook_version"], payload["section_id"])
                    if key not in runbook_manifest:
                        errors.append(f"unauthorised runbook citation in {label}")

    @staticmethod
    def _check_policy(text: str, errors: list[str]) -> None:
        if any(pattern.search(text) for pattern in _PROHIBITED):
            errors.append("prohibited confidence or operational-execution claim")

    @staticmethod
    def _check_numbers(
        text: str,
        assertions: list[Any],
        evidence: dict[str, dict[str, Any]],
        errors: list[str],
    ) -> None:
        checked: list[float] = []
        for assertion in assertions:
            item = evidence.get(assertion.evidence_id)
            if item is None:
                errors.append(f"numeric assertion cites unknown evidence: {assertion.evidence_id}")
                continue
            value: Any = item.get("structured_value")
            for part in assertion.field_path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"numeric assertion field does not resolve: {assertion.field_path}")
                continue
            if not math.isclose(float(value), assertion.value, rel_tol=1e-6, abs_tol=1e-9):
                errors.append(f"fabricated numerical value for {assertion.evidence_id}:{assertion.field_path}")
                continue
            checked.append(float(value))

        scrubbed = _SEMVER.sub("", text)
        textual = [token for token in _NUMBER.findall(scrubbed)]
        for token in textual:
            number = float(token.rstrip("%"))
            candidates = [value * 100 if token.endswith("%") else value for value in checked]
            if not any(math.isclose(number, candidate, rel_tol=0, abs_tol=0.051) for candidate in candidates):
                errors.append(f"unverified numerical text: {token}")
