import json
from pathlib import Path
from types import SimpleNamespace

from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest, ClaimDecisionStatus
from app.models.claim import Claim
from app.models.retrieval import (
    ProviderError, ProviderErrorType, ProviderResult, RetrievalPlan, RetrievalResult, RetrievalStatus,
)
from app.models.validation import EvidenceValidationResponse
from app.reporting.builder import build_overall_report, build_verification_report


ROOT = Path(__file__).parents[2]


def _claim(text="النص الأصلي دون تعديل"):
    return Claim.model_validate({
        "id": "claim_001", "original_text": text, "normalized_claim": "صياغة معيارية",
        "claim_type": "FIQH_RULING", "domain": "FIQH",
        "search_queries": ["حكم فقهي موثق"],
        "attributes": [{"id": "attr_001", "type": "RULING", "value": "سنة مؤكدة"}],
        "requires_evidence": True, "reason": "fixture",
    })


def _report(status="SUPPORTED", *, evidence=None, retrieval=None, display_number=1):
    claim = _claim()
    evidence = evidence or [{
        "evidence_id": "fiqh:1", "provider": "DORAR_FEQHIA", "evidence_type": "FIQH_CONTENT",
        "provider_record_id": "record-1", "source_url": "https://example.test/fiqh/1",
        "title": "حكم الوتر", "text": "صلاة الوتر سنة مؤكدة.",
        "structured_fields": {}, "parent_evidence_id": None,
    }]
    support = ["fiqh:1"] if status in {"SUPPORTED", "PARTIAL"} else []
    contradict = ["fiqh:1"] if status == "CONTRADICTED" else []
    validation = EvidenceValidationResponse.model_validate({
        "claim_id": claim.id, "validation_status": "COMPLETED",
        "validations": [{"attribute_id": "attr_001", "attribute_type": "RULING",
            "claimed_value": "سنة مؤكدة", "status": status,
            "evidence_ids": support + contradict, "supporting_evidence_ids": support,
            "contradicting_evidence_ids": contradict, "rationale": "fixture",
            "validation_method": "semantic"}],
    })
    decision = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
    return build_verification_report(claim, evidence, validation, decision, retrieval,
                                     display_number=display_number)


def test_additive_presentation_fields_numbering_and_original_values_are_exact():
    report = _report(display_number=7)
    assert report.display_number == 7
    assert report.claim_text == "النص الأصلي دون تعديل"
    assert report.normalized_claim == "صياغة معيارية"
    source = report.sources[0]
    assert source.evidence_text == "صلاة الوتر سنة مؤكدة."
    assert source.source_url == "https://example.test/fiqh/1"
    assert source.provider_record_id == "record-1"
    assert source.provider_label_ar == "الدرر السنية — الموسوعة الفقهية"


def test_partial_relationship_is_visible_and_unrelated_candidate_is_hidden():
    evidence = [{
        "evidence_id": "fiqh:1", "provider": "DORAR_FEQHIA", "evidence_type": "FIQH_CONTENT",
        "provider_record_id": "record-1", "source_url": "https://example.test/fiqh/1",
        "text": "دليل جزئي", "structured_fields": {},
    }, {
        "evidence_id": "fiqh:unrelated", "provider": "DORAR_FEQHIA",
        "evidence_type": "FIQH_CONTENT", "text": "نتيجة بحث غير مستعملة",
        "structured_fields": {},
    }]
    report = _report("PARTIAL", evidence=evidence)
    assert [item.evidence_id for item in report.sources] == ["fiqh:1"]
    assert report.sources[0].roles[0].role.value == "PARTIALLY_SUPPORTING"
    assert "نتيجة بحث غير مستعملة" not in report.model_dump_json()


def test_provider_failure_is_separate_from_factual_evidence():
    retrieval = RetrievalResult(
        claim_id="claim_001", retrieval_plan=RetrievalPlan(claim_id="claim_001", sources=[]),
        provider_results=[ProviderResult(
            provider="DORAR_FEQHIA", success=False,
            error=ProviderError(provider="DORAR_FEQHIA", error_type=ProviderErrorType.ACCESS_DENIED,
                                message="403", retryable=False))],
        total_evidence_candidates=0, retrieval_status=RetrievalStatus.SOURCE_ERROR,
    )
    report = _report(retrieval=retrieval)
    assert report.provider_failures[0].error_type == "ACCESS_DENIED"
    assert "لا تمثل هذه المشكلة حكمًا" in report.provider_failures[0].message_ar

    no_results = retrieval.model_copy(deep=True)
    no_results.provider_results[0].error.error_type = ProviderErrorType.NO_RESULTS
    assert _report(retrieval=no_results).provider_failures == []


def test_hadith_explanation_parent_provenance_and_metadata_are_preserved():
    claim = _claim()
    evidence = [{
        "evidence_id": "explanation:1", "provider": "DORAR_HADITH_EXPLANATION",
        "evidence_type": "HADITH_EXPLANATION", "provider_record_id": "exp-1",
        "source_url": "https://example.test/explanation/1", "text": "نص الشرح الأصلي",
        "parent_evidence_id": "hadith:1",
        "structured_fields": {"hadith_id": "h-1", "explanation_id": "exp-1"},
        "target_attribute_ids": ["attr_001"],
    }]
    # The presentation builder is independent of domain semantics; this fixture audits provenance only.
    report = _report(evidence=[{**evidence[0], "evidence_id": "fiqh:1"}])
    assert report.sources[0].parent_evidence_id == "hadith:1"
    assert report.sources[0].metadata["explanation_id"] == "exp-1"
    assert report.sources[0].evidence_text == "نص الشرح الأصلي"


def test_overall_report_has_stable_mapping_and_deterministic_counts():
    reports = [_report("SUPPORTED", display_number=1),
               _report("CONTRADICTED", display_number=2)]
    overall = build_overall_report([SimpleNamespace(report=item) for item in reports])
    assert overall.overall_status == ClaimDecisionStatus.CONFLICTING
    assert [(item.claim_id, item.display_number) for item in overall.claim_numbers] == [
        ("claim_001", 1), ("claim_001", 2)]
    counts = {item.status.value: item.count for item in overall.status_counts}
    assert counts["SUPPORTED"] == 1 and counts["CONFLICTING"] == 1
    assert overall.marker_strategy == "NUMBERED_CLAIMS_SECTION"


def test_stage5_cross_domain_fixture_builds_reports_without_evidence_leakage():
    saved = json.loads((ROOT / "evaluation/stage5_mixed_e2e_offline_results.json").read_text(encoding="utf-8"))
    case = next(item for item in saved["cases"] if item["case_id"] == "mixed_valid")
    providers_by_claim = {}
    for retrieval in case["retrieval"]:
        providers_by_claim[retrieval["claim_id"]] = {
            candidate["evidence_id"]: candidate["provider"]
            for provider in retrieval["providers"] for candidate in provider["candidates"]
        }
    expected = {
        "QURAN": {"QURANPEDIA", "DORAR_TAFSEER"},
        "HADITH": {"HADEETHENC", "DORAR_HADITH", "DORAR_HADITH_EXPLANATION"},
        "FIQH": {"DORAR_FEQHIA"}, "AQEEDAH": {"DORAR_AQEEDA"},
        "HISTORY": {"DORAR_HISTORY"},
    }
    assert {item["domain"] for item in case["claims"]} >= set(expected)
    for validation in case["validations"]:
        claim = next(item for item in case["claims"] if item["id"] == validation["claim_id"])
        used = {eid for row in validation["validations"]
                for eid in row["supporting_evidence_ids"] + row["contradicting_evidence_ids"]}
        assert all(providers_by_claim[claim["id"]][eid] in expected[claim["domain"]] for eid in used)


def test_stage51_live_compatibility_and_frontend_safety_contract():
    live = json.loads((ROOT / "evaluation/stage51_mixed_live_results.json").read_text(encoding="utf-8"))
    decisions = {item["claim_id"]: item["final_status"] for item in live["decisions"]}
    assert decisions == {
        "claim_001": "CONFLICTING", "claim_002": "INSUFFICIENT_EVIDENCE",
        "claim_003": "SUPPORTED", "claim_004": "INSUFFICIENT_EVIDENCE",
        "claim_005": "REQUIRES_SPECIALIST", "claim_006": "REQUIRES_SPECIALIST",
    }
    script = (ROOT / "frontend/assets/app.js").read_text(encoding="utf-8")
    page = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'lang="ar" dir="rtl"' in page
    assert "provider_failures" in script and "source_url" in script
    assert "validator_confidence" not in script and "نسبة صحة" not in script
    assert "PARTIALLY_SUPPORTING" in script and "NUMBERED_CLAIMS_SECTION" not in script
    assert "safeUrl" in script and "original_claim_text" in script
