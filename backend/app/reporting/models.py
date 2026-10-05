from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.decision.models import ClaimDecisionStatus, DecisionReasonCode, DecisionRuleTrace
from app.models.claim import AttributeType
from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.validation import AttributeValidationStatus, EvidenceValidationResponse
from app.decision.models import ClaimDecision


class EvidenceRole(str, Enum):
    SUPPORTING = "SUPPORTING"
    PARTIALLY_SUPPORTING = "PARTIALLY_SUPPORTING"
    CONTRADICTING = "CONTRADICTING"


class VerificationReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: Claim
    evidence_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    validation: EvidenceValidationResponse
    decision: ClaimDecision


class StatusPresentation(BaseModel):
    label_ar: str
    icon: str


class AttributeReport(BaseModel):
    attribute_id: str
    attribute_type: AttributeType
    claimed_value: str
    validation_status: AttributeValidationStatus
    validation_method: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    user_message: str


class AttributeSourceRole(BaseModel):
    attribute_id: str
    role: EvidenceRole


class SourceReport(BaseModel):
    evidence_id: str
    provider: EvidenceProvider
    provider_record_id: str | None = None
    source_url: str | None = None
    title: str | None = None
    evidence_type: EvidenceType | None = None
    author: str | None = None
    evidence_text: str | None = None
    reference: str | None = None
    provider_label_ar: str | None = None
    parent_evidence_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    used_for_attributes: list[str] = Field(default_factory=list)
    roles: list[AttributeSourceRole] = Field(default_factory=list)


class UnresolvedItem(BaseModel):
    attribute_id: str
    attribute_type: AttributeType | None = None
    claimed_value: str | None = None
    status: AttributeValidationStatus | None = None
    message: str


class ReportTrace(BaseModel):
    phase5_decision: ClaimDecisionStatus
    phase5_reason_code: DecisionReasonCode
    phase4_validation_ids: list[str]
    evidence_ids: list[str]
    decision_trace: list[DecisionRuleTrace]


class TraceableVerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    claim_id: str
    claim_text: str
    decision: ClaimDecisionStatus
    reason_code: DecisionReasonCode
    summary_ar: str
    reason_explanation_ar: str
    presentation: StatusPresentation
    attributes: list[AttributeReport]
    sources: list[SourceReport]
    unresolved_items: list[UnresolvedItem]
    warnings: list[str]
    trace: ReportTrace
    technical_details: dict[str, Any]
    display_number: int = Field(default=1, ge=1)
    normalized_claim: str | None = None
    domain: str | None = None
    claim_type: str | None = None
    provider_failures: list["ProviderFailureReport"] = Field(default_factory=list)
    final_explanation_ar: str | None = None


class ProviderFailureReport(BaseModel):
    provider: EvidenceProvider
    provider_label_ar: str
    error_type: str
    message_ar: str
    retryable: bool = False


class StatusCount(BaseModel):
    status: ClaimDecisionStatus
    label_ar: str
    count: int = Field(ge=0)


class ClaimNumberMapping(BaseModel):
    claim_id: str
    display_number: int = Field(ge=1)
    original_claim_text: str


class OverallVerificationReport(BaseModel):
    overall_status: ClaimDecisionStatus
    status_label_ar: str
    total_claims: int = Field(ge=0)
    status_counts: list[StatusCount]
    claim_numbers: list[ClaimNumberMapping]
    marker_strategy: str = "NUMBERED_CLAIMS_SECTION"
