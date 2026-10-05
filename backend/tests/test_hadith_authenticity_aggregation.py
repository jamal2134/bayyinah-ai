from datetime import datetime, timezone

import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate
from app.models.validation import AttributeValidationStatus
from app.validation.deterministic import grade_category
from app.validation.service import EvidenceValidationService


TARGET = "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى"


def claim(grade="صحيح", *, asserted_by=None, all_attributes=False):
    attributes = [
        {"type": "HADITH_TEXT", "value": TARGET},
        {"type": "AUTHENTICITY", "value": grade, "asserted_by": asserted_by},
    ]
    if all_attributes:
        attributes[1:1] = [
            {"type": "NARRATOR", "value": "عمر بن الخطاب"},
            {"type": "SOURCE", "value": "البخاري"},
        ]
    return Claim.model_validate({
        "id": "claim_001", "original_text": f"{TARGET} وهو حديث {grade}",
        "normalized_claim": f"{TARGET} وهو حديث {grade}",
        "claim_type": "HADITH_RECORD", "domain": "HADITH",
        "attributes": attributes, "search_queries": [f"{TARGET} حكم الحديث"],
        "requires_evidence": True, "reason": "Authenticity regression fixture",
    })


def evidence(identifier, grade, *, hadith_id=None, text=TARGET, narrator="عمر بن الخطاب",
             scholar=None, source="صحيح البخاري", page="1", rank=None):
    structured = {
        "hadith_id": hadith_id, "narrator": narrator, "scholar": scholar,
        "source": source, "page_or_number": page, "grade": grade,
    }
    return EvidenceCandidate(
        evidence_id=identifier, claim_id="claim_001", provider="DORAR_HADITH",
        evidence_type="HADITH_JUDGMENT", text=text, narrator=narrator,
        scholar=scholar, judgment=grade, reference=page, page=page,
        provider_record_id=hadith_id, result_rank=rank,
        structured_fields=structured, raw_metadata=dict(structured),
        retrieved_at=datetime.now(timezone.utc),
    )


def authenticity_response(items, *, grade="صحيح", asserted_by=None, all_attributes=False):
    response = EvidenceValidationService().validate(
        claim(grade, asserted_by=asserted_by, all_attributes=all_attributes), items
    )
    result = next(row for row in response.validations
                  if row.attribute_type.value == "AUTHENTICITY")
    return response, result


def test_a1_single_aligned_positive_grade_is_supported():
    _, result = authenticity_response([evidence("positive", "صحيح", hadith_id="H1")])
    assert result.status == AttributeValidationStatus.SUPPORTED


def test_a2_compatible_positive_wording_is_supported():
    _, result = authenticity_response([evidence("positive", "رواية صحيحة", hadith_id="H1")])
    assert result.status == AttributeValidationStatus.SUPPORTED
    assert result.contradicting_evidence_ids == []


def test_a3_explicit_negative_same_target_contradicts():
    _, result = authenticity_response([evidence("negative", "لا يصح إسناده", hadith_id="H1")])
    assert result.status == AttributeValidationStatus.CONTRADICTED
    assert result.contradicting_evidence_ids == ["negative"]


def test_a4_different_record_negative_does_not_conflict_with_positive():
    response, result = authenticity_response([
        evidence("positive", "صحيح", hadith_id="H1"),
        evidence("other-route", "لا يصح إسناده", hadith_id="H2"),
    ])
    assert result.status == AttributeValidationStatus.SUPPORTED
    assert result.supporting_evidence_ids == ["positive"]
    assert result.contradicting_evidence_ids == []
    excluded = next(row for row in response.authenticity_audit
                    if row["evidence_id"] == "other-route")
    assert excluded["eligible"] is False
    assert excluded["grade_category"] == "NEGATIVE"


def test_a5_genuine_same_target_disagreement_is_preserved():
    _, result = authenticity_response([
        evidence("positive", "صحيح", hadith_id="H1", scholar="A"),
        evidence("negative", "ضعيف", hadith_id="H1", scholar="B"),
    ])
    assert result.status == AttributeValidationStatus.UNCERTAIN
    assert result.supporting_evidence_ids == ["positive"]
    assert result.contradicting_evidence_ids == ["negative"]


@pytest.mark.parametrize("grade", ["صحيح", "ضعيف"])
def test_a6_a7_unrelated_grade_cannot_support_or_contradict(grade):
    _, result = authenticity_response([
        evidence("unrelated", grade, hadith_id="OTHER", text="الدين النصيحة")
    ])
    assert result.status == AttributeValidationStatus.NOT_FOUND
    assert result.supporting_evidence_ids == result.contradicting_evidence_ids == []


def test_a8_unresolved_record_cannot_support_or_contradict():
    _, result = authenticity_response([
        evidence("unresolved", "صحيح", hadith_id="OTHER", text="إنما الأعمال بالنيات")
    ])
    assert result.status == AttributeValidationStatus.NOT_FOUND
    assert result.supporting_evidence_ids == result.contradicting_evidence_ids == []


@pytest.mark.parametrize("grade", ["لا يصح", "ليس بصحيح", "إسناده لا يصح"])
def test_a9_negative_phrases_never_normalize_positive(grade):
    assert grade_category(grade) == "NEGATIVE"
    _, result = authenticity_response([evidence("negative", grade, hadith_id="H1")])
    assert result.status == AttributeValidationStatus.CONTRADICTED


@pytest.mark.parametrize("grade", ["غريب", "غريب من هذا الوجه"])
def test_a10_qualified_gharib_is_not_automatic_weakness(grade):
    assert grade_category(grade) == "MIXED_OR_QUALIFIED"
    _, result = authenticity_response([evidence("qualified", grade, hadith_id="H1")])
    assert result.status == AttributeValidationStatus.NOT_FOUND
    assert result.contradicting_evidence_ids == []


def test_a11_a12_scholar_attribution_requires_matching_scholar():
    _, wrong = authenticity_response(
        [evidence("y", "صحيح", hadith_id="H1", scholar="العالم Y")],
        asserted_by="العالم X",
    )
    _, matching = authenticity_response(
        [evidence("x", "صحيح", hadith_id="H1", scholar="العالم X")],
        asserted_by="العالم X",
    )
    assert wrong.status == AttributeValidationStatus.UNCERTAIN
    assert wrong.supporting_evidence_ids == []
    assert matching.status == AttributeValidationStatus.SUPPORTED


def test_a13_a14_a15_order_duplicate_and_rank_invariance():
    base = [
        evidence("positive", "صحيح", hadith_id="H1", rank=9),
        evidence("negative", "ضعيف", hadith_id="H1", rank=1),
    ]
    _, first = authenticity_response(base)
    _, reordered = authenticity_response(list(reversed(base)))
    _, duplicated = authenticity_response(base + [
        evidence("positive-copy", "صحيح", hadith_id="H1", rank=1)
    ])
    reranked = [item.model_copy(update={"result_rank": 10 - (item.result_rank or 0)})
                for item in base]
    _, changed_ranks = authenticity_response(reranked)
    assert {first.status, reordered.status, duplicated.status, changed_ranks.status} == {
        AttributeValidationStatus.UNCERTAIN
    }


def test_real_regression_uses_record_specific_grade_provenance():
    items = [
        evidence("bukhari", "صحيح", hadith_id="H1", scholar="البخاري"),
        evidence("ayni", "رواية صحيحة", hadith_id="H1", scholar="العيني"),
        evidence("zarqani", "صحيح", hadith_id="H1", scholar="الزرقاني"),
        evidence("ibn-hajar-route", "لا يصح لها إسناد، وهو وهم",
                 hadith_id="H2", scholar="ابن حجر العسقلاني", page="route-2"),
    ]
    response, result = authenticity_response(items, all_attributes=True)
    by_type = {row.attribute_type.value: row for row in response.validations}
    assert by_type["HADITH_TEXT"].status == AttributeValidationStatus.SUPPORTED
    assert by_type["NARRATOR"].status == AttributeValidationStatus.SUPPORTED
    assert by_type["SOURCE"].status == AttributeValidationStatus.SUPPORTED
    assert result.status == AttributeValidationStatus.SUPPORTED
    assert set(result.supporting_evidence_ids) == {"bukhari", "ayni", "zarqani"}
    assert result.contradicting_evidence_ids == []
    assert {row["evidence_id"] for row in response.authenticity_audit} == {
        "bukhari", "ayni", "zarqani", "ibn-hajar-route"
    }


def test_wrong_authenticity_claim_is_contradicted_by_aligned_positive_record():
    _, result = authenticity_response(
        [evidence("positive", "صحيح", hadith_id="H1")], grade="موضوع"
    )
    assert result.status == AttributeValidationStatus.CONTRADICTED
    assert result.supporting_evidence_ids == []
