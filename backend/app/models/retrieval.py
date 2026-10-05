from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import Claim, ExtractionResult
from app.models.evidence import EvidenceCandidate, EvidenceProvider


class RetrievalPurpose(str, Enum):
    QURAN_RETRIEVAL = "QURAN_RETRIEVAL"
    QURAN_TAFSIR = "QURAN_TAFSIR"
    STRUCTURED_HADITH_RETRIEVAL = "STRUCTURED_HADITH_RETRIEVAL"
    HADITH_SOURCE_AND_JUDGMENT = "HADITH_SOURCE_AND_JUDGMENT"
    ATHAR_SOURCE_AND_JUDGMENT = "ATHAR_SOURCE_AND_JUDGMENT"
    ISLAMIC_LIBRARY_SEARCH = "ISLAMIC_LIBRARY_SEARCH"
    FIQH_RETRIEVAL = "FIQH_RETRIEVAL"
    AQEEDAH_RETRIEVAL = "AQEEDAH_RETRIEVAL"
    HISTORY_RETRIEVAL = "HISTORY_RETRIEVAL"
    HADITH_EXPLANATION = "HADITH_EXPLANATION"


class DependencyStatus(str, Enum):
    PARENT_ALIGNED = "PARENT_ALIGNED"
    PARENT_UNRELATED = "PARENT_UNRELATED"
    PARENT_UNRESOLVED = "PARENT_UNRESOLVED"
    EXPLANATION_NOT_AVAILABLE = "EXPLANATION_NOT_AVAILABLE"
    EXPLANATION_ID_MISSING = "EXPLANATION_ID_MISSING"
    DUPLICATE_EXPLANATION_SKIPPED = "DUPLICATE_EXPLANATION_SKIPPED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    NO_RESULTS = "NO_RESULTS"
    EXPLANATION_IDENTITY_MISMATCH = "EXPLANATION_IDENTITY_MISMATCH"
    EXPLANATION_IDENTITY_UNRESOLVED = "EXPLANATION_IDENTITY_UNRESOLVED"
    ACCEPTED = "ACCEPTED"


class PlannedSource(BaseModel):
    provider: EvidenceProvider
    purpose: RetrievalPurpose
    priority: int = Field(ge=1)


class RetrievalPlan(BaseModel):
    claim_id: str
    sources: list[PlannedSource]
    tasks: list["RetrievalTask"] = Field(default_factory=list)


class RetrievalTask(BaseModel):
    task_id: str = Field(pattern=r"^task_\d{3,}$")
    claim_id: str
    target_attribute_ids: list[str]
    provider: EvidenceProvider
    purpose: RetrievalPurpose
    query: str | None = None
    queries: list[str] = Field(default_factory=list)
    max_results: int | None = Field(default=None, ge=1)
    depends_on_task_id: str | None = Field(default=None, pattern=r"^task_\d{3,}$")
    dependency_evidence_id: str | None = None
    execution_condition: str | None = None


class ProviderErrorType(str, Enum):
    ACCESS_DENIED = "ACCESS_DENIED"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PARSER_ERROR = "PARSER_ERROR"
    NO_RESULTS = "NO_RESULTS"
    ENDPOINT_UNAVAILABLE = "ENDPOINT_UNAVAILABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class ProviderError(BaseModel):
    provider: EvidenceProvider
    error_type: ProviderErrorType
    message: str
    retryable: bool = False
    http_status: int | None = None


class QueryAttempt(BaseModel):
    query: str | None
    attempt: int = Field(ge=1)
    duration_ms: float = Field(ge=0)
    result_count: int = Field(ge=0)
    success: bool
    endpoint: str | None = None
    http_status: int | None = None
    parameters: dict = Field(default_factory=dict)
    parser_success: bool | None = None


class ProviderResult(BaseModel):
    provider: EvidenceProvider
    success: bool
    query_attempts: list[QueryAttempt] = Field(default_factory=list)
    evidence: list[EvidenceCandidate] = Field(default_factory=list)
    error: ProviderError | None = None


class DependencyTrace(BaseModel):
    provider: EvidenceProvider
    status: DependencyStatus
    parent_task_id: str | None = None
    dependent_task_id: str | None = None
    parent_evidence_id: str | None = None
    dependency_record_id: str | None = None
    reason: str


class RetrievalStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    NO_RESULTS = "NO_RESULTS"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    NO_SUPPORTED_SOURCE = "NO_SUPPORTED_SOURCE"
    SOURCE_ERROR = "SOURCE_ERROR"
    SKIPPED = "SKIPPED"


class RetrievalResult(BaseModel):
    claim_id: str
    retrieval_ready: bool = True
    missing_context: list[str] = Field(default_factory=list)
    retrieval_plan: RetrievalPlan
    provider_results: list[ProviderResult] = Field(default_factory=list)
    total_evidence_candidates: int = Field(ge=0)
    retrieval_status: RetrievalStatus
    reason: str | None = None
    dependency_trace: list[DependencyTrace] = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: Claim


class RetrieveTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50_000)


class ExtractAndRetrieveResult(BaseModel):
    extraction: ExtractionResult
    retrieval: list[RetrievalResult]

