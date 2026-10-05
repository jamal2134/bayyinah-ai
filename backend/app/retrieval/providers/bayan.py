import time
from datetime import datetime, timezone

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import InvalidProviderResponse, ProviderAdapter
from app.retrieval.query_selector import select_queries


class BayanAdapter(ProviderAdapter):
    provider = EvidenceProvider.BAYAN

    async def retrieve(self, claim):
        attempts = []
        query = select_queries(claim, 1)[0] if select_queries(claim, 1) else claim.normalized_claim
        started = time.perf_counter()
        try:
            # This is one of the small route set published in Bayan's Swagger 1.0 docs.
            endpoint = "/en/Api/content/muslims/list"
            payload, status = await self.get_json_response(endpoint)
            items = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(items, list):
                raise InvalidProviderResponse("Bayan list response is not an array")
            terms = set(query.casefold().split())
            matches = [item for item in items if terms & set(
                f"{item.get('name', '')} {item.get('description', '')} {item.get('arName', '')}".casefold().split())][:10]
            attempts.append(self.attempt(query, 1, started, len(matches), bool(matches),
                                         endpoint=endpoint, http_status=status, parser_success=True))
            evidence = []
            for rank, item in enumerate(matches, 1):
                text = (item.get("description") or item.get("description_ar") or item.get("arDescription")
                        or item.get("name") or item.get("name_ar") or item.get("arName"))
                language = item.get("language")
                if isinstance(language, dict):
                    language = language.get("abr") or language.get("name_en") or language.get("original_name")
                authors = item.get("authors")
                author = item.get("author")
                if not author and isinstance(authors, list):
                    author = ", ".join(str(a.get("name") or a.get("name_ar")) for a in authors
                                       if isinstance(a, dict) and (a.get("name") or a.get("name_ar"))) or None
                score_type = next((key for key in ("similarity", "relevance", "score")
                                   if isinstance(item.get(key), (int, float))), None)
                evidence.append(EvidenceCandidate(
                    evidence_id=f"bayan:{item.get('id', rank)}", claim_id=claim.id, provider=self.provider,
                    evidence_type=EvidenceType.LIBRARY_CONTENT, query_used=query,
                    title=item.get("name") or item.get("name_ar") or item.get("arName"),
                    text=text, source_name="Bayan Al Islam", author=author, language=language,
                    provider_record_id=str(item.get("id")) if item.get("id") is not None else None,
                    provider_score=item.get(score_type) if score_type else None,
                    source_url=f"{self.base_url}/en/Api/id/{item.get('id')}", provider_score_type=score_type,
                    result_rank=rank, retrieved_at=datetime.now(timezone.utc),
                    raw_metadata={key: item.get(key) for key in ("contentType", "translations", "attachments")
                                  if item.get(key) is not None},
                ))
            if evidence:
                return ProviderResult(provider=self.provider, success=True, query_attempts=attempts, evidence=evidence)
            return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                                  error=ProviderError(provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                                                      message="No matching content in confirmed Bayan list route."))
        except Exception as exc:
            return self.failure(exc, attempts)
