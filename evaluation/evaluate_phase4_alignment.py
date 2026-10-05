"""Build the Phase 4.1 alignment report from fresh regression and live E2E results."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def main():
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    output = test.stdout + test.stderr
    passed = int((re.search(r"(\d+) passed", output) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", output) or [0, 0])[1])
    skipped = int((re.search(r"(\d+) skipped", output) or [0, 0])[1])

    e2e = json.loads((ROOT / "evaluation" / "phase4_e2e_live_results.json").read_text(encoding="utf-8"))
    phase4 = json.loads((ROOT / "evaluation" / "phase4_results.json").read_text(encoding="utf-8"))
    selected = {case["id"]: case for case in e2e["cases"]
                if case["id"] in {"hadith_record", "hadith_authenticity_safety"}}
    hadith_row = selected["hadith_record"]["claims"][0]
    authenticity_row = selected["hadith_authenticity_safety"]["claims"][0]

    def results(row):
        return [{
            "attribute_id": item["attribute_id"], "attribute_type": item["attribute_type"],
            "status": item["status"], "validation_method": item["validation_method"],
            "evidence_ids": item["evidence_ids"],
            "supporting_evidence_ids": item["supporting_evidence_ids"],
            "contradicting_evidence_ids": item["contradicting_evidence_ids"],
        } for item in row["phase4"]["validations"]]

    auth_results = results(authenticity_row)
    report = {
        "status": "completed" if test.returncode == 0 else "failed",
        "tests_run": passed + failed + skipped,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "hadith_candidates": hadith_row["phase3"]["evidence"],
        "candidate_alignment": hadith_row["phase4"]["candidate_alignment"],
        "attribute_results": results(hadith_row),
        "authenticity_attribute_results": auth_results,
        "supporting_evidence_ids": sorted({e for item in results(hadith_row) for e in item["supporting_evidence_ids"]}),
        "contradicting_evidence_ids": sorted({e for item in results(hadith_row) for e in item["contradicting_evidence_ids"]}),
        "authenticity_safety_passed": all(
            item["status"] != "SUPPORTED" for item in auth_results if item["attribute_type"] == "AUTHENTICITY"
        ),
        "unsupported_inference_rate": phase4["metrics"]["unsupported_inference_rate"],
        "validation_execution_failures": (
            hadith_row["phase4"]["execution_failures"] + authenticity_row["phase4"]["execution_failures"]
        ),
        "phase_boundary": "STOP_AFTER_PHASE_4",
    }
    destination = ROOT / "evaluation" / "phase4_alignment_results.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output.strip())
    print(json.dumps({key: report[key] for key in (
        "tests_run", "tests_passed", "tests_failed", "tests_skipped",
        "authenticity_safety_passed", "unsupported_inference_rate",
    )}, indent=2))
    if test.returncode:
        raise SystemExit(test.returncode)


if __name__ == "__main__":
    main()
