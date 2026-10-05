"""Run the 30-case live evaluation. Requires ANTHROPIC_API_KEY; never invents scores."""
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.models.claim import ExtractionResult  # noqa: E402


def contains_proposition(result, token):
    token = token.casefold()
    return any(token in claim.normalized_claim.casefold() or token in claim.original_text.casefold()
               for claim in result.claims)


def evaluate(items, extractor, cached_by_text=None):
    cached_by_text = cached_by_text or {}
    rows = []
    totals = {"structured": 0, "count": 0, "domain_hits": 0, "domain_total": 0,
              "type_hits": 0, "type_total": 0, "missed": 0, "propositions": 0,
              "oversplit": 0, "evidence_requirements": 0, "evidence_requirement_cases": 0}
    for item in items:
        expected = item["expected"]
        input_text = item["input_text"]
        try:
            cached = cached_by_text.get(input_text)
            result = (
                ExtractionResult.model_validate({
                    "input_language": cached.get("input_language", "other"),
                    "claim_count": cached["claim_count"],
                    "claims": cached["claims"],
                })
                if cached else extractor.extract(input_text)
            )
            totals["structured"] += 1
            count_ok = expected["minimum_claim_count"] <= result.claim_count <= expected["maximum_claim_count"]
            totals["count"] += int(count_ok)
            actual_domains = {x.domain.value for x in result.claims}
            actual_types = {x.claim_type.value for x in result.claims}
            domain_hits = sum(x in actual_domains for x in expected["domains"])
            type_hits = sum(x in actual_types for x in expected["claim_types"])
            missed = sum(not contains_proposition(result, x) for x in expected["key_propositions"])
            evidence_count = sum(claim.requires_evidence for claim in result.claims)
            non_verifiable_count = result.claim_count - evidence_count
            evidence_requirement_accurate = None
            if "minimum_evidence_required" in expected:
                evidence_requirement_accurate = (
                    evidence_count >= expected["minimum_evidence_required"]
                    and non_verifiable_count <= expected["maximum_non_verifiable"]
                )
                totals["evidence_requirement_cases"] += 1
                totals["evidence_requirements"] += int(evidence_requirement_accurate)
            totals["domain_hits"] += domain_hits; totals["domain_total"] += len(expected["domains"])
            totals["type_hits"] += type_hits; totals["type_total"] += len(expected["claim_types"])
            totals["missed"] += missed; totals["propositions"] += len(expected["key_propositions"])
            totals["oversplit"] += max(0, result.claim_count - expected["maximum_claim_count"])
            rows.append({"id": item["id"], "text": input_text,
                         "success": True, "claim_count": result.claim_count,
                         "input_language": result.input_language,
                         "claim_texts": [claim.original_text for claim in result.claims],
                         "claims": [claim.model_dump(mode="json") for claim in result.claims],
                         "requires_evidence_count": evidence_count,
                         "non_verifiable_count": non_verifiable_count,
                         "evidence_requirement_accurate": evidence_requirement_accurate,
                         "count_accurate": count_ok, "missed_key_propositions": missed})
        except Exception as exc:
            rows.append({"id": item["id"], "text": input_text,
                         "success": False, "error": type(exc).__name__})
            totals["domain_total"] += len(expected["domains"])
            totals["type_total"] += len(expected["claim_types"])
            totals["missed"] += len(expected["key_propositions"])
            totals["propositions"] += len(expected["key_propositions"])
    n = len(items)
    ratio = lambda a, b: round(a / b, 4) if b else 0.0
    metrics = {
        "claim_count_accuracy": ratio(totals["count"], n),
        "domain_classification_accuracy": ratio(totals["domain_hits"], totals["domain_total"]),
        "claim_type_accuracy": ratio(totals["type_hits"], totals["type_total"]),
        "missed_claim_rate": ratio(totals["missed"], totals["propositions"]),
        "over_splitting_rate": ratio(totals["oversplit"], n),
        "structured_output_success_rate": ratio(totals["structured"], n),
        "evidence_requirement_accuracy": ratio(
            totals["evidence_requirements"], totals["evidence_requirement_cases"]
        ),
    }
    return metrics, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-failures", action="store_true",
                        help="Reuse successful cases in the current result and retry only failures.")
    args = parser.parse_args()
    items = json.loads((ROOT / "evaluation" / "claim_extraction_dataset.json").read_text(encoding="utf-8-sig"))
    output_dir = ROOT / "evaluation" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "claim_extraction_results.json"
    cached_by_text = {}
    if args.resume_failures and result_path.exists():
        previous = json.loads(result_path.read_text(encoding="utf-8"))
        cached_by_text = {
            case["text"]: case for case in previous.get("cases", [])
            if case.get("success") and case.get("claims")
        }
    settings = get_settings()
    if not settings.anthropic_api_key:
        report = {"status": "skipped", "reason": "ANTHROPIC_API_KEY is not configured; metrics were not fabricated.",
                  "case_count": len(items), "model": settings.anthropic_model,
                  "timestamp_utc": datetime.now(timezone.utc).isoformat(), "metrics": None}
    else:
        metrics, cases = evaluate(items, ClaimExtractor(settings), cached_by_text)
        if metrics["structured_output_success_rate"] == 0:
            report = {
                "status": "failed",
                "reason": "No model response passed extraction; metrics were not reported.",
                "case_count": len(items), "model": settings.anthropic_model,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(), "metrics": None,
                "cases": cases,
            }
        else:
            report = {"status": "completed", "case_count": len(items), "model": settings.anthropic_model,
                      "timestamp_utc": datetime.now(timezone.utc).isoformat(), "metrics": metrics, "cases": cases}
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["Bayyinah AI Claim Extraction Evaluation", f"Status: {report['status']}", f"Cases: {len(items)}"]
    if report["metrics"]:
        lines.extend(f"{key}: {value:.2%}" for key, value in report["metrics"].items())
    else:
        lines.append(f"Reason: {report['reason']}")
    summary = "\n".join(lines) + "\n"
    (output_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")


if __name__ == "__main__":
    main()

