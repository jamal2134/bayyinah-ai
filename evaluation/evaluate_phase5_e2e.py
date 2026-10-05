"""Consume saved Phase 4 live output and produce Phase 5 decisions without live calls."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.decision.engine import decide_claim  # noqa: E402
from app.decision.models import ClaimDecisionRequest  # noqa: E402
from app.models.claim import Claim  # noqa: E402
from app.models.validation import EvidenceValidationResponse  # noqa: E402


EXPECTED = {
    "quran_reference": ("SUPPORTED", "ALL_REQUIRED_ATTRIBUTES_SUPPORTED"),
    "quran_metadata": ("SUPPORTED", "ALL_REQUIRED_ATTRIBUTES_SUPPORTED"),
    "quran_metadata_negative": ("CONFLICTING", "EVIDENCE_CONFLICT"),
    "hadith_record": ("SUPPORTED", "ALL_REQUIRED_ATTRIBUTES_SUPPORTED"),
    "hadith_authenticity_safety": ("INSUFFICIENT_EVIDENCE", "REQUIRED_EVIDENCE_MISSING"),
    "bayan_education": ("INSUFFICIENT_EVIDENCE", "REQUIRED_EVIDENCE_MISSING"),
}


def main():
    source = ROOT / "evaluation" / "phase4_e2e_live_results.json"
    phase4 = json.loads(source.read_text(encoding="utf-8"))
    records = []
    for case in phase4["cases"]:
        if case["id"] not in EXPECTED:
            continue
        if len(case["claims"]) != 1:
            raise ValueError(f"{case['id']} must contain exactly one Phase 4 claim")
        row = case["claims"][0]
        claim = Claim.model_validate(row["phase2"])
        validation = EvidenceValidationResponse.model_validate(row["phase4"])
        result = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
        expected, expected_reason = EXPECTED[case["id"]]
        records.append({
            "id": case["id"], "claim_id": claim.id,
            "expected_decision": expected, "actual_decision": result.decision.value,
            "expected_reason_code": expected_reason, "actual_reason_code": result.reason_code.value,
            "phase4_attribute_statuses": {item.attribute_id: item.status.value for item in validation.validations},
            "supporting_evidence_ids": result.supporting_evidence_ids,
            "contradicting_evidence_ids": result.contradicting_evidence_ids,
            "unresolved_attribute_ids": result.unresolved_attribute_ids,
            "decision_trace": [item.model_dump(mode="json") for item in result.decision_trace],
            "passed": result.decision.value == expected and result.reason_code.value == expected_reason,
        })
    report = {
        "status": "completed" if len(records) == len(EXPECTED) and all(r["passed"] for r in records) else "failed",
        "mode": "saved_phase4_live_input_no_provider_calls", "source": str(source.relative_to(ROOT)),
        "case_count": len(records), "passed_cases": sum(r["passed"] for r in records), "records": records,
    }
    destination = ROOT / "evaluation" / "phase5_e2e_results.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "case_count": report["case_count"],
                      "passed_cases": report["passed_cases"]}, indent=2))
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
