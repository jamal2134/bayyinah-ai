import threading
import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import ProviderAdapter
from app.retrieval.providers.dorar_adapter_utils import attempt, requests_failure, run_serialized, stable_token
from app.retrieval.providers.dorar_retrievers.dorar_hadith_clean import retrieve_hadith
from app.retrieval.query_selector import select_provider_queries


class DorarHadithAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR_HADITH
    _lock = threading.Lock()

    def __init__(self, *args, max_results: int = 15, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_results = max_results

    async def retrieve(self, claim):
        queries = select_provider_queries(claim, self.provider, self.max_attempts)
        if not queries:
            return ProviderResult(provider=self.provider, success=False, error=ProviderError(
                provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                message="No usable Dorar Hadith query."))
        attempts = []
        for query in queries:
            started = time.perf_counter()
            try:
                payload = await run_serialized(self._lock, retrieve_hadith, query, self.max_results)
                rows = payload.get("results", []) if isinstance(payload, dict) else []
                attempts.append(attempt(query, started, len(rows), bool(rows),
                                        parameters={"max_results": self.max_results}, endpoint="/hadith/search"))
            except Exception as exc:
                attempts.append(attempt(query, started, 0, False,
                                        parameters={"max_results": self.max_results}, endpoint="/hadith/search"))
                return requests_failure(self.provider, exc, attempts)
            evidence = [self._candidate(claim.id, query, row) for row in rows
                        if isinstance(row, dict) and row.get("hadith_text")]
            if evidence:
                return ProviderResult(provider=self.provider, success=True,
                                      query_attempts=attempts, evidence=evidence)
        return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                              error=ProviderError(provider=self.provider,
                                  error_type=ProviderErrorType.NO_RESULTS,
                                  message="No Dorar Hadith results found."))

    def _candidate(self, claim_id, query, row):
        record_id = str(row.get("hadith_id") or "") or stable_token(
            row.get("hadith_text"), row.get("narrator"), row.get("scholar"),
            row.get("source"), row.get("grade"))
        structured = {key: row.get(key) for key in (
            "hadith_id", "narrator", "scholar", "source", "page_or_number", "grade",
            "takhrij", "categories", "explanation_available", "explanation_id", "rank", "url")}
        return EvidenceCandidate(
            evidence_id=f"dorar-hadith:{record_id}", claim_id=claim_id, provider=self.provider,
            evidence_type=EvidenceType.HADITH_JUDGMENT, query_used=query,
            text=row["hadith_text"], source_name="Dorar Hadith", reference=row.get("page_or_number"),
            page=row.get("page_or_number"), narrator=row.get("narrator"), scholar=row.get("scholar"),
            judgment=row.get("grade"), language="ar", provider_record_id=record_id,
            source_url=row.get("url"), result_rank=row.get("rank"),
            retrieved_at=datetime.now(timezone.utc), structured_fields=structured,
            raw_metadata=dict(row),
        )
