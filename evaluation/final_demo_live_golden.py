"""Live golden acceptance: two extraction checks plus one complete real pipeline run."""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.application.costs import CostTracker  # noqa: E402
from app.application.orchestrator import VerificationOrchestrator  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.retrieval.provider_registry import build_provider_adapters  # noqa: E402
from app.validation.semantic import SemanticValidator  # noqa: E402
from app.validation.service import EvidenceValidationService  # noqa: E402
from evaluation.final_demo_acceptance import GOLDEN  # noqa: E402
from evaluation.stage5_mixed_e2e import RecordingRetrievalService  # noqa: E402
from evaluation.stage51_mixed_live import build_report  # noqa: E402


def signature(claims):
    return [{"claim_type": item.claim_type.value, "domain": item.domain.value,
             "parent_index": next((index for index, candidate in enumerate(claims, 1)
                                   if candidate.id == item.parent_claim_id), None),
             "relationship": item.relationship.value if item.relationship else None}
            for item in claims]


async def main():
    settings = Settings()
    tracker = CostTracker()
    extraction_runs = []
    extractor = ClaimExtractor(settings, usage_sink=tracker.record_usage)
    for number in (1, 2):
        started = time.perf_counter()
        result = await asyncio.to_thread(extractor.extract, GOLDEN)
        extraction_runs.append({"run": number, "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                                "claim_count": result.claim_count, "signature": signature(result.claims)})

    started = time.perf_counter()
    timeout = httpx.Timeout(settings.http_read_timeout, connect=settings.http_connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        retrieval = RecordingRetrievalService(build_provider_adapters(settings, client))
        orchestrator = VerificationOrchestrator(
            settings, extractor=ClaimExtractor(settings, usage_sink=tracker.record_usage),
            retrieval_service=retrieval,
            validation_service=EvidenceValidationService(
                SemanticValidator(settings, usage_sink=tracker.record_usage)),
        )
        response = await orchestrator.verify_text(GOLDEN, "final_demo_live_golden")
    pipeline_duration = round((time.perf_counter() - started) * 1000, 3)
    extraction_runs.append({"run": 3, "duration_ms": next(
        (item.duration_ms for item in response.execution if item.step.value == "ANALYZE_TEXT"), None),
        "claim_count": len(response.claims), "signature": signature([item.claim for item in response.claims])})
    report = build_report(response, retrieval, tracker, pipeline_duration)
    report["extraction_stability"] = {
        "runs": extraction_runs,
        "stable": len({json.dumps(item["signature"], sort_keys=True) for item in extraction_runs}) == 1,
        "claim_counts": [item["claim_count"] for item in extraction_runs],
    }
    report["provider_availability"] = [{
        "provider": provider["provider"],
        "availability": ("AVAILABLE" if provider["success"] and provider["candidate_count"]
                         else "PARTIAL" if provider["success"] else "UNAVAILABLE"),
        "candidate_count": provider["candidate_count"],
        "error_type": provider["error"]["error_type"] if provider["error"] else None,
    } for row in report["retrieval"] for provider in row["providers"]]
    destination = ROOT / "evaluation/final_demo_live_golden.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": report["status"], "claims": len(report["claims"]),
                      "extraction_stability": report["extraction_stability"],
                      "provider_availability": report["provider_availability"],
                      "decisions": report["decisions"], "metrics": report["metrics"],
                      "cost": report["cost"], "failures": report["failures"]},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
