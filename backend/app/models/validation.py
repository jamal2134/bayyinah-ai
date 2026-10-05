from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.claim import AttributeType, Claim
from app.models.evidence import EvidenceCandidate
from app.models.retrieval import RetrievalResult, RetrievalStatus


class AttributeValidationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    NOT_FOUND = "NOT_FOUND"
    UNCERTAIN = "UNCERTAIN"


class ValidationExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class AttributeValidationResult(BaseModel):
    attribute_id: str
    attribute_type: AttributeType
    claimed_value: str
    status: AttributeValidationStatus
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str
    asserted_by: str | None = None
    validation_method: str
    validator_confidence: float | None = Field(default=None, ge=0, le=1)


class ValidationTrace(BaseModel):
    attribute_id: str
    method: str
    candidate_ids: list[str] = Field(default_factory=list)
    fields_compared: list[str] = Field(default_factory=list)
    result: AttributeValidationStatus


class ValidationExecutionFailure(BaseModel):
    attribute_id: str
    stage: str
    error_type: str
    message: str


class CandidateAlignmentTrace(BaseModel):
    evidence_id: str
    alignment: str
    reason: str
    attribute_id: str | None = None


class EvidenceValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: Claim
    evidence_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    retrieval_result: RetrievalResult | None = None

    @model_validator(mode="after")
    def evidence_belongs_to_claim(self):
        if any(item.claim_id != self.claim.id for item in self.evidence_candidates):
            raise ValueError("all evidence candidates must belong to the requested claim")
        if self.retrieval_result and self.retrieval_result.claim_id != self.claim.id:
            raise ValueError("retrieval_result must belong to the requested claim")
        return self


class EvidenceValidationResponse(BaseModel):
    claim_id: str
    validations: list[AttributeValidationResult] = Field(default_factory=list)
    validation_status: ValidationExecutionStatus
    retrieval_status: RetrievalStatus | None = None
    missing_context: list[str] = Field(default_factory=list)
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    trace: list[ValidationTrace] = Field(default_factory=list)
    execution_failures: list[ValidationExecutionFailure] = Field(default_factory=list)
    candidate_alignment: list[CandidateAlignmentTrace] = Field(default_factory=list)
    authenticity_audit: list[dict[str, Any]] = Field(default_factory=list)
    quran_record_alignment: str | None = Field(default=None, pattern=r"^(ALIGNED|MISMATCH|UNRESOLVED)$")


class SemanticValidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: AttributeValidationStatus
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
