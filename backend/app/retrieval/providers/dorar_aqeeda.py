import threading
import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import ProviderAdapter
from app.retrieval.providers.dorar_adapter_utils import attempt, requests_failure, run_serialized, stable_token
from app.retrieval.providers.dorar_retrievers.dorar_aqeeda_search import retrieve_aqeeda
from app.retrieval.query_selector import select_provider_queries


class DorarAqeedaAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR_AQEEDA
    _lock = threading.Lock()

    def __init__(self, *args, max_results: int = 15, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_results = max_results

    async def retrieve(self, claim):
        queries = select_provider_queries(claim, self.provider, self.max_attempts)
        attempts = []
        for query in queries:
            started = time.perf_counter()
            try:
                payload = await run_serialized(self._lock, retrieve_aqeeda, query, self.max_results)
            except Exception as exc:
                attempts.append(attempt(query, started, 0, False,
                                        parameters={"max_results": self.max_results}, endpoint="/aqeeda/search"))
                return requests_failure(self.provider, exc, attempts)
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            skipped = payload.get("skipped", []) if isinstance(payload, dict) else []
            evidence = [self._candidate(claim.id, query, row) for row in rows
                        if isinstance(row, dict) and row.get("content")]
            attempts.append(attempt(query, started, len(evidence), bool(evidence),
                parameters={"max_results": self.max_results, "skipped": skipped}, endpoint="/aqeeda/search"))
            if evidence:
                return ProviderResult(provider=self.provider, success=True,
                                      query_attempts=attempts, evidence=evidence)
        return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                              error=ProviderError(provider=self.provider,
                                  error_type=ProviderErrorType.NO_RESULTS,
                                  message="No Dorar Aqeeda records found."))

    def _candidate(self, claim_id, query, row):
        record_id = str(row.get("aqeeda_id") or stable_token(row.get("url"), row.get("title")))
        structured = {key: row.get(key) for key in ("rank", "aqeeda_id", "title", "url")}
        return EvidenceCandidate(
            evidence_id=f"dorar-aqeeda:{record_id}", claim_id=claim_id, provider=self.provider,
            evidence_type=EvidenceType.AQEEDA_CONTENT, query_used=query, title=row.get("title"),
            text=row["content"], source_name="Dorar Aqeeda", language="ar",
            provider_record_id=record_id, source_url=row.get("url"), result_rank=row.get("rank"),
            retrieved_at=datetime.now(timezone.utc), structured_fields=structured,
            raw_metadata=dict(row),
        )
