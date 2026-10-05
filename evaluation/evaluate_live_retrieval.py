"""Run Phase 3 against real providers and write a report separate from fixture tests."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config.settings import Settings  # noqa: E402
from app.models.claim import Claim  # noqa: E402
from app.models.evidence import EvidenceProvider  # noqa: E402
from app.retrieval.cache import MemoryCache  # noqa: E402
from app.retrieval.providers.bayan import BayanAdapter  # noqa: E402
from app.retrieval.providers.dorar import DorarAdapter  # noqa: E402
from app.retrieval.providers.hadeethenc import HadeethEncAdapter  # noqa: E402
from app.retrieval.providers.quranpedia import QuranpediaAdapter  # noqa: E402
from app.retrieval.service import RetrievalService  # noqa: E402


FORBIDDEN_MARKERS = ("fixture", "fixture source text", "fixture.invalid", "mock")


def claim(number, text, domain, claim_type, queries, attributes):
    return Claim.model_validate({
        "id": f"claim_{number:03d}", "original_text": text, "normalized_claim": text,
        "domain": domain, "claim_type": claim_type, "search_queries": queries,
        "attributes": attributes, "entities": [], "requires_evidence": True,
        "reason": "Live Phase 3 API verification",
    })


CASES = [
    claim(1, "آية الكرسي هي الآية 255 من سورة البقرة.", "QURAN", "QURAN_REFERENCE",
          ["آية الكرسي سورة البقرة 255"], [{"type": "SURAH", "value": "البقرة"},
                                             {"type": "AYAH_NUMBER", "value": "255"}]),
    claim(2, "سورة الملك تتكون من 30 آية.", "QURAN", "QURAN_CONTEXT",
          ["سورة الملك عدد الآيات"], [{"type": "SURAH", "value": "الملك"},
                                       {"type": "VERSE_COUNT", "value": "30"}]),
    claim(3, "حديث إنما الأعمال بالنيات عن عمر بن الخطاب رواه البخاري.", "HADITH", "HADITH_RECORD",
          ["إنما الأعمال بالنيات"], [{"type": "TEXT", "value": "إنما الأعمال بالنيات"},
                                      {"type": "NARRATOR", "value": "عمر بن الخطاب"}]),
    claim(4, "حديث إنما الأعمال بالنيات صحيح.", "HADITH", "HADITH_AUTHENTICITY",
          ["إنما الأعمال بالنيات"], [{"type": "TEXT", "value": "إنما الأعمال بالنيات"},
                                      {"type": "AUTHENTICITY", "value": "صحيح"}]),
    claim(5, "المسلم من سلم المسلمون من لسانه ويده.", "HADITH", "HADITH_TEXT",
          ["المسلم من سلم المسلمون من لسانه ويده"],
          [{"type": "TEXT", "value": "المسلم من سلم المسلمون من لسانه ويده"}]),
    claim(6, "ابن كثير فسّر النور في الآية بأنه الهدى.", "QURAN", "QURAN_TAFSIR",
          ["ابن كثير تفسير النور الهدى"], []),
    claim(7, "مواد تعليمية إسلامية للمسلمين.", "GENERAL", "GENERAL_ISLAMIC_CLAIM",
          ["Islam Muslim"], []),
    claim(8, "البحث عن حديث يتعلق بالصلاة.", "HADITH", "HADITH_TEXT",
          ["حديث الصلاة"], [{"type": "TEXT", "value": "الصلاة"}]),
    claim(9, "حكم فقهي لا يغطيه مزود موثق حاليًا.", "FIQH", "FIQH_RULING",
          ["حكم فقهي"], [{"type": "RULING", "value": "حكم فقهي"}]),
]


def assert_no_test_evidence(rows):
    offenders = []
    for row in rows:
        for candidate in row.get("evidence_candidates", []):
            serialized = json.dumps(candidate, ensure_ascii=False).casefold()
            if any(marker in serialized for marker in FORBIDDEN_MARKERS):
                offenders.append(candidate.get("evidence_id"))
    if offenders:
        raise AssertionError(f"Live evidence contains fixture/mock markers: {offenders}")


async def main():
    settings = Settings()
    timeout = httpx.Timeout(settings.http_read_timeout, connect=settings.http_connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": "BayyinahAI/phase3-live-verification"}) as client:
        cache = MemoryCache()
        adapters = {
            EvidenceProvider.QURANPEDIA: QuranpediaAdapter(settings.quranpedia_base_url, client, cache),
            EvidenceProvider.HADEETHENC: HadeethEncAdapter(settings.hadeethenc_base_url, client, cache),
            EvidenceProvider.DORAR: DorarAdapter(settings.dorar_base_url, client, cache),
            EvidenceProvider.BAYAN: BayanAdapter(settings.bayan_base_url, client, cache),
        }
        service = RetrievalService(adapters)
        rows = []
        for item in CASES:
            result = await service.retrieve(item)
            candidates = [candidate.model_dump(mode="json")
                          for provider in result.provider_results for candidate in provider.evidence]
            rows.append({"claim": item.model_dump(mode="json"),
                         "retrieval": result.model_dump(mode="json"),
                         "evidence_candidates": candidates})

    assert_no_test_evidence(rows)
    provider_results = [provider for row in rows for provider in row["retrieval"]["provider_results"]]
    attempts = [attempt for provider in provider_results for attempt in provider["query_attempts"]]
    evidence = [candidate for row in rows for candidate in row["evidence_candidates"]]
    targeted_ids = {attribute_id for row in rows for task in row["retrieval"]["retrieval_plan"]["tasks"]
                    for attribute_id in task["target_attribute_ids"]}
    covered_ids = {attribute_id for candidate in evidence
                   for attribute_id in candidate.get("target_attribute_ids", [])}
    provider_names = sorted({provider["provider"] for provider in provider_results})
    reached = sorted({provider["provider"] for provider in provider_results
                      if any(a.get("http_status") is not None for a in provider["query_attempts"])})
    successfully_queried = sorted({provider["provider"] for provider in provider_results
                                   if provider["success"] and any(
                                       a.get("http_status") is not None and a.get("parser_success") is True
                                       for a in provider["query_attempts"])})
    metrics = {
        "live_cases": len(rows), "providers_attempted": len(provider_names),
        "providers_reached": len(reached),
        "providers_successfully_queried": len(successfully_queried),
        "successful_api_calls": sum(a["success"] for a in attempts),
        "failed_api_calls": sum(not a["success"] for a in attempts),
        "provider_access_denied_calls": sum(a.get("http_status") == 403 for a in attempts),
        "claims_with_candidates": sum(bool(row["evidence_candidates"]) for row in rows),
        "claims_without_candidates": sum(not row["evidence_candidates"] for row in rows),
        "evidence_candidates_retrieved": len(evidence), "fixture_candidate_count": 0,
        "missing_context_cases": sum(row["retrieval"]["retrieval_status"] == "MISSING_CONTEXT" for row in rows),
        "no_supported_source_cases": sum(row["retrieval"]["retrieval_status"] == "NO_SUPPORTED_SOURCE"
                                         for row in rows),
        "provider_successful_query_rate": (len(successfully_queried) / len(provider_names)
                                           if provider_names else 0),
        "normalization_success_rate": (sum(bool(candidate.get("provider") and candidate.get("text"))
                                           for candidate in evidence) / len(evidence) if evidence else 1),
        "attribute_coverage_rate": (len(targeted_ids & covered_ids) / len(targeted_ids)
                                    if targeted_ids else 1.0),
        "source_metadata_preservation_rate": (sum(bool(candidate.get("source_name") and
                                                          (candidate.get("provider_record_id") or
                                                           candidate.get("source_url")))
                                                   for candidate in evidence) / len(evidence) if evidence else 1),
        "missing_context_safety_rate": 1.0 if any(
            row["retrieval"]["retrieval_status"] == "MISSING_CONTEXT" and
            not row["retrieval"]["provider_results"] for row in rows) else 0.0,
        "unsupported_source_safety_rate": 1.0 if any(
            row["retrieval"]["retrieval_status"] == "NO_SUPPORTED_SOURCE" and
            not row["retrieval"]["provider_results"] for row in rows) else 0.0,
    }
    report = {"status": "completed", "evaluation_mode": "live_real_providers",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "providers_attempted": provider_names, "providers_reached": reached,
              "providers_successfully_queried": successfully_queried,
              "metrics": metrics, "cases": rows}
    output = ROOT / "evaluation" / "phase3_live_results_fixed.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
