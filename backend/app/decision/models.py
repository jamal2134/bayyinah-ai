from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.claim import Claim
from app.models.validation import EvidenceValidationResponse


class ClaimDecisionStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONFLICTING = "CONFLICTING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REQUIRES_SPECIALIST = "REQUIRES_SPECIALIST"


class DecisionReasonCode(str, Enum):
    ALL_REQUIRED_ATTRIBUTES_SUPPORTED = "ALL_REQUIRED_ATTRIBUTES_SUPPORTED"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
    REQUIRED_EVIDENCE_MISSING = "REQUIRED_EVIDENCE_MISSING"
    AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    CLAIM_CONTRADICTED_BY_EVIDENCE = "CLAIM_CONTRADICTED_BY_EVIDENCE"
    VALIDATION_EXECUTION_FAILURE = "VALIDATION_EXECUTION_FAILURE"
    SPECIALIST_REVIEW_REQUIRED = "SPECIALIST_REVIEW_REQUIRED"


class DecisionRuleTrace(BaseModel):
    rule_id: str
    priority: int
    matched: bool
    reason: str


class ClaimDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation: EvidenceValidationResponse
    claim: Claim | None = None
    specialist_review_required: bool = False

    @model_validator(mode="after")
    def claim_matches_validation(self):
        if self.claim and self.claim.id != self.validation.claim_id:
            raise ValueError("claim and validation claim_id must match")
        return self


class ClaimDecision(BaseModel):
    claim_id: str
    decision: ClaimDecisionStatus
    reason_code: DecisionReasonCode
    reason: str
    attribute_summary: dict[str, int]
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    unresolved_attribute_ids: list[str] = Field(default_factory=list)
    decision_trace: list[DecisionRuleTrace]
