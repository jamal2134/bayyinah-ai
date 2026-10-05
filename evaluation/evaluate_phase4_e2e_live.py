"""Run the real Phase 2 -> Phase 3 APIs -> Phase 4 pipeline; never use fixtures."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.models.claim import Claim  # noqa: E402
from app.models.evidence import EvidenceProvider  # noqa: E402
from app.retrieval.cache import MemoryCache  # noqa: E402
from app.retrieval.providers.bayan import BayanAdapter  # noqa: E402
from app.retrieval.providers.hadeethenc import HadeethEncAdapter  # noqa: E402
from app.retrieval.providers.quranpedia import QuranpediaAdapter  # noqa: E402
from app.retrieval.service import RetrievalService  # noqa: E402
from app.validation.semantic import SemanticValidator  # noqa: E402
from app.validation.service import EvidenceValidationService  # noqa: E402


INPUTS = [
    ("quran_reference", "آية الكرسي هي الآية 255 من سورة البقرة."),
    ("quran_metadata", "سورة الملك تتكون من 30 آية."),
    ("quran_metadata_negative", "سورة الملك تتكون من 31 آية."),
    ("hadith_record", "حديث إنما الأعمال بالنيات عن عمر بن الخطاب رواه البخاري."),
    ("hadith_authenticity_safety", "حديث إنما الأعمال بالنيات صحيح."),
    ("bayan_education", "مواد تعليمية إسلامية للمسلمين."),
]
FORBIDDEN = ("fixture.invalid", "fixture source text", '"fixture": true', '"mock": true')


def real_evidence(candidate):
    blob = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False).casefold()
    return not any(marker in blob for marker in FORBIDDEN) and candidate.raw_metadata.get("fixture") is not True


async def main():
    settings = Settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for this live evaluation")
    timeout = httpx.Timeout(settings.http_read_timeout, connect=settings.http_connect_timeout)
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True,
        headers={"User-Agent": "BayyinahAI/phase4-e2e-live-verification"},
    ) as http_client:
        cache = MemoryCache()
        retrieval = RetrievalService({
            EvidenceProvider.QURANPEDIA: QuranpediaAdapter(settings.quranpedia_base_url, http_client, cache),
            EvidenceProvider.HADEETHENC: HadeethEncAdapter(settings.hadeethenc_base_url, http_client, cache),
            EvidenceProvider.BAYAN: BayanAdapter(settings.bayan_base_url, http_client, cache),
        })
        validator = EvidenceValidationService(SemanticValidator(settings))
        extractor = ClaimExtractor(settings)
        cases = []
        for case_id, text in INPUTS:
            extraction = extractor.extract(text)
            phase2_method = "anthropic_claim_extraction"
            claims = extraction.claims
            # Search-topic requests are intentionally NON_VERIFIABLE in Phase 2. For the
            # provider integration check, use the documented Phase 2 retrieval contract.
            if case_id == "bayan_education" and not any(c.requires_evidence for c in claims):
                claims = [Claim.model_validate({
                    "id": "claim_001", "original_text": text, "normalized_claim": text,
                    "claim_type": "GENERAL_ISLAMIC_CLAIM", "domain": "GENERAL",
                    "search_queries": [text], "entities": [],
                    "attributes": [{"type": "OTHER", "value": text}],
                    "requires_evidence": True,
                    "reason": "Explicit Phase 2 retrieval contract for the Bayan live integration check.",
                })]
                phase2_method = "documented_phase2_contract"
            claim_rows = []
            for claim in claims:
                retrieved = await retrieval.retrieve(claim)
                candidates = [item for provider in retrieved.provider_results for item in provider.evidence]
                if not all(real_evidence(item) for item in candidates):
                    raise AssertionError(f"{case_id} contains fixture/mock evidence")
                validation = validator.validate(claim, candidates, retrieved)
                evidence = [{
                    "provider": item.provider.value,
                    "provider_record_id": item.provider_record_id,
                    "evidence_id": item.evidence_id,
                    "source_url": item.source_url,
                    "target_attribute_ids": item.target_attribute_ids,
                    "fixture": item.raw_metadata.get("fixture", False),
                    "short_identifying_information": item.text[:240],
                    "reference": item.reference,
                } for item in candidates]
                claim_rows.append({
                    "phase2": claim.model_dump(mode="json"),
                    "phase2_method": phase2_method,
                    "phase3": {
                        "status": retrieved.retrieval_status.value,
                        "providers": [item.provider.value for item in retrieved.provider_results],
                        "evidence": evidence,
                    },
                    "phase4": validation.model_dump(mode="json"),
                })
            cases.append({"id": case_id, "input_claim": text, "claims": claim_rows})

    all_evidence = [e for case in cases for row in case["claims"] for e in row["phase3"]["evidence"]]
    validations = [v for case in cases for row in case["claims"] for v in row["phase4"]["validations"]]
    authenticity = [v for v in validations if v["attribute_type"] == "AUTHENTICITY"]
    report = {
        "status": "completed",
        "evaluation_mode": "phase2_phase3_live_apis_phase4",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dorar": {"enabled": False, "reason": "HTTP 403; not required by this evaluation"},
        "metrics": {
            "input_cases": len(INPUTS),
            "real_evidence_candidates": len(all_evidence),
            "fixture_evidence_candidates": sum(bool(e["fixture"]) for e in all_evidence),
            "validation_execution_failures": sum(
                len(row["phase4"]["execution_failures"]) for case in cases for row in case["claims"]
            ),
            "unsupported_authenticity_supports": sum(v["status"] == "SUPPORTED" for v in authenticity),
        },
        "cases": cases,
        "phase_boundary": "STOP_AFTER_PHASE_4",
    }
    output = ROOT / "evaluation" / "phase4_e2e_live_results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
