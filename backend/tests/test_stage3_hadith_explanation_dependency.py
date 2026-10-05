import asyncio
from datetime import datetime, timezone

import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import (
    DependencyStatus, ProviderError, ProviderErrorType, ProviderResult, RetrievalStatus,
)
from app.models.validation import AttributeValidationStatus, SemanticValidationOutput
from app.retrieval.service import RetrievalService
from app.validation.service import EvidenceValidationService


TARGET = "الدين النصيحة"


def interpretation_claim(*, kind="HADITH_INTERPRETATION", include_context=True,
                         extra_attributes=None):
    attributes = [{"id": "attr_001", "type": "INTERPRETATION",
                   "value": "النصيحة تشمل إرادة الخير للآخرين"}]
    attributes.extend(extra_attributes or [])
    data = {
        "id": "claim_001", "original_text": "شرح حديث الدين النصيحة",
        "normalized_claim": "شرح حديث الدين النصيحة",
        "claim_type": kind, "domain": "HADITH", "attributes": attributes,
        "search_queries": ["حديث الدين النصيحة"], "requires_evidence": True,
        "reason": "interpretation test",
    }
    if include_context:
        data["subject_context"] = {"type": "HADITH", "text": TARGET}
    return Claim.model_validate(data)


def parent_candidate(identifier, text=TARGET, *, hadith_id=None, available=True,
                     explanation_id="X1", narrator="correct narrator", source="correct source",
                     scholar="Scholar", judgment="Grade"):
    hadith_id = hadith_id or identifier
    structured = {
        "hadith_id": hadith_id, "explanation_available": available,
        "explanation_id": explanation_id, "narrator": narrator, "source": source,
    }
    return EvidenceCandidate(
        evidence_id=f"dorar-hadith:{identifier}", claim_id="claim_001",
        provider=EvidenceProvider.DORAR_HADITH, evidence_type=EvidenceType.HADITH_JUDGMENT,
        text=text, source_name="Dorar Hadith", narrator=narrator, scholar=scholar,
        judgment=judgment, provider_record_id=identifier,
        source_url=f"https://dorar.net/h/{identifier}", retrieved_at=datetime.now(timezone.utc),
        structured_fields=structured, raw_metadata=dict(structured),
    )


def explanation_candidate(explanation_id="X1", *, hadith_id="H1", hadith_text=TARGET,
                          text="Exact retrieved explanation"):
    structured = {"explanation_id": explanation_id, "hadith_id": hadith_id,
                  "hadith_text": hadith_text}
    return EvidenceCandidate(
        evidence_id=f"dorar-hadith-explanation:{explanation_id}", claim_id="claim_001",
        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
        evidence_type=EvidenceType.HADITH_EXPLANATION, text=text,
        source_name="Dorar Hadith Explanation", provider_record_id=explanation_id,
        source_url=f"https://www.dorar.net/hadith/sharh/{explanation_id}",
        retrieved_at=datetime.now(timezone.utc), structured_fields=structured,
        raw_metadata={**structured, "explanation": text},
    )


class Primary:
    max_attempts = 1
    max_results = 10
    def __init__(self, candidates):
        self.candidates = candidates
    async def retrieve(self, claim):
        return ProviderResult(provider=EvidenceProvider.DORAR_HADITH, success=True,
                              evidence=[item.model_copy(deep=True) for item in self.candidates])


class Explanation:
    max_attempts = 1
    calls = None
    def __init__(self, factory=None):
        self.calls = []
        self.factory = factory or (lambda explanation_id, hadith_id, parent_id:
            ProviderResult(provider=EvidenceProvider.DORAR_HADITH_EXPLANATION, success=True,
                           evidence=[explanation_candidate(explanation_id, hadith_id=hadith_id)]))
    async def retrieve_by_id(self, claim_id, explanation_id, hadith_id="", parent_evidence_id=None):
        self.calls.append((claim_id, explanation_id, hadith_id, parent_evidence_id))
        return self.factory(explanation_id, hadith_id, parent_evidence_id)


def retrieve(claim, parents, explanation=None, *, parent_claim=None):
    explanation = explanation or Explanation()
    service = RetrievalService({EvidenceProvider.DORAR_HADITH: Primary(parents),
                                EvidenceProvider.DORAR_HADITH_EXPLANATION: explanation})
    result = asyncio.run(service.retrieve(claim, parent_claim=parent_claim))
    return result, explanation


@pytest.mark.parametrize("parent,expected", [
    (parent_candidate("H1", text="حديث مختلف تمامًا"), DependencyStatus.PARENT_UNRELATED),
    (parent_candidate("H1", text="الدين النص"), DependencyStatus.PARENT_UNRESOLVED),
    (parent_candidate("H1", available=False), DependencyStatus.EXPLANATION_NOT_AVAILABLE),
    (parent_candidate("H1", explanation_id=""), DependencyStatus.EXPLANATION_ID_MISSING),
])
def test_zero_call_safety_gates(parent, expected):
    result, explanation = retrieve(interpretation_claim(), [parent])
    assert explanation.calls == []
    assert result.dependency_trace[0].status == expected
    assert all(item.provider != EvidenceProvider.DORAR_HADITH_EXPLANATION
               for item in result.provider_results)


def test_non_interpretation_claim_makes_zero_explanation_calls():
    claim = Claim.model_validate({
        "id": "claim_001", "original_text": TARGET, "normalized_claim": TARGET,
        "claim_type": "HADITH_RECORD", "domain": "HADITH",
        "attributes": [{"type": "HADITH_TEXT", "value": TARGET}],
        "search_queries": ["حديث الدين النصيحة"], "requires_evidence": True,
        "reason": "record",
    })
    result, explanation = retrieve(claim, [parent_candidate("H1")])
    assert explanation.calls == [] and result.dependency_trace == []


def test_success_path_preserves_dependency_provenance_and_targets_interpretation_only():
    result, explanation = retrieve(interpretation_claim(), [parent_candidate("H1")])
    assert len(explanation.calls) == 1
    dependent = next(item for provider in result.provider_results
                     if provider.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION
                     for item in provider.evidence)
    assert dependent.evidence_type == EvidenceType.HADITH_EXPLANATION
    assert dependent.text == "Exact retrieved explanation"
    assert dependent.source_url == "https://www.dorar.net/hadith/sharh/X1"
    assert dependent.raw_metadata["explanation"] == dependent.text
    assert dependent.parent_evidence_id == "dorar-hadith:H1"
    assert dependent.target_attribute_ids == ["attr_001"]
    task = result.retrieval_plan.tasks[-1]
    assert task.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION
    assert task.depends_on_task_id == "task_001"
    assert task.dependency_evidence_id == "dorar-hadith:H1"
    assert task.target_attribute_ids == ["attr_001"]
    assert task.query is None and task.queries == []
    assert result.dependency_trace[-1].status == DependencyStatus.ACCEPTED


def test_unrelated_explanation_id_is_never_called_but_aligned_one_is():
    unrelated = parent_candidate("A", text="حديث آخر", explanation_id="A")
    aligned = parent_candidate("B", hadith_id="B", explanation_id="B")
    result, explanation = retrieve(interpretation_claim(), [unrelated, aligned])
    assert [call[1] for call in explanation.calls] == ["B"]
    assert {trace.status for trace in result.dependency_trace} >= {
        DependencyStatus.PARENT_UNRELATED, DependencyStatus.ACCEPTED}


def test_wrong_claimed_attribution_does_not_block_correct_text_identity():
    claim = interpretation_claim(extra_attributes=[
        {"id": "attr_002", "type": "HADITH_TEXT", "value": TARGET},
        {"id": "attr_003", "type": "NARRATOR", "value": "wrong narrator"},
        {"id": "attr_004", "type": "SOURCE", "value": "wrong source"},
    ])
    result, explanation = retrieve(claim, [parent_candidate(
        "H1", narrator="actual narrator", source="actual source")])
    assert len(explanation.calls) == 1
    dependent = next(item for provider in result.provider_results
                     if provider.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION
                     for item in provider.evidence)
    assert dependent.target_attribute_ids == ["attr_001"]


def test_explanation_identity_mismatch_is_rejected_not_exposed():
    explanation = Explanation(lambda eid, hid, parent: ProviderResult(
        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION, success=True,
        evidence=[explanation_candidate(eid, hadith_id="OTHER", hadith_text="حديث آخر")]))
    result, explanation = retrieve(interpretation_claim(), [parent_candidate("H1")], explanation)
    dependent_result = next(item for item in result.provider_results
                            if item.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION)
    assert dependent_result.evidence == [] and not dependent_result.success
    assert result.dependency_trace[-1].status == DependencyStatus.EXPLANATION_IDENTITY_MISMATCH
    assert result.retrieval_status == RetrievalStatus.PARTIAL


def test_same_explanation_id_for_two_aligned_records_is_fetched_once():
    parents = [parent_candidate("H1", explanation_id="X1", scholar="A"),
               parent_candidate("H2", hadith_id="H1", explanation_id="X1", scholar="B")]
    result, explanation = retrieve(interpretation_claim(), parents)
    assert len(explanation.calls) == 1
    assert sum(trace.status == DependencyStatus.DUPLICATE_EXPLANATION_SKIPPED
               for trace in result.dependency_trace) == 1
    dependent = next(item for provider in result.provider_results
                     if provider.provider == EvidenceProvider.DORAR_HADITH_EXPLANATION
                     for item in provider.evidence)
    assert dependent.parent_evidence_id in {"dorar-hadith:H1", "dorar-hadith:H2"}


@pytest.mark.parametrize("error_type", [
    ProviderErrorType.TIMEOUT, ProviderErrorType.NETWORK_ERROR,
    ProviderErrorType.ACCESS_DENIED, ProviderErrorType.NO_RESULTS,
])
def test_dependent_provider_failure_or_empty_result_preserves_parent(error_type):
    explanation = Explanation(lambda eid, hid, parent: ProviderResult(
        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION, success=False,
        error=ProviderError(provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                            error_type=error_type, message=error_type.value)))
    result, explanation = retrieve(interpretation_claim(), [parent_candidate("H1")], explanation)
    assert len(explanation.calls) == 1
    parents = [item for provider in result.provider_results
               if provider.provider == EvidenceProvider.DORAR_HADITH for item in provider.evidence]
    assert [item.evidence_id for item in parents] == ["dorar-hadith:H1"]
    assert result.retrieval_status == RetrievalStatus.PARTIAL
    expected = DependencyStatus.NO_RESULTS if error_type == ProviderErrorType.NO_RESULTS else DependencyStatus.PROVIDER_FAILURE
    assert result.dependency_trace[-1].status == expected


def test_explicit_parent_claim_is_preferred_identity_anchor():
    child = interpretation_claim(include_context=False)
    parent = Claim.model_validate({
        "id": "claim_002", "original_text": TARGET, "normalized_claim": TARGET,
        "claim_type": "HADITH_RECORD", "domain": "HADITH",
        "attributes": [{"type": "HADITH_TEXT", "value": TARGET}],
        "search_queries": ["حديث الدين النصيحة"], "requires_evidence": True,
        "reason": "parent",
    })
    result, explanation = retrieve(child, [parent_candidate("H1")], parent_claim=parent)
    assert len(explanation.calls) == 1
    assert result.dependency_trace[-1].status == DependencyStatus.ACCEPTED


def test_hadith_explanation_reaches_semantic_interpretation_without_automatic_support():
    class Semantic:
        def __init__(self): self.seen = []
        def validate(self, attribute, candidates):
            self.seen.append((attribute, candidates))
            return SemanticValidationOutput(
                status=AttributeValidationStatus.PARTIAL,
                supporting_evidence_ids=[candidates[0].evidence_id],
                rationale="The supplied explanation establishes only part of the proposition.",
                confidence=0.8)
    semantic = Semantic()
    candidate = explanation_candidate()
    candidate.parent_evidence_id = "dorar-hadith:H1"
    candidate.target_attribute_ids = ["attr_001"]
    claim = interpretation_claim(extra_attributes=[
        {"id": "attr_002", "type": "AUTHENTICITY", "value": "claimed grade"}])
    validation = EvidenceValidationService(semantic).validate(claim, [candidate])
    assert semantic.seen[0][1][0].text == "Exact retrieved explanation"
    assert validation.validations[0].status == AttributeValidationStatus.PARTIAL
    assert validation.validations[0].validation_method == "semantic"
    assert validation.validations[0].status != AttributeValidationStatus.SUPPORTED
    authenticity = next(item for item in validation.validations
                        if item.attribute_type.value == "AUTHENTICITY")
    assert authenticity.status == AttributeValidationStatus.NOT_FOUND
    assert authenticity.evidence_ids == []
