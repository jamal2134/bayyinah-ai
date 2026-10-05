import threading
import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import ProviderAdapter
from app.retrieval.providers.dorar_adapter_utils import attempt, requests_failure, run_serialized
from app.retrieval.providers.dorar_retrievers.DORAR_HADITH_EXPLANATION import get_sharh_by_id


class DorarHadithExplanationAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR_HADITH_EXPLANATION
    _lock = threading.Lock()

    async def retrieve(self, claim):
        return ProviderResult(provider=self.provider, success=False, error=ProviderError(
            provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
            message="Dorar Hadith Explanation requires an explicit explanation ID."))

    async def retrieve_by_id(self, claim_id: str, sharh_id: str, hadith_id: str = "",
                             parent_evidence_id: str | None = None) -> ProviderResult:
        started = time.perf_counter()
        try:
            row = await run_serialized(self._lock, get_sharh_by_id, sharh_id, hadith_id)
        except Exception as exc:
            tries = [attempt(str(sharh_id), started, 0, False,
                             endpoint=f"/hadith/sharh/{sharh_id}")]
            return requests_failure(self.provider, exc, tries)
        explanation = row.get("explanation", "") if isinstance(row, dict) else ""
        tries = [attempt(str(sharh_id), started, int(bool(explanation)), bool(explanation),
                         endpoint=f"/hadith/sharh/{sharh_id}")]
        if not explanation:
            return ProviderResult(provider=self.provider, success=False, query_attempts=tries,
                                  error=ProviderError(provider=self.provider,
                                      error_type=ProviderErrorType.NO_RESULTS,
                                      message="No Dorar Hadith explanation content found."))
        explanation_id = str(row.get("explanation_id") or sharh_id)
        structured = {key: row.get(key) for key in (
            "hadith_id", "explanation_id", "hadith_text", "narrator", "scholar",
            "hadith_source", "page_or_number", "grade", "takhrij", "url")}
        candidate = EvidenceCandidate(
            evidence_id=f"dorar-hadith-explanation:{explanation_id}", claim_id=claim_id,
            provider=self.provider, evidence_type=EvidenceType.HADITH_EXPLANATION,
            query_used=None, text=explanation, source_name="Dorar Hadith Explanation",
            reference=row.get("page_or_number"), page=row.get("page_or_number"),
            narrator=row.get("narrator"), scholar=row.get("scholar"), judgment=row.get("grade"),
            language="ar", provider_record_id=explanation_id, source_url=row.get("url"),
            retrieved_at=datetime.now(timezone.utc), parent_evidence_id=parent_evidence_id,
            structured_fields=structured, raw_metadata=dict(row),
        )
        return ProviderResult(provider=self.provider, success=True,
                              query_attempts=tries, evidence=[candidate])
