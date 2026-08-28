"""Deterministic schema, grounding, numerical, citation, and policy validation."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from backend.copilot.models import CopilotContext, CopilotDraft
from backend.contracts.api import CopilotClaim, ValidatedCopilotMessage


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

    def validate(self, raw: dict[str, Any], context: CopilotContext) -> ValidatedCopilotMessage:
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
        for evidence_id in draft.contradiction_evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"unknown contradiction evidence: {evidence_id}")

        for claim in draft.claims:
            self._check_policy(claim.text, errors)
            self._check_numbers(claim.text, claim.numeric_assertions, evidence, errors)
            for citation in claim.citations:
                payload = citation.model_dump(mode="json")
                if payload["citation_type"] == "EVIDENCE":
                    key = (
                        payload["evidence_id"],
                        payload["evidence_package_id"],
                        payload["evidence_package_version"],
                    )
                    if key not in evidence_manifest or payload["evidence_id"] not in evidence:
                        errors.append(f"unauthorised evidence citation in {claim.claim_id}")
                else:
                    key = (payload["runbook_id"], payload["runbook_version"], payload["section_id"])
                    if key not in runbook_manifest:
                        errors.append(f"unauthorised runbook citation in {claim.claim_id}")
            if claim.claim_type.value == "RUNBOOK_GUIDANCE" and not any(
                citation.citation_type == "RUNBOOK" for citation in claim.citations
            ):
                errors.append(f"runbook guidance {claim.claim_id} lacks a runbook citation")

        self._check_policy(draft.summary, errors)
        for recommendation in draft.recommendations:
            self._check_policy(f"{recommendation.title} {recommendation.rationale}", errors)
            if not recommendation.requires_human_approval:
                errors.append(f"recommendation {recommendation.recommendation_id} bypasses human control")
            if not recommendation.citations:
                errors.append(f"recommendation {recommendation.recommendation_id} is uncited")
            if recommendation.action_type in {"CONTAIN", "REMEDIATE"} and not any(
                citation.citation_type == "RUNBOOK" for citation in recommendation.citations
            ):
                errors.append(f"operational recommendation {recommendation.recommendation_id} is not runbook-grounded")

        if errors:
            raise CopilotValidationError(sorted(set(errors)))
        return ValidatedCopilotMessage(
            message_id=f"msg_{uuid4().hex}",
            interaction_id=context.interaction_id,
            incident_id=context.incident_id,
            evidence_package_id=context.evidence_package_id,
            evidence_package_version=context.evidence_package_version,
            mode=draft.mode,
            status="VALIDATED",
            created_at=datetime.now(UTC),
            summary=draft.summary,
            claims=[
                CopilotClaim(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    text=claim.text,
                    citations=claim.citations,
                )
                for claim in draft.claims
            ],
            assessment=draft.assessment,
            recommendations=draft.recommendations,
            limitations=draft.limitations,
            suggested_questions=draft.suggested_questions,
        )

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
