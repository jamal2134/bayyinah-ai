import asyncio

import pytest

from app.models.evidence import EvidenceProvider, EvidenceType
from app.models.validation import AttributeValidationStatus
from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.retrieval.service import RetrievalService
from app.validation.service import EvidenceValidationService
from evaluation.stage5_mixed_e2e import (
    CASE_CLAIMS, FixtureProvider, FixtureSemanticValidator, HADITH_TEXT,
    _candidate, aggregate_metrics, run_offline_case,
)


def run(case_id, **kwargs):
    return asyncio.run(run_offline_case(case_id, **kwargs))


def test_mixed_valid_runs_complete_pipeline_with_relationships_and_specialist_routes():
    result = run("mixed_valid")
    assert len(result["claims"]) == 7
    children = {item["id"]: (item["parent_claim_id"], item["relationship"])
                for item in result["claims"] if item["parent_claim_id"]}
    assert children == {"claim_002": ("claim_001", "INTERPRETS"),
                        "claim_004": ("claim_003", "EXPLAINS")}
    assert all(item["expected_provider_family"] for item in result["routing"])
    decisions = {item["claim_id"]: item["final_status"] for item in result["decisions"]}
    assert set(decisions.values()) == {"SUPPORTED"}


def test_adversarial_claims_remain_falsifiable_and_wrong_quran_parent_is_not_rescued():
    result = run("mixed_adversarial")
    decisions = {item["claim_id"]: item for item in result["decisions"]}
    assert decisions["claim_001"]["final_status"] == "CONFLICTING"
    assert decisions["claim_002"]["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert decisions["claim_004"]["final_status"] == "CONFLICTING"
    assert decisions["claim_007"]["final_status"] == "CONFLICTING"
    tafseer = next(item for item in result["retrieval"] if item["claim_id"] == "claim_002")
    assert tafseer["status"] == "MISSING_CONTEXT" and tafseer["providers"] == []


def test_partial_case_preserves_absence_as_insufficient_or_ambiguous_not_conflict():
    result = run("partial_insufficient")
    assert {item["final_status"] for item in result["decisions"]} == {"INSUFFICIENT_EVIDENCE"}
    assert not any(item["final_status"] == "CONFLICTING" for item in result["decisions"])


@pytest.mark.parametrize("domain_index,evidence_type,provider", [
    (2, EvidenceType.TAFSEER_SECTION, EvidenceProvider.DORAR_TAFSEER),
    (4, EvidenceType.HADITH, EvidenceProvider.HADEETHENC),
    (5, EvidenceType.FIQH_CONTENT, EvidenceProvider.DORAR_FEQHIA),
    (6, EvidenceType.AQEEDA_CONTENT, EvidenceProvider.DORAR_AQEEDA),
    (0, EvidenceType.HISTORY_EVENT, EvidenceProvider.DORAR_HISTORY),
])
def test_cross_domain_evidence_cannot_create_a_verdict(domain_index, evidence_type, provider):
    item = CASE_CLAIMS["mixed_valid"]()[domain_index]
    evidence = _candidate(item.id, provider, evidence_type, "cross-domain:1",
                          "related words from an incompatible evidence domain")
    result = EvidenceValidationService(FixtureSemanticValidator()).validate(item, [evidence])
    assert all(row.status not in {AttributeValidationStatus.SUPPORTED,
                                  AttributeValidationStatus.CONTRADICTED}
               for row in result.validations)


def test_hadith_explanation_never_validates_authenticity_and_dependency_is_authorized():
    result = run("mixed_valid")
    assert result["metrics"]["unauthorized_explanation_calls"] == 0
    assert result["dependencies"][0]["status"] == "ACCEPTED"
    parent_id = result["dependencies"][0]["parent_evidence_id"]
    assert result["explanation_calls"][0][2] == parent_id
    explanation_ids = {candidate["evidence_id"] for row in result["retrieval"]
                       for provider in row["providers"] for candidate in provider["candidates"]
                       if candidate["evidence_type"] == "HADITH_EXPLANATION"}
    authenticity = [attribute for validation in result["validations"]
                    for attribute in validation["validations"]
                    if attribute["attribute_type"] == "AUTHENTICITY"]
    assert not any(explanation_ids & set(item["evidence_ids"]) for item in authenticity)


def test_unrelated_hadith_parent_makes_zero_dependent_calls():
    child = CASE_CLAIMS["mixed_valid"]()[3]
    parent = CASE_CLAIMS["mixed_valid"]()[2]
    unrelated = _candidate(child.id, EvidenceProvider.DORAR_HADITH,
                           EvidenceType.HADITH_JUDGMENT, "hadith:unrelated", "حديث مختلف تماما",
                           structured_fields={"hadith_id": "x", "explanation_available": True,
                                              "explanation_id": "exp-x"})
    primary = FixtureProvider(EvidenceProvider.DORAR_HADITH, {child.id: [unrelated]})

    class Explanation:
        max_attempts = 1
        calls = []
        async def retrieve_by_id(self, *args, **kwargs):
            self.calls.append(args)

    explanation = Explanation()
    service = RetrievalService({EvidenceProvider.DORAR_HADITH: primary,
                                EvidenceProvider.DORAR_HADITH_EXPLANATION: explanation})
    result = asyncio.run(service.retrieve(child, parent_claim=parent))
    assert explanation.calls == []
    assert result.dependency_trace[0].status.value == "PARENT_UNRELATED"


def test_specialist_failure_is_isolated_and_other_claims_complete():
    result = run("mixed_valid", failed_provider=EvidenceProvider.DORAR_FEQHIA)
    decisions = {item["claim_id"]: item for item in result["decisions"]}
    assert decisions["claim_005"]["final_status"] == "REQUIRES_SPECIALIST"
    assert decisions["claim_005"]["reason_code"] == "VALIDATION_EXECUTION_FAILURE"
    assert all(item["final_status"] == "SUPPORTED" for key, item in decisions.items()
               if key != "claim_005")


def test_metrics_are_structural_and_hit_stage5_targets():
    cases = [run(name) for name in CASE_CLAIMS]
    metrics = aggregate_metrics(cases)
    assert metrics["unsupported_inference_rate"] == 0
    assert metrics["evidence_traceability"] == 1
    assert metrics["routing_precision"] == 1
    assert metrics["unauthorized_explanation_calls"] == 0


def test_evidence_text_url_record_and_parent_identity_survive_end_to_end():
    result = run("mixed_valid")
    candidates = [candidate for row in result["retrieval"] for provider in row["providers"]
                  for candidate in provider["candidates"]]
    assert all(item.get("text") and item.get("source_url") and item.get("provider_record_id")
               for item in candidates)
    explanation = next(item for item in candidates if item["evidence_type"] == "HADITH_EXPLANATION")
    assert explanation["text"] == "صلاح العمل وقبوله مرتبط بالنية"
    assert explanation["parent_evidence_id"] == "dorar-hadith:child-1"


def test_phase5_is_deterministic_across_repeated_controlled_runs():
    first, second = run("mixed_valid"), run("mixed_valid")
    assert first["decisions"] == second["decisions"]


def test_provider_order_and_rank_do_not_change_phase5_decision():
    item = CASE_CLAIMS["mixed_valid"]()[4]
    candidates = [
        _candidate(item.id, EvidenceProvider.DORAR_FEQHIA, EvidenceType.FIQH_CONTENT,
                   "fiqh:a", "صلاة الوتر سنة مؤكدة", title="صلاة الوتر سنة مؤكدة",
                   provider_score=0.01, result_rank=2,
                   raw_metadata={"fixture_semantic_status": "SUPPORTED"}),
        _candidate(item.id, EvidenceProvider.DORAR_FEQHIA, EvidenceType.FIQH_CONTENT,
                   "fiqh:b", "صلاة الوتر سنة مؤكدة", title="صلاة الوتر سنة مؤكدة",
                   provider_score=999, result_rank=1,
                   raw_metadata={"fixture_semantic_status": "SUPPORTED"}),
    ]
    service = EvidenceValidationService(FixtureSemanticValidator())
    first = decide_claim(ClaimDecisionRequest(claim=item,
                         validation=service.validate(item, candidates)))
    reordered = [candidates[1].model_copy(update={"provider_score": 0, "result_rank": 2}),
                 candidates[0].model_copy(update={"provider_score": 1000, "result_rank": 1})]
    second = decide_claim(ClaimDecisionRequest(claim=item,
                          validation=service.validate(item, reordered)))
    assert first.decision == second.decision == "SUPPORTED"
    assert first.reason_code == second.reason_code
