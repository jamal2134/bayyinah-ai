"""Optional live Anthropic evaluation for only the semantic Phase 4 cases."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config.settings import Settings  # noqa: E402
from app.models.claim import Claim  # noqa: E402
from app.validation.semantic import SemanticValidator  # noqa: E402
from app.validation.service import EvidenceValidationService  # noqa: E402
from evaluate_phase4 import build  # noqa: E402


def main():
    settings = Settings()
    output = ROOT / "evaluation" / "results" / "phase4_semantic_live_results.json"
    if not settings.anthropic_api_key:
        output.write_text(json.dumps({"status": "skipped", "reason": "ANTHROPIC_API_KEY is not configured; no score was fabricated."}, indent=2), encoding="utf-8")
        print("Skipped: ANTHROPIC_API_KEY is not configured.")
        return
    cases = [item for item in json.loads((ROOT / "evaluation" / "phase4_cases.json").read_text(encoding="utf-8")) if item["method"] == "semantic"]
    service = EvidenceValidationService(SemanticValidator(settings))
    records = []
    for case in cases:
        claim = Claim.model_validate({
            "id": "claim_001", "original_text": f"Validation target: {case['claim']}",
            "normalized_claim": f"Validation target: {case['claim']}", "claim_type": "HADITH_RECORD",
            "domain": "HADITH", "search_queries": ["semantic evaluation context"], "entities": [],
            "attributes": [{"type": case["type"], "value": case["claim"]}],
            "requires_evidence": True, "reason": "Live Phase 4 evaluation",
        })
        response = service.validate(claim, [build(case)])
        validation = response.validations[0] if response.validations else None
        records.append({"id": case["id"], "expected": case["expected"],
                        "actual": validation.status.value if validation else None,
                        "execution_status": response.validation_status.value,
                        "warnings": response.warnings,
                        "execution_failures": [item.model_dump(mode="json") for item in response.execution_failures]})
    completed = [row for row in records if row["execution_status"] == "COMPLETED"]
    def precision(label):
        predicted = [row for row in completed if row["actual"] == label]
        return (sum(row["expected"] == label for row in predicted) / len(predicted)) if predicted else None

    def accuracy(label):
        expected = [row for row in completed if row["expected"] == label]
        return (sum(row["actual"] == label for row in expected) / len(expected)) if expected else None

    report = {
        "status": "completed" if len(completed) == len(records) else "partial",
        "semantic_validation_accuracy": (sum(row["actual"] == row["expected"] for row in completed) / len(completed)) if completed else None,
        "attempted_cases": len(records), "completed_cases": len(completed),
        "failed_cases": len(records) - len(completed),
        "supported_precision": precision("SUPPORTED"),
        "contradiction_precision": precision("CONTRADICTED"),
        "partial_accuracy": accuracy("PARTIAL"),
        "not_found_accuracy": accuracy("NOT_FOUND"),
        "uncertain_accuracy": accuracy("UNCERTAIN"),
        "records": records,
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "evaluation" / "phase4_semantic_live_results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
