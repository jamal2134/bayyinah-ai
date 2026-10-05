from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import Claim
from app.models.validation import EvidenceValidationResponse
from app.reporting.models import OverallVerificationReport, TraceableVerificationReport


def utcnow():
    return datetime.now(timezone.utc)


class RequestStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StepName(str, Enum):
    ANALYZE_TEXT = "ANALYZE_TEXT"
    RETRIEVE_EVIDENCE = "RETRIEVE_EVIDENCE"
    ALIGN_EVIDENCE = "ALIGN_EVIDENCE"
    VALIDATE_EVIDENCE = "VALIDATE_EVIDENCE"
    MAKE_DECISION = "MAKE_DECISION"
    BUILD_REPORT = "BUILD_REPORT"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionStep(BaseModel):
    step: StepName
    status: StepStatus = StepStatus.PENDING
    title_ar: str
    summary_ar: str = "في انتظار التنفيذ."
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    details: dict = Field(default_factory=dict)


class CostType(str, Enum):
    CALCULATED_FROM_API_USAGE = "CALCULATED_FROM_API_USAGE"
    ESTIMATED = "ESTIMATED"


class CostStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PRICING_UNAVAILABLE = "PRICING_UNAVAILABLE"


class LLMUsageRecord(BaseModel):
    phase: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_type: CostType
    cost_status: CostStatus
    estimated_cost_usd: Decimal | None = None
    estimated_cost_sar: Decimal | None = None


class ProviderCallSummary(BaseModel):
    provider: str
    request_count: int


class CostSummary(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_calls: int = 0
    provider_breakdown: list[ProviderCallSummary] = Field(default_factory=list)
    duration_ms: float = 0
    cost_status: CostStatus = CostStatus.AVAILABLE
    estimated_cost_usd: Decimal | None = Decimal("0")
    estimated_cost_sar: Decimal | None = Decimal("0")
    usd_sar_rate: Decimal = Decimal("3.75")
    usage_records: list[LLMUsageRecord] = Field(default_factory=list)


class ClaimVerificationResult(BaseModel):
    claim: Claim
    validation: EvidenceValidationResponse
    report: TraceableVerificationReport


class VerificationResponse(BaseModel):
    request_id: str
    status: RequestStatus
    input_text: str
    claims: list[ClaimVerificationResult] = Field(default_factory=list)
    execution: list[ExecutionStep]
    cost: CostSummary | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    presentation: OverallVerificationReport | None = None


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50_000)


class VerificationAccepted(BaseModel):
    request_id: str
    status: RequestStatus
