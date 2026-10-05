import threading
import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import ProviderAdapter
from app.retrieval.providers.dorar_adapter_utils import attempt, requests_failure, run_serialized, stable_token
from app.retrieval.providers.dorar_retrievers.dorar_tafseer_clean import export_tafseer
from app.retrieval.query_selector import select_provider_queries


class DorarTafseerAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR_TAFSEER
    _lock = threading.Lock()

    async def retrieve(self, claim):
        queries = select_provider_queries(claim, self.provider, self.max_attempts)
        if not queries:
            return self._empty("No usable Dorar Tafseer query.")
        attempts = []
        for query in queries:
            started = time.perf_counter()
            try:
                payload = await run_serialized(self._lock, export_tafseer, query)
            except Exception as exc:
                attempts.append(attempt(query, started, 0, False, endpoint="/tafseer/search"))
                return requests_failure(self.provider, exc, attempts)
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            failures = [row for row in rows if isinstance(row, dict) and row.get("error")]
            evidence = []
            for row in rows:
                if not isinstance(row, dict) or row.get("error"):
                    continue
                for label, content in (row.get("sections") or {}).items():
                    if isinstance(content, str) and content.strip():
                        evidence.append(self._candidate(claim.id, query, row, label, content))
            attempts.append(attempt(query, started, len(evidence), bool(evidence),
                                    parameters={"page_failures": failures}, endpoint="/tafseer/search"))
            if evidence:
                return ProviderResult(provider=self.provider, success=True,
                                      query_attempts=attempts, evidence=evidence)
        return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                              error=ProviderError(provider=self.provider,
                                  error_type=ProviderErrorType.NO_RESULTS,
                                  message="No Dorar Tafseer sections found."))

    def _candidate(self, claim_id, query, row, label, content):
        fragment = stable_token(row.get("page_url"), label)
        page_id = row.get("page_id")
        record_id = str(page_id) if page_id is not None else stable_token(row.get("page_url"))
        structured = {key: row.get(key) for key in (
            "search_match", "source_url", "page_url", "matched_section", "surah_id",
            "page_id", "page_title", "headings")}
        structured["section_name"] = label
        return EvidenceCandidate(
            evidence_id=f"dorar-tafseer:{record_id}:{fragment}", claim_id=claim_id,
            provider=self.provider, evidence_type=EvidenceType.TAFSEER_SECTION,
            query_used=query, title=row.get("page_title"), text=content,
            source_name="Dorar Tafseer", reference=(str(row.get("surah_id"))
                if row.get("surah_id") is not None else None), page=(str(page_id) if page_id is not None else None),
            language="ar", provider_record_id=record_id,
            source_url=row.get("source_url") or row.get("page_url"),
            retrieved_at=datetime.now(timezone.utc), fragment_id=fragment,
            fragment_label=str(label), structured_fields=structured, raw_metadata=dict(row),
        )

    def _empty(self, message):
        return ProviderResult(provider=self.provider, success=False,
                              error=ProviderError(provider=self.provider,
                                  error_type=ProviderErrorType.NO_RESULTS, message=message))
