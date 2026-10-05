import time
from datetime import datetime, timezone

import httpx

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.parsers.dorar_html import parse_dorar_html
from app.retrieval.providers.base import InvalidProviderResponse, ProviderAdapter
from app.retrieval.query_selector import select_queries


class DorarAdapter(ProviderAdapter):
    provider = EvidenceProvider.DORAR
    request_headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ar,en;q=0.8",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
        "Referer": "https://dorar.net/hadith/search",
        "X-Requested-With": "XMLHttpRequest",
    }

    async def retrieve(self, claim):
        attempts = []
        try:
            for number, query in enumerate(select_queries(claim, self.max_attempts), 1):
                started = time.perf_counter()
                params = {"skey": query}
                payload, status = await self.get_json_response("/dorar_api.json", params,
                                                               headers=self.request_headers)
                ahadith = payload.get("ahadith") if isinstance(payload, dict) else None
                if not isinstance(ahadith, dict) or not isinstance(ahadith.get("result"), str):
                    raise InvalidProviderResponse("Dorar response is missing ahadith.result HTML")
                records = parse_dorar_html(ahadith["result"])
                attempts.append(self.attempt(query, number, started, len(records), bool(records),
                                             endpoint="/dorar_api.json", http_status=status,
                                             parameters=params, parser_success=True))
                if not records:
                    continue
                evidence = []
                for rank, record in enumerate(records, 1):
                    identity = f"{query}:{rank}"
                    evidence.append(EvidenceCandidate(
                        evidence_id=f"dorar:{identity}", claim_id=claim.id, provider=self.provider,
                        evidence_type=EvidenceType.ATHAR if claim.domain.value == "ATHAR" else EvidenceType.HADITH_JUDGMENT,
                        query_used=query, text=record["hadith"], source_name=record["source"] or "Dorar",
                        reference=record["reference"], narrator=record["narrator"], scholar=record["scholar"],
                        judgment=record["judgment"], language="ar", source_url=f"{self.base_url}/dorar_api.json",
                        result_rank=rank, retrieved_at=datetime.now(timezone.utc),
                        raw_metadata={"response_path": "ahadith.result"},
                    ))
                return ProviderResult(provider=self.provider, success=True, query_attempts=attempts, evidence=evidence)
            return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                                  error=ProviderError(provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                                                      message="No Dorar results found."))
        except httpx.HTTPStatusError as exc:
            query = select_queries(claim, self.max_attempts)[len(attempts)] if len(attempts) < self.max_attempts else None
            attempts.append(self.attempt(query, len(attempts) + 1, started, 0, False,
                                         endpoint="/dorar_api.json", http_status=exc.response.status_code,
                                         parameters={"skey": query} if query else {}, parser_success=False))
            return self.failure(exc, attempts)
        except Exception as exc:
            return self.failure(exc, attempts)

