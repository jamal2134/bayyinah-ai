import threading
import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import ProviderAdapter
from app.retrieval.providers.dorar_adapter_utils import attempt, requests_failure, run_serialized, stable_token
from app.retrieval.providers.dorar_retrievers.dorar_history_search import search_history
from app.retrieval.query_selector import select_provider_queries


class DorarHistoryAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR_HISTORY
    _lock = threading.Lock()

    async def retrieve(self, claim):
        queries = select_provider_queries(claim, self.provider, self.max_attempts)
        attempts = []
        for query in queries:
            started = time.perf_counter()
            try:
                rows = await run_serialized(self._lock, search_history, query)
            except Exception as exc:
                attempts.append(attempt(query, started, 0, False, endpoint="/history/search"))
                return requests_failure(self.provider, exc, attempts)
            rows = rows if isinstance(rows, list) else []
            evidence = [self._candidate(claim.id, query, row) for row in rows
                        if isinstance(row, dict) and row.get("details")]
            attempts.append(attempt(query, started, len(evidence), bool(evidence),
                                    endpoint="/history/search"))
            if evidence:
                return ProviderResult(provider=self.provider, success=True,
                                      query_attempts=attempts, evidence=evidence)
        return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                              error=ProviderError(provider=self.provider,
                                  error_type=ProviderErrorType.NO_RESULTS,
                                  message="No Dorar History events found."))

    def _candidate(self, claim_id, query, row):
        record_id = str(row.get("event_id") or stable_token(
            row.get("title"), row.get("hijri_year"), row.get("gregorian_year"), row.get("details")))
        structured = {key: row.get(key) for key in (
            "event_id", "title", "hijri_year", "gregorian_year", "url")}
        return EvidenceCandidate(
            evidence_id=f"dorar-history:{record_id}", claim_id=claim_id, provider=self.provider,
            evidence_type=EvidenceType.HISTORY_EVENT, query_used=query, title=row.get("title"),
            text=row["details"], source_name="Dorar History", language="ar",
            provider_record_id=record_id, source_url=row.get("url"),
            retrieved_at=datetime.now(timezone.utc), structured_fields=structured,
            raw_metadata=dict(row),
        )
