import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult
from app.retrieval.providers.base import InvalidProviderResponse, ProviderAdapter
from app.retrieval.query_selector import quran_ayah_numbers, quran_identifiers, select_queries
from app.validation.normalization import normalize_surah


SURAH_NUMBERS = {"الفاتحة": 1, "البقرة": 2, "آل عمران": 3, "الكهف": 18,
                 "الملك": 67, "الإخلاص": 112, "الفلق": 113, "الناس": 114,
                 "الإسراء": 17, "الاسراء": 17, "غافر": 40, "الشرح": 94, "المسد": 111,
                 "al-fatiha": 1, "al-baqarah": 2, "al-mulk": 67}

PREFERRED_TAFSIR_IDS = (2012, 3, 331)


class QuranpediaAdapter(ProviderAdapter):
    provider = EvidenceProvider.QURANPEDIA

    @staticmethod
    def surah_number(value: str | None):
        if not value:
            return None
        if value.isdigit() and 1 <= int(value) <= 114:
            return int(value)
        normalized = normalize_surah(value)
        return SURAH_NUMBERS.get(normalized, SURAH_NUMBERS.get(value.strip().casefold().replace("surah ", "")))

    async def list_tafsir_sources(self, surah: int, ayah: int):
        return await self.get_json(f"/ayah/{surah}/{ayah}/tafsir")

    async def get_tafsir(self, surah: int, ayah: int, book_id: int):
        return await self.get_json(f"/ayah/{surah}/{ayah}/book/{book_id}")

    @staticmethod
    def _rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "books", "tafsirs"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    async def _retrieve_tafsir(self, claim, surah, ayah_numbers, attempts):
        evidence = []
        for ayah in ayah_numbers:
            discovery_endpoint = f"/ayah/{surah}/{ayah}/tafsir"
            started = time.perf_counter()
            discovery, status = await self.get_json_response(discovery_endpoint)
            books = self._rows(discovery)
            attempts.append(self.attempt(
                f"{surah}:{ayah}:tafsir", len(attempts) + 1, started, len(books), True,
                endpoint=discovery_endpoint, http_status=status,
                parser_success=isinstance(discovery, (list, dict)),
            ))
            available = {int(item["id"]): item for item in books
                         if isinstance(item, dict) and str(item.get("id", "")).isdigit()}
            for book_id in PREFERRED_TAFSIR_IDS:
                if book_id not in available:
                    continue
                content_endpoint = f"/ayah/{surah}/{ayah}/book/{book_id}"
                content_started = time.perf_counter()
                payload, content_status = await self.get_json_response(content_endpoint)
                content = payload.get("content", []) if isinstance(payload, dict) else []
                usable = [item for item in content if isinstance(item, dict) and item.get("text")]
                attempts.append(self.attempt(
                    str(book_id), len(attempts) + 1, content_started, len(usable), bool(usable),
                    endpoint=content_endpoint, http_status=content_status,
                    parser_success=isinstance(payload, dict),
                ))
                if not usable:
                    continue
                book = payload.get("book") or available[book_id]
                author_data = book.get("author") if isinstance(book, dict) else None
                author = ((author_data.get("ar_name") or author_data.get("name"))
                          if isinstance(author_data, dict) else author_data)
                texts = [BeautifulSoup(str(item["text"]), "html.parser").get_text(" ", strip=True)
                         for item in usable]
                texts = [text for text in texts if text]
                if not texts:
                    continue
                book_name = book.get("name") or available[book_id].get("name")
                evidence.append(EvidenceCandidate(
                    evidence_id=f"quranpedia:tafsir:{surah}:{ayah}:{book_id}", claim_id=claim.id,
                    provider=self.provider, evidence_type=EvidenceType.QURAN_TAFSIR,
                    query_used=f"{surah}:{ayah}:tafsir", title=book_name,
                    text=" ".join(texts), source_name="Quranpedia", author=author,
                    reference=f"{surah}:{ayah}", language="ar", provider_record_id=str(book_id),
                    source_url=f"{self.base_url}{content_endpoint}", result_rank=1,
                    retrieved_at=datetime.now(timezone.utc), raw_metadata={
                        "surah": surah, "ayah": ayah, "book_id": book_id,
                        "book_name": book_name, "book_short_name": book.get("short_name"),
                        "author": author, "language": book.get("language"),
                        "fundamental": available[book_id].get("fundamental"),
                        "category": available[book_id].get("category"),
                        "content": usable,
                    },
                ))
                break
        if evidence:
            return ProviderResult(provider=self.provider, success=True,
                                  query_attempts=attempts, evidence=evidence)
        return ProviderResult(
            provider=self.provider, success=False, query_attempts=attempts,
            error=ProviderError(provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                                message="NO_TAFSIR_AVAILABLE", retryable=False),
        )

    async def retrieve(self, claim):
        attempts = []
        try:
            surah_value, ayah_value = quran_identifiers(claim)
            ayah_numbers = quran_ayah_numbers(claim)
            surah = self.surah_number(surah_value)
            if claim.claim_type.value in {"QURAN_INTERPRETATION", "QURAN_TAFSIR"}:
                if surah and ayah_numbers:
                    return await self._retrieve_tafsir(claim, surah, ayah_numbers, attempts)
                return ProviderResult(provider=self.provider, success=False, error=ProviderError(
                    provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                    message="Structured Quran parent context is required for Tafsir lookup.", retryable=False))
            if surah and ayah_numbers:
                started = time.perf_counter()
                rows, statuses, endpoints = [], [], []
                for ayah_number in ayah_numbers:
                    endpoint = f"/mushafs/1/{surah}/{ayah_number}"
                    data, status = await self.get_json_response(endpoint)
                    if not isinstance(data, dict) or not data.get("text"):
                        raise InvalidProviderResponse("Quranpedia ayah response is missing text")
                    rows.append(data)
                    statuses.append(status)
                    endpoints.append(endpoint)
                combined_text = " ".join(row["text"].lstrip("\ufeff") for row in rows)
                reference = f"{surah}:{ayah_numbers[0]}" if len(ayah_numbers) == 1 else f"{surah}:{ayah_numbers[0]}-{ayah_numbers[-1]}"
                evidence = [EvidenceCandidate(
                    evidence_id=f"quranpedia:{reference}", claim_id=claim.id,
                    provider=self.provider, evidence_type=EvidenceType.QURAN_AYAH,
                    query_used=reference, text=combined_text, source_name="Quranpedia",
                    reference=reference, page=str(rows[0].get("page_number")) if rows[0].get("page_number") else None,
                    language="ar", provider_record_id="+".join(str(row.get("id", "")) for row in rows),
                    source_url=f"{self.base_url}{endpoints[0]}", result_rank=1,
                    retrieved_at=datetime.now(timezone.utc), raw_metadata={
                        "surah": surah, "ayah": ayah_numbers[0] if len(ayah_numbers) == 1 else None,
                        "ayah_numbers": ayah_numbers, "ayah_texts": [row["text"] for row in rows],
                        "options": [row.get("options", []) for row in rows],
                    },
                )]
                attempts.append(self.attempt(reference, 1, started, 1, True,
                                             endpoint=",".join(endpoints), http_status=statuses[-1],
                                             parser_success=True))
                return ProviderResult(provider=self.provider, success=True, query_attempts=attempts, evidence=evidence)
            if surah:
                started = time.perf_counter()
                endpoint = f"/surah/information/{surah}"
                data, status = await self.get_json_response(endpoint)
                if not isinstance(data, dict):
                    raise InvalidProviderResponse("Quranpedia surah response is not an object")
                count_rows = data.get("ayahs_count")
                if not isinstance(count_rows, list) or not count_rows:
                    raise InvalidProviderResponse("Quranpedia surah response is missing ayahs_count")
                values = [row.get("value") for row in count_rows if isinstance(row, dict)]
                introduction = data.get("introduction") or {}
                raw_text = introduction.get("value") or f"Surah {surah}: ayah counts {values}"
                text = BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True)
                attempts.append(self.attempt(str(surah), 1, started, 1, True, endpoint=endpoint,
                                             http_status=status, parser_success=True))
                evidence = [EvidenceCandidate(
                    evidence_id=f"quranpedia:surah:{surah}", claim_id=claim.id,
                    provider=self.provider, evidence_type=EvidenceType.QURAN_SURAH,
                    query_used=str(surah), text=text, source_name="Quranpedia",
                    reference=f"surah:{surah}", language="ar", provider_record_id=str(surah),
                    source_url=f"{self.base_url}{endpoint}", result_rank=1,
                    retrieved_at=datetime.now(timezone.utc),
                    raw_metadata={"surah": surah, "ayahs_count": count_rows,
                                  "surah_number": data.get("surah_number"),
                                  "surah_type": data.get("surah_type")},
                )]
                return ProviderResult(provider=self.provider, success=True,
                                      query_attempts=attempts, evidence=evidence)
            return ProviderResult(provider=self.provider, success=False, error=ProviderError(
                provider=self.provider, error_type=ProviderErrorType.NO_RESULTS,
                message="Structured SURAH and AYAH_NUMBER are required for confirmed ayah lookup.", retryable=False))
        except Exception as exc:
            return self.failure(exc, attempts)

