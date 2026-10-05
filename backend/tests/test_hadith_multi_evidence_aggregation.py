from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.validation import AttributeValidationStatus
from app.validation.service import EvidenceValidationService


HADITH_TEXT = "إنما الأعمال بالنيات"


def hadith_claim(attribute_type, value):
    return Claim.model_validate({
        "id": "claim_001",
        "original_text": f"{HADITH_TEXT} {value}",
        "normalized_claim": f"{HADITH_TEXT} {value}",
        "claim_type": "HADITH_RECORD",
        "domain": "HADITH",
        "attributes": [
            {"id": "attr_001", "type": "HADITH_TEXT", "value": HADITH_TEXT},
            {"id": "attr_002", "type": attribute_type, "value": value},
        ],
        "search_queries": [f"{HADITH_TEXT} تخريج"],
        "requires_evidence": True,
        "reason": "Hadith aggregation regression fixture",
    })


def evidence(identifier, *, text=HADITH_TEXT, narrator=None, source=None, rank=None):
    return EvidenceCandidate(
        evidence_id=identifier,
        claim_id="claim_001",
        provider=EvidenceProvider.DORAR_HADITH,
        evidence_type=EvidenceType.HADITH,
        text=text,
        narrator=narrator,
        reference=source,
        result_rank=rank,
        retrieved_at=datetime.now(timezone.utc),
    )


def result(attribute_type, value, candidates):
    response = EvidenceValidationService().validate(
        hadith_claim(attribute_type, value), candidates
    )
    return next(item for item in response.validations if item.attribute_type.value == attribute_type)


def test_h1_aligned_matching_narrator_is_supported():
    assert result("NARRATOR", "عمر بن الخطاب", [
        evidence("umar", narrator="عمر بن الخطاب")
    ]).status == AttributeValidationStatus.SUPPORTED


def test_h2_alternative_narrator_does_not_cancel_matching_support():
    item = result("NARRATOR", "عمر بن الخطاب", [
        evidence("umar", narrator="عمر بن الخطاب"),
        evidence("alternative", narrator="أبو سعيد"),
    ])
    assert item.status == AttributeValidationStatus.SUPPORTED
    assert item.supporting_evidence_ids == ["umar"]
    assert item.contradicting_evidence_ids == []


@pytest.mark.parametrize("alternatives", [
    ["صحيح مسلم"],
    ["صحيح مسلم", "النسائي"],
])
def test_h3_h4_additional_sources_do_not_cancel_bukhari(alternatives):
    candidates = [evidence("bukhari", source="صحيح البخاري")]
    candidates += [evidence(f"alternative-{index}", source=value)
                   for index, value in enumerate(alternatives)]
    item = result("SOURCE", "صحيح البخاري", candidates)
    assert item.status == AttributeValidationStatus.SUPPORTED
    assert item.supporting_evidence_ids == ["bukhari"]
    assert item.contradicting_evidence_ids == []


def test_h5_different_source_without_match_is_not_contradiction():
    item = result("SOURCE", "صحيح البخاري", [evidence("muslim", source="صحيح مسلم")])
    assert item.status == AttributeValidationStatus.NOT_FOUND
    assert item.contradicting_evidence_ids == []


def test_h6_wrong_narrator_is_not_supported_by_aligned_umar_record():
    item = result("NARRATOR", "أبو هريرة", [evidence("umar", narrator="عمر بن الخطاب")])
    assert item.status == AttributeValidationStatus.NOT_FOUND
    assert item.supporting_evidence_ids == item.contradicting_evidence_ids == []


@pytest.mark.parametrize("other_text", [
    "الدين النصيحة",
    "إنما الأعمال بالنية",
])
def test_h7_h8_unrelated_or_unresolved_record_cannot_support(other_text):
    item = result("NARRATOR", "عمر بن الخطاب", [
        evidence("not-aligned", text=other_text, narrator="عمر بن الخطاب")
    ])
    assert item.status == AttributeValidationStatus.NOT_FOUND
    assert item.supporting_evidence_ids == item.contradicting_evidence_ids == []


def test_h9_h10_rank_and_order_do_not_change_result():
    candidates = [
        evidence("alternative", narrator="أبو سعيد", rank=1),
        evidence("umar", narrator="عمر بن الخطاب", rank=9),
    ]
    first = result("NARRATOR", "عمر بن الخطاب", candidates)
    second = result("NARRATOR", "عمر بن الخطاب", list(reversed(candidates)))
    assert first.status == second.status == AttributeValidationStatus.SUPPORTED
    assert set(first.supporting_evidence_ids) == set(second.supporting_evidence_ids) == {"umar"}


def test_ui_paginates_filtered_report_sources_without_mutating_report_data():
    script = (Path(__file__).parents[2] / "frontend" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "const EVIDENCE_BATCH_SIZE=4" in script
    assert "r.sources.map((s,index)=>sourceCard(s,r,index>=EVIDENCE_BATCH_SIZE))" in script
    assert "hidden.slice(0,EVIDENCE_BATCH_SIZE)" in script
    assert "r.sources.length-EVIDENCE_BATCH_SIZE" in script
    assert "show-more-evidence\" type=\"button" in script
