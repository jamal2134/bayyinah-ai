"""Offline Phase 6 evaluation. Reads saved artifacts and never contacts a provider."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.models.claim import Claim
from app.models.validation import EvidenceValidationResponse
from app.reporting.builder import build_verification_report


def synthetic(case):
    text = case.get("claim_text", "ادعاء عربي للاختبار")
    attrs, vals, evidence = [], [], {}
    for index, status in enumerate(case["statuses"]):
        aid = f"attr_{index + 1:03d}"
        atype = "AUTHENTICITY" if index == case.get("authenticity_index", -1) else "TEXT"
        attrs.append({"id": aid, "type": atype, "value": "قيمة", "requires_evidence": True})
        eid = "bayan:shared" if case.get("same_evidence") else f"bayan:{index + 1}"
        support = [eid] if status in {"SUPPORTED", "PARTIAL"} else []
        oppose = [eid] if status == "CONTRADICTED" else []
        vals.append({"attribute_id": aid, "attribute_type": atype, "claimed_value": "قيمة",
            "status": status, "evidence_ids": support + oppose,
            "supporting_evidence_ids": support, "contradicting_evidence_ids": oppose,
            "rationale": "structured upstream result", "validation_method": "deterministic"})
        if support or oppose:
            evidence[eid] = {"evidence_id": eid, "provider": "BAYAN",
                             "provider_record_id": eid.split(":")[1], "source_url": None}
    claim = Claim.model_validate({"id": "claim_001", "original_text": text,
        "normalized_claim": text, "claim_type": "GENERAL_ISLAMIC_CLAIM", "domain": "GENERAL",
        "search_queries": ["ادعاء عربي للاختبار"], "entities": [], "attributes": attrs,
        "requires_evidence": True, "reason": "Offline deterministic evaluation."})
    failures = []
    execution = "COMPLETED"
    if case.get("execution_failure"):
        failures = [{"attribute_id": "attr_001", "stage": "validator", "error_type": "TestError",
                     "message": "Saved simulated failure"}]
        execution = "ERROR"
    validation = EvidenceValidationResponse.model_validate({"claim_id": claim.id,
        "validations": vals, "validation_status": execution, "execution_failures": failures})
    decision = decide_claim(ClaimDecisionRequest(validation=validation, claim=claim,
                         specialist_review_required=case.get("specialist", False)))
    return claim, list(evidence.values()), validation, decision


def evaluate_dataset():
    cases = json.loads((ROOT / "evaluation/phase6_cases.json").read_text(encoding="utf-8"))
    counters = {"decision": 0, "reason": 0, "attributes": 0, "provenance": 0,
                "unresolved": 0, "not_found": 0, "not_found_n": 0,
                "auth": 0, "auth_n": 0, "injection": 0, "injection_n": 0,
                "determinism": 0, "inference": 0}
    for case in cases:
        claim, evidence, validation, decision = synthetic(case)
        report = build_verification_report(claim, evidence, validation, decision)
        again = build_verification_report(claim, evidence, validation, decision)
        counters["decision"] += report.decision == decision.decision
        counters["reason"] += report.reason_code == decision.reason_code
        original = {v.attribute_id: v.status for v in validation.validations}
        counters["attributes"] += all(original[a.attribute_id] == a.validation_status for a in report.attributes)
        valid_ids = {e["evidence_id"] for e in evidence}
        counters["provenance"] += {s.evidence_id for s in report.sources} <= valid_ids
        counters["unresolved"] += {u.attribute_id for u in report.unresolved_items} == set(decision.unresolved_attribute_ids)
        if "NOT_FOUND" in case["statuses"]:
            counters["not_found_n"] += 1
            counters["not_found"] += all("خاطئة" not in a.user_message for a in report.attributes if a.validation_status.value == "NOT_FOUND")
        if "authenticity_index" in case:
            counters["auth_n"] += 1
            counters["auth"] += any("لا يعني" in warning for warning in report.warnings)
        if case.get("claim_text", "").startswith("Ignore"):
            counters["injection_n"] += 1
            counters["injection"] += report.decision.value != "SUPPORTED"
        counters["determinism"] += report.model_dump_json() == again.model_dump_json()
        counters["inference"] += int(any(a.validation_status != original[a.attribute_id] for a in report.attributes))
    n = len(cases)
    metric = lambda value, total=n: value / total if total else 1.0
    return {"case_count": n, "decision_preservation_rate": metric(counters["decision"]),
        "reason_code_preservation_rate": metric(counters["reason"]),
        "attribute_status_preservation_rate": metric(counters["attributes"]),
        "evidence_provenance_accuracy": metric(counters["provenance"]),
        "unresolved_item_accuracy": metric(counters["unresolved"]),
        "not_found_wording_safety_rate": metric(counters["not_found"], counters["not_found_n"]),
        "authenticity_safety_rate": metric(counters["auth"], counters["auth_n"]),
        "prompt_injection_resistance_rate": metric(counters["injection"], counters["injection_n"]),
        "determinism_rate": metric(counters["determinism"]),
        "unsupported_report_inference_rate": metric(counters["inference"])}


def evaluate_e2e():
    phase4 = json.loads((ROOT / "evaluation/phase4_e2e_live_results.json").read_text(encoding="utf-8"))
    phase5 = {r["id"]: r for r in json.loads(
        (ROOT / "evaluation/phase5_e2e_results.json").read_text(encoding="utf-8"))["records"]}
    records = []
    for case in phase4["cases"]:
        upstream = case["claims"][0]
        claim = Claim.model_validate(upstream["phase2"])
        validation = EvidenceValidationResponse.model_validate(upstream["phase4"])
        decision = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
        report = build_verification_report(claim, upstream["phase3"]["evidence"], validation, decision)
        p5 = phase5[case["id"]]
        data = report.model_dump(mode="json")
        records.append({"id": case["id"], "claim_text": claim.original_text,
            "phase5_decision": p5["actual_decision"], "phase5_reason_code": p5["actual_reason_code"],
            "report_decision": data["decision"], "report_reason_code": data["reason_code"],
            "summary_ar": data["summary_ar"], "attribute_reports": data["attributes"],
            "sources": data["sources"], "unresolved_items": data["unresolved_items"],
            "warnings": data["warnings"], "trace": data["trace"],
            "passed": data["decision"] == p5["actual_decision"] and data["reason_code"] == p5["actual_reason_code"]})
    return {"status": "completed", "mode": "saved_inputs_no_provider_calls", "case_count": len(records),
            "passed_cases": sum(r["passed"] for r in records), "records": records}


if __name__ == "__main__":
    (ROOT / "evaluation/phase6_results.json").write_text(
        json.dumps(evaluate_dataset(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "evaluation/phase6_e2e_results.json").write_text(
        json.dumps(evaluate_e2e(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
