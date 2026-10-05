"""Offline Phase 4 evaluation. Semantic cases are reported separately and never fabricated."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.claim import Claim  # noqa: E402
from app.models.evidence import EvidenceCandidate  # noqa: E402
from app.validation.service import EvidenceValidationService  # noqa: E402


def ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def build(case, suffix=""):
    raw = dict(case.get("evidence", {}))
    field = case.get("field")
    value = case.get("value")
    kwargs = {}
    if field == "text": kwargs["text"] = value
    elif field: kwargs[field] = value
    if case.get("scholar"): kwargs["scholar"] = case["scholar"]
    return EvidenceCandidate.model_validate({
        "evidence_id": f"ev_{case['id']}{suffix}", "claim_id": "claim_001",
        "target_attribute_ids": case.get("targets", []), "provider": "QURANPEDIA" if case["type"] in {"SURAH", "AYAH_NUMBER", "VERSE_COUNT", "REVELATION_PERIOD"} else "HADEETHENC",
        "evidence_type": "QURAN_SURAH" if case["type"] in {"SURAH", "VERSE_COUNT", "REVELATION_PERIOD"} else "QURAN_AYAH" if case["type"] == "AYAH_NUMBER" else "HADITH",
        "text": kwargs.pop("text", "retrieved evidence"), "provider_score": case.get("score"),
        "provider_score_type": "similarity" if case.get("score") is not None else None,
        "retrieved_at": datetime.now(timezone.utc), "raw_metadata": raw, **kwargs,
    })


def main():
    cases = json.loads((ROOT / "evaluation" / "phase4_cases.json").read_text(encoding="utf-8"))
    records = []
    for case in cases:
        if case["method"] == "semantic":
            records.append({"id": case["id"], "expected": case["expected"], "actual": None,
                            "method": "semantic", "execution_status": "SKIPPED",
                            "evidence_ids": [], "supporting_evidence_ids": [],
                            "contradicting_evidence_ids": []})
            continue
        claim = Claim.model_validate({
            "id": "claim_001", "original_text": f"Validation target: {case['claim']}",
            "normalized_claim": f"Validation target: {case['claim']}",
            "claim_type": "QURAN_RECORD" if case["type"] in {"SURAH", "AYAH_NUMBER", "VERSE_COUNT", "REVELATION_PERIOD"} else "HADITH_RECORD",
            "domain": "QURAN" if case["type"] in {"SURAH", "AYAH_NUMBER", "VERSE_COUNT", "REVELATION_PERIOD"} else "HADITH",
            "search_queries": ["evaluation claim context"], "entities": [],
            "attributes": [{"type": case["type"], "value": case["claim"], "asserted_by": case.get("asserted_by")}],
            "requires_evidence": True, "reason": "Phase 4 evaluation",
        })
        candidates = [] if case.get("no_candidate") else [build(case)]
        if case.get("conflict"):
            candidates = [build({**case, "field": "judgment", "value": value}, str(index)) for index, value in enumerate(case["conflict"])]
        response = EvidenceValidationService().validate(claim, candidates)
        validation = response.validations[0]
        records.append({"id": case["id"], "expected": case["expected"], "actual": validation.status.value,
                        "method": case["method"], "evidence_ids": validation.evidence_ids,
                        "supporting_evidence_ids": validation.supporting_evidence_ids,
                        "contradicting_evidence_ids": validation.contradicting_evidence_ids})
    evaluated = [row for row in records if row["method"] == "structured"]
    semantic = [row for row in records if row["method"] == "semantic"]
    correct = sum(row["actual"] == row["expected"] for row in evaluated)
    predicted_supported = [row for row in evaluated if row["actual"] == "SUPPORTED"]
    expected_contradicted = [row for row in evaluated if row["expected"] == "CONTRADICTED"]
    expected_not_found = [row for row in evaluated if row["expected"] == "NOT_FOUND"]
    expected_uncertain = [row for row in evaluated if row["expected"] == "UNCERTAIN"]
    injection = [row for row in evaluated if next(case for case in cases if case["id"] == row["id"]).get("injection")]
    unsupported = [row for row in predicted_supported if row["expected"] != "SUPPORTED"]
    metrics = {
        "attribute_validation_accuracy": ratio(correct, len(evaluated)),
        "supported_precision": ratio(sum(row["expected"] == "SUPPORTED" for row in predicted_supported), len(predicted_supported)),
        "contradiction_precision": ratio(sum(row["actual"] == "CONTRADICTED" for row in expected_contradicted), len(expected_contradicted)),
        "not_found_accuracy": ratio(sum(row["actual"] == "NOT_FOUND" for row in expected_not_found), len(expected_not_found)),
        "uncertain_accuracy": ratio(sum(row["actual"] == "UNCERTAIN" for row in expected_uncertain), len(expected_uncertain)),
        "evidence_attribution_accuracy": ratio(sum(row["actual"] == row["expected"] for row in evaluated if row["id"] in {"p4_014", "p4_015"}), 2),
        "evidence_linkage_accuracy": ratio(sum(bool(row["evidence_ids"]) == (row["expected"] != "NOT_FOUND" or row["id"] in {"p4_012", "p4_023", "p4_024", "p4_025"}) for row in evaluated), len(evaluated)),
        "structured_validation_accuracy": ratio(correct, len(evaluated)),
        "semantic_validation_accuracy": None,
        "prompt_injection_resistance_rate": ratio(sum(row["actual"] != "SUPPORTED" for row in injection), len(injection)),
        "unsupported_inference_rate": ratio(len(unsupported), len(evaluated)),
    }
    report = {"mode": "offline_deterministic", "case_count": len(cases), "evaluated_structured_cases": len(evaluated),
              "semantic_cases_skipped": len(semantic), "semantic_skip_reason": "Live Anthropic evaluation is separate; no semantic score was fabricated.",
              "metrics": metrics, "records": records}
    output = ROOT / "evaluation" / "results" / "phase4_results.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "evaluation" / "phase4_results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
