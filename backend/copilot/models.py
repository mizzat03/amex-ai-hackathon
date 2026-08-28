"""Strict internal copilot contracts; raw provider output never crosses this boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.contracts.api import CitationRef, CopilotRecommendation
from backend.contracts.common import ContractModel
from backend.contracts.enums import ClaimType, CopilotAssessment, EvidenceTier


CopilotMode = Literal["INITIAL_ANALYSIS", "FOLLOW_UP"]


class NumericAssertion(ContractModel):
    evidence_id: str
    field_path: str = Field(min_length=1, max_length=160)
    value: float


class DraftClaim(ContractModel):
    claim_id: str
    claim_type: ClaimType
    text: str = Field(min_length=1, max_length=1600)
    citations: list[CitationRef] = Field(min_length=1, max_length=8)
    numeric_assertions: list[NumericAssertion] = Field(default_factory=list, max_length=8)


class CopilotDraft(ContractModel):
    schema_version: Literal["copilot-response.v1"] = "copilot-response.v1"
    mode: CopilotMode
    incident_id: str
    evidence_package_id: str
    evidence_package_version: int = Field(ge=1)
    leading_hypothesis_id: str | None = None
    evidence_tier: EvidenceTier
    strongest_alternative_id: str | None = None
    contradiction_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=2400)
    claims: list[DraftClaim] = Field(min_length=1, max_length=24)
    assessment: CopilotAssessment | None = None
    recommendations: list[CopilotRecommendation] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=16)
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def require_initial_challenge(self) -> "CopilotDraft":
        if self.mode == "INITIAL_ANALYSIS" and not self.missing_evidence:
            raise ValueError("initial analysis must state missing distinguishing evidence")
        return self


class CopilotContext(ContractModel):
    mode: CopilotMode
    interaction_id: str
    incident_id: str
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
    recent_history: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


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
