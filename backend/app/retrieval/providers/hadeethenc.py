import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import InvalidProviderResponse, ProviderAdapter
from app.retrieval.query_selector import select_provider_queries


class HadeethEncAdapter(ProviderAdapter):
    provider = EvidenceProvider.HADEETHENC

    async def _search(self, query: str, language: str):
        params = {"phrase": query, "language": language}
        data, status = await self.get_json_response("/hadeeths/search/", params)
        hits = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(hits, list):
            raise InvalidProviderResponse("HadeethEnc search response is not an array")
        return hits, status, params

    async def retrieve(self, claim):
        attempts = []
        language = "ar" if any("\u0600" <= char <= "\u06ff" for char in claim.normalized_claim) else "en"
        try:
            for number, query in enumerate(select_provider_queries(claim, self.provider, self.max_attempts), 1):
                started = time.perf_counter()
                hits, status, params = await self._search(query, language)
                attempts.append(self.attempt(query, number, started, len(hits), bool(hits),
                                             endpoint="/hadeeths/search/", http_status=status,
                                             parameters=params, parser_success=True))
                if not hits:
                    continue
                evidence = []
                for rank, hit in enumerate(hits[:10], 1):
                    record_id = str(hit.get("id", ""))
                    if not record_id:
                        continue
                    detail_started = time.perf_counter()
                    detail_params = {"language": language, "id": record_id}
                    detail, detail_status = await self.get_json_response("/hadeeths/one/", detail_params)
                    attempts.append(self.attempt(record_id, len(attempts) + 1, detail_started, 1, True,
                                                 endpoint="/hadeeths/one/", http_status=detail_status,
                                                 parameters=detail_params, parser_success=isinstance(detail, dict)))
                    text = detail.get("hadeeth") or detail.get("title")
                    if not text:
                        raise InvalidProviderResponse("HadeethEnc detail response is missing hadith text")
                    score_type = next((key for key in ("similarity", "relevance", "score")
                                       if isinstance(hit.get(key), (int, float))), None)
                    evidence.append(EvidenceCandidate(
                        evidence_id=f"hadeethenc:{record_id}", claim_id=claim.id, provider=self.provider,
                        evidence_type=EvidenceType.HADITH, query_used=query, title=detail.get("title"), text=text,
                        source_name="HadeethEnc", reference=detail.get("reference") or detail.get("references"),
                        judgment=detail.get("grade"), language=language, provider_record_id=record_id,
                        source_url=f"{self.base_url}/hadeeths/one/?language={language}&id={record_id}",
                        provider_score=hit.get(score_type) if score_type else None,
                        provider_score_type=score_type,
                        result_rank=rank, retrieved_at=datetime.now(timezone.utc),
                        raw_metadata={key: detail.get(key) for key in ("attribution", "grade", "explanation", "hints",
                                                                       "categories", "translations", "words_meanings")
                                      if detail.get(key) is not None},
                    ))
                return ProviderResult(provider=self.provider, success=bool(evidence), query_attempts=attempts,
                                      evidence=evidence, error=None if evidence else ProviderError(
                                          provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                                          message="No complete HadeethEnc records found."))
            return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                                  error=ProviderError(provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                                                      message="No HadeethEnc results found."))
        except Exception as exc:
            return self.failure(exc, attempts)
