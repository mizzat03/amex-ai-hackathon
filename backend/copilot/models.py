"""Strict internal copilot contracts; raw provider output never crosses this boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.contracts.api import CitationRef
from backend.contracts.common import ContractModel
from backend.contracts.enums import EvidenceTier


CopilotMode = Literal["INITIAL_ANALYSIS", "FOLLOW_UP"]
CopilotConfidence = Literal["LOW", "MODERATE", "HIGH"]


def confidence_for_evidence_tier(
    tier: EvidenceTier | str,
) -> CopilotConfidence:
    """Map only the authoritative deterministic tier to display confidence."""
    value = tier.value if isinstance(tier, EvidenceTier) else tier
    return {
        EvidenceTier.STRONG_EVIDENCE.value: "HIGH",
        EvidenceTier.MODERATE_EVIDENCE.value: "MODERATE",
        EvidenceTier.WEAK_EVIDENCE.value: "LOW",
        EvidenceTier.INSUFFICIENT_EVIDENCE.value: "LOW",
    }[value]


class NumericAssertion(ContractModel):
    evidence_id: str
    field_path: str = Field(min_length=1, max_length=160)
    value: float


class DraftEvidencePoint(ContractModel):
    text: str = Field(min_length=1, max_length=1600)
    citations: list[CitationRef] = Field(default_factory=list, max_length=8)
    numeric_assertions: list[NumericAssertion] = Field(default_factory=list, max_length=8)


class DraftRecommendedCheck(ContractModel):
    title: str = Field(min_length=1, max_length=400)
    rationale: str = Field(min_length=1, max_length=1200)
    expected_signal: str = Field(min_length=1, max_length=1200)
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    requires_human_approval: Literal[True] = True
    citations: list[CitationRef] = Field(default_factory=list, max_length=8)


class CopilotDraft(ContractModel):
    schema_version: Literal["copilot-response.v2"] = "copilot-response.v2"
    mode: CopilotMode
    incident_id: str
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    leading_hypothesis_id: str | None = None
    evidence_tier: EvidenceTier
    strongest_alternative_id: str | None = None
    headline: str = Field(min_length=1, max_length=400)
    direct_answer: str = Field(min_length=1, max_length=2400)
    supporting_points: list[DraftEvidencePoint] = Field(default_factory=list, max_length=12)
    contradictory_points: list[DraftEvidencePoint] = Field(default_factory=list, max_length=12)
    unknown_points: list[DraftEvidencePoint] = Field(default_factory=list, max_length=12)
    recommended_checks: list[DraftRecommendedCheck] = Field(default_factory=list, max_length=8)
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def require_initial_challenge(self) -> "CopilotDraft":
        if self.mode == "INITIAL_ANALYSIS" and not self.unknown_points:
            raise ValueError("initial analysis must state unknown or distinguishing evidence")
        if not self.supporting_points and not self.contradictory_points:
            raise ValueError("an answer requires at least one grounded evidence point")
        return self


class CopilotContext(ContractModel):
    mode: CopilotMode
    interaction_id: str
    incident_id: str
    thread_id: str | None = None
    question: str | None = None
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    evidence_completeness: Literal["COMPLETE", "PARTIAL", "INVALID"]
    leading_hypothesis_id: str | None = None
    evidence_tier: EvidenceTier
    strongest_alternative_id: str | None = None
    evidence_items: list[dict[str, Any]]
    citation_manifest: list[dict[str, Any]]
    runbook_sections: list[dict[str, Any]] = Field(default_factory=list)
    history_digest: dict[str, Any] = Field(default_factory=dict)
    recent_history: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    referenced_history: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class CopilotAudit(ContractModel):
    interaction_id: str
    incident_id: str
    evidence_package_id: str
    evidence_package_version: int
    configuration_version: str
    provider: str
    model_id: str
    mode: CopilotMode
    status: Literal["VALIDATED", "FALLBACK", "FAILED"]
    attempts: int = Field(ge=0)
    repair_attempted: bool
    validation_errors: list[str] = Field(default_factory=list)
    context_item_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    created_at: datetime
    completed_at: datetime
