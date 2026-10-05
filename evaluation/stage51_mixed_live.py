"""One audited real mixed-domain E2E run through VerificationOrchestrator."""
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.application.costs import CostTracker  # noqa: E402
from app.application.models import ProviderCallSummary  # noqa: E402
from app.application.orchestrator import VerificationOrchestrator  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.models.evidence import EvidenceProvider  # noqa: E402
from app.retrieval.provider_registry import build_provider_adapters  # noqa: E402
from app.validation.evidence_matcher import (  # noqa: E402
    CONTEXTUAL_EVIDENCE_TYPES, TYPE_COMPATIBILITY, CandidateAlignment,
    evidence_context_alignment,
)
from app.validation.semantic import SemanticValidator  # noqa: E402
from app.validation.service import EvidenceValidationService  # noqa: E402
from evaluation.stage5_mixed_e2e import MIXED_VALID_AR, RecordingRetrievalService, _routing_expected  # noqa: E402


def build_report(response, retrieval, tracker, duration_ms):
    provider_counts = Counter()
    candidate_by_id = {}
    retrieval_rows, dependency_rows, routing = [], [], []
    for claim_result in response.claims:
        claim = claim_result.claim
        result = retrieval.results[claim.id]
        expected = _routing_expected(claim.domain.value, claim.claim_type.value)
        routing.append({
            "claim_id": claim.id, "expected_provider_family": sorted(expected),
            "planned_sources": [item.model_dump(mode="json") for item in result.retrieval_plan.sources],
            "tasks": [item.model_dump(mode="json") for item in result.retrieval_plan.tasks],
        })
        providers = []
        for provider in result.provider_results:
            provider_counts[provider.provider.value] += len(provider.query_attempts)
            candidates = []
            for item in provider.evidence:
                candidate_by_id[item.evidence_id] = item
                candidates.append({
                    "evidence_id": item.evidence_id, "provider": item.provider.value,
                    "evidence_type": item.evidence_type.value,
                    "provider_record_id": item.provider_record_id,
                    "target_attribute_ids": item.target_attribute_ids,
                    "source_url": item.source_url, "parent_evidence_id": item.parent_evidence_id,
                    "fragment_id": item.fragment_id, "fragment_label": item.fragment_label,
                    "title": item.title, "text": item.text,
                    "structured_fields": item.structured_fields,
                })
            providers.append({
                "provider": provider.provider.value, "success": provider.success,
                "query_attempts": [item.model_dump(mode="json") for item in provider.query_attempts],
                "candidate_count": len(candidates), "candidates": candidates,
                "error": provider.error.model_dump(mode="json") if provider.error else None,
            })
        retrieval_rows.append({"claim_id": claim.id, "status": result.retrieval_status.value,
                               "reason": result.reason, "providers": providers})
        dependency_rows.extend({"claim_id": claim.id, **item.model_dump(mode="json")}
                               for item in result.dependency_trace)

    relationships, unsupported = [], 0
    for claim_result in response.claims:
        claim, validation = claim_result.claim, claim_result.validation
        alignment = {(row.attribute_id, row.evidence_id): row.alignment
                     for row in validation.candidate_alignment if row.attribute_id}
        for row in validation.validations:
            attribute = next(item for item in claim.attributes if item.id == row.attribute_id)
            for role, evidence_ids in (("SUPPORT", row.supporting_evidence_ids),
                                       ("CONTRADICTION", row.contradicting_evidence_ids)):
                for evidence_id in evidence_ids:
                    evidence = candidate_by_id.get(evidence_id)
                    compatible = bool(evidence and evidence.evidence_type in
                                      TYPE_COMPATIBILITY.get(attribute.type, set()))
                    if evidence and evidence.evidence_type in CONTEXTUAL_EVIDENCE_TYPES:
                        aligned = (evidence_context_alignment(claim, attribute, evidence)[0]
                                   == CandidateAlignment.ALIGNED)
                    else:
                        aligned = alignment.get((attribute.id, evidence_id), "ALIGNED") == "ALIGNED"
                    valid = compatible and aligned
                    unsupported += not valid
                    relationships.append({"claim_id": claim.id, "attribute_id": attribute.id,
                                          "evidence_id": evidence_id, "role": role,
                                          "compatible_and_aligned": valid})
    expected_routes = sum(bool(item["expected_provider_family"]) for item in routing)
    precise_routes = sum(set(source["provider"] for source in item["planned_sources"])
                         <= set(item["expected_provider_family"]) for item in routing)
    accepted = {item["parent_evidence_id"] for item in dependency_rows if item["status"] == "ACCEPTED"}
    explanation_candidates = [item for item in candidate_by_id.values()
                              if item.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION]
    unauthorized = sum(not item.parent_evidence_id or item.parent_evidence_id not in accepted
                       for item in explanation_candidates)
    traceable = sum(bool(item["evidence_id"]) for item in relationships)
    cost = tracker.summary(
        [ProviderCallSummary(provider=provider, request_count=count)
         for provider, count in sorted(provider_counts.items())], duration_ms)
    return {
        "evaluation_version": "stage5.1", "mode": "live", "status": response.status.value,
        "generated_at": datetime.now(timezone.utc).isoformat(), "input_text": response.input_text,
        "claims": [item.claim.model_dump(mode="json") for item in response.claims],
        "routing": routing, "retrieval": retrieval_rows, "dependencies": dependency_rows,
        "validations": [{"claim_id": item.claim.id, **item.validation.model_dump(mode="json")}
                        for item in response.claims],
        "decisions": [{"claim_id": item.claim.id, "final_status": item.report.decision.value,
                       "reason_code": item.report.reason_code.value,
                       "evidence_ids": item.report.trace.evidence_ids}
                      for item in response.claims],
        "metrics": {
            "unsupported_inference_count": unsupported,
            "total_support_or_contradiction_decisions": len(relationships),
            "unsupported_inference_rate": unsupported / len(relationships) if relationships else 0,
            "validated_decisions_with_evidence_ids": traceable,
            "total_evidence_based_decisions": len(relationships),
            "evidence_traceability": traceable / len(relationships) if relationships else 1,
            "routing_precision": precise_routes / expected_routes if expected_routes else 1,
            "unauthorized_explanation_calls": unauthorized,
        },
        "relationship_audit": relationships, "cost": cost.model_dump(mode="json"),
        "failures": [{"claim_id": item.claim.id, **failure.model_dump(mode="json")}
                     for item in response.claims for failure in item.validation.execution_failures],
    }


async def main():
    settings = Settings()
    tracker = CostTracker()
    started = time.perf_counter()
    timeout = httpx.Timeout(settings.http_read_timeout, connect=settings.http_connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        retrieval = RecordingRetrievalService(build_provider_adapters(settings, client))
        orchestrator = VerificationOrchestrator(
            settings,
            extractor=ClaimExtractor(settings, usage_sink=tracker.record_usage),
            retrieval_service=retrieval,
            validation_service=EvidenceValidationService(
                SemanticValidator(settings, usage_sink=tracker.record_usage)),
        )
        response = await orchestrator.verify_text(MIXED_VALID_AR, "stage5_live_mixed_valid")
    report = build_report(response, retrieval, tracker,
                          round((time.perf_counter() - started) * 1000, 3))
    destination = ROOT / "evaluation" / "stage51_mixed_live_results.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": report["status"], "claim_count": len(report["claims"]),
                      "decisions": report["decisions"], "metrics": report["metrics"],
                      "cost": report["cost"], "failures": report["failures"]},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
