from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.agents.claim_extractor import ClaimExtractor, SYSTEM_PROMPT
from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.validation import AttributeValidationStatus, SemanticValidationOutput
from app.retrieval.router import create_retrieval_plan
from app.validation.service import EvidenceValidationService
from conftest import FakeClient, valid_result


MIXED_INPUT = (
    "قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الفلق. "
    "وتدل الآية على توحيد الله سبحانه وتعالى ونفي الشريك عنه. "
    "وقال النبي صلى الله عليه وسلم: «إنما الأعمال بالنيات»، رواه أبو هريرة رضي الله عنه "
    "في صحيح البخاري، ومعنى الحديث أن قبول العمل مرتبط بالنية. "
    "ومن الأحكام الفقهية أن صلاة الوتر واجبة عند المذهب الحنفي. "
    "ومن مسائل العقيدة أن الإيمان بالملائكة من أركان الإيمان. "
    "ووقعت غزوة بدر الكبرى في السنة الثانية للهجرة."
)


def raw_claim(identifier, text, claim_type, domain, attributes, *, parent=None,
              relationship=None, asserted_by=None):
    prepared = []
    for attribute_type, value in attributes:
        item = {"type": attribute_type, "value": value, "requires_evidence": True}
        if asserted_by:
            item["asserted_by"] = asserted_by
        prepared.append(item)
    return {
        "id": identifier,
        "original_text": text,
        "normalized_claim": text,
        "claim_type": claim_type,
        "domain": domain,
        "attributes": prepared,
        "search_queries": [f"{text} دليل"],
        "entities": [],
        "parent_claim_id": parent,
        "relationship": relationship,
        "requires_evidence": True,
        "reason": "An externally verifiable proposition.",
    }


def history(identifier="claim_001", event="غزوة بدر الكبرى", date=None):
    attributes = [("OTHER", event)]
    if date:
        attributes.append(("DATE", date))
    text = event if not date else f"وقعت {event} في {date}"
    return raw_claim(identifier, text, "ISLAMIC_HISTORY", "HISTORY", attributes)


def aqeedah(asserted_by=None):
    text = "الإيمان بالملائكة من أركان الإيمان"
    return Claim.model_validate(raw_claim(
        "claim_001", text, "AQEEDAH", "AQEEDAH", [("OTHER", text)],
        asserted_by=asserted_by,
    ))


def evidence(identifier, text, *, title=None):
    return EvidenceCandidate(
        evidence_id=identifier,
        claim_id="claim_001",
        provider=EvidenceProvider.DORAR_AQEEDA,
        evidence_type=EvidenceType.AQEEDA_CONTENT,
        title=title,
        text=text,
        retrieved_at=datetime.now(timezone.utc),
    )


class Semantic:
    def __init__(self, status):
        self.status = status
        self.calls = []

    def validate(self, attribute, candidates):
        self.calls.append(candidates)
        identifier = candidates[0].evidence_id
        return SemanticValidationOutput(
            status=self.status,
            supporting_evidence_ids=[identifier] if self.status == AttributeValidationStatus.SUPPORTED else [],
            contradicting_evidence_ids=[identifier] if self.status == AttributeValidationStatus.CONTRADICTED else [],
            rationale="Verdict is based only on aligned evidence.",
            confidence=.9,
        )


def test_prompt_requires_final_history_coverage_and_aqeedah_attributes():
    assert "final sentence" in SYSTEM_PROMPT
    assert "Islamic History" in SYSTEM_PROMPT
    assert "generic Aqeedah proposition" in SYSTEM_PROMPT
    assert "TEXT or OTHER" in SYSTEM_PROMPT


def test_empty_evidence_attributes_are_rejected_and_extractor_retries(settings):
    invalid = raw_claim("claim_001", "الإيمان بالملائكة من أركان الإيمان",
                        "AQEEDAH", "AQEEDAH", [])
    with pytest.raises(ValidationError, match="Aqeedah claims must contain at least one verifiable attribute"):
        Claim.model_validate(invalid)
    valid = raw_claim("claim_001", "الإيمان بالملائكة من أركان الإيمان",
                      "AQEEDAH", "AQEEDAH",
                      [("OTHER", "الإيمان بالملائكة من أركان الإيمان")])
    client = FakeClient([valid_result([invalid], "ar"), valid_result([valid], "ar")])
    result = ClaimExtractor(settings, client).extract(valid["original_text"])
    assert len(client.messages.calls) == 2
    assert result.claims[0].attributes[0].type.value == "OTHER"


@pytest.mark.parametrize("case,claims,expected", [
    ("H1", [history(date="2 هـ")], ["غزوة بدر الكبرى"]),
    ("H2", [raw_claim("claim_001", "صلاة الوتر واجبة عند الحنفية", "FIQH_RULING", "FIQH",
                       [("RULING", "واجبة")]), history("claim_002", date="2 هـ")],
     ["صلاة الوتر واجبة عند الحنفية", "غزوة بدر الكبرى"]),
    ("H3", [history(date="2 هـ"), raw_claim("claim_002", "الإيمان بالملائكة من أركان الإيمان",
                                             "AQEEDAH", "AQEEDAH", [("OTHER", "الإيمان بالملائكة")])],
     ["غزوة بدر الكبرى", "الإيمان بالملائكة من أركان الإيمان"]),
    ("H4", [history(), history("claim_002", "فتح مكة", "8 هـ")],
     ["غزوة بدر الكبرى", "فتح مكة"]),
    ("H5", [history()], ["غزوة بدر الكبرى"]),
    ("H6", [history(date="2 هـ")], ["غزوة بدر الكبرى"]),
])
def test_history_extraction_coverage_matrix(settings, case, claims, expected):
    text = ". ".join(item["original_text"] for item in claims)
    result = ClaimExtractor(settings, FakeClient([valid_result(claims, "ar")])).extract(text)
    history_claims = [item for item in result.claims if item.domain.value == "HISTORY"]
    assert len(result.claims) == len(claims)
    assert all(any(value in item.normalized_claim for item in result.claims) for value in expected)
    assert all(any(attr.type.value in {"TEXT", "OTHER"} for attr in item.attributes)
               for item in history_claims)
    if case == "H5":
        assert not any(attr.type.value == "DATE" for attr in history_claims[0].attributes)
    if case == "H6":
        dates = [attr.value for attr in history_claims[0].attributes if attr.type.value == "DATE"]
        assert dates == ["2 هـ"]
        assert not any("624" in value for value in dates)


@pytest.mark.parametrize("case,status", [
    ("A2", AttributeValidationStatus.SUPPORTED),
    ("A3", AttributeValidationStatus.CONTRADICTED),
])
def test_aligned_aqeedah_can_reach_semantic_verdict(case, status):
    semantic = Semantic(status)
    item = evidence("aqeeda:aligned", "الإيمان بالملائكة من أركان الإيمان",
                    title="الإيمان بالملائكة من أركان الإيمان")
    result = EvidenceValidationService(semantic).validate(aqeedah(), [item])
    assert result.validations[0].status == status
    assert len(semantic.calls) == 1


def test_aqeedah_is_routable_and_not_skipped_without_evidence():
    claim = aqeedah()
    response = EvidenceValidationService().validate(claim, [])
    plan = create_retrieval_plan(claim)
    assert response.validation_status.value != "SKIPPED"
    assert response.validations[0].status == AttributeValidationStatus.NOT_FOUND
    assert [source.provider for source in plan.sources] == [EvidenceProvider.DORAR_AQEEDA]
    assert plan.tasks[0].target_attribute_ids == ["attr_001"]


@pytest.mark.parametrize("case,item,expected", [
    ("A4", evidence("related", "الملائكة مخلوقات نورانية", title="الملائكة"),
     AttributeValidationStatus.NOT_FOUND),
    ("A5", evidence("unrelated", "أحكام الإجارة التجارية", title="الإجارة"),
     AttributeValidationStatus.NOT_FOUND),
])
def test_related_or_unrelated_aqeedah_does_not_auto_support(case, item, expected):
    semantic = Semantic(AttributeValidationStatus.SUPPORTED)
    result = EvidenceValidationService(semantic).validate(aqeedah(), [item])
    assert result.validations[0].status == expected
    assert semantic.calls == []


def test_aqeedah_attribution_alignment_matrix():
    claim = aqeedah(asserted_by="العالم س")
    semantic = Semantic(AttributeValidationStatus.SUPPORTED)
    generic = evidence("generic", "الإيمان بالملائكة من أركان الإيمان",
                       title="الإيمان بالملائكة")
    same = evidence("same", "العالم س: الإيمان بالملائكة من أركان الإيمان",
                    title="العالم س والإيمان بالملائكة")
    other = evidence("other", "العالم ص: الإيمان بالملائكة ليس من أركان الإيمان",
                     title="العالم ص والإيمان بالملائكة")
    a6_generic = EvidenceValidationService(semantic).validate(claim, [generic]).validations[0]
    assert a6_generic.status == AttributeValidationStatus.UNCERTAIN
    assert semantic.calls == []
    a6_explicit = EvidenceValidationService(semantic).validate(claim, [same]).validations[0]
    assert a6_explicit.status == AttributeValidationStatus.SUPPORTED
    assert len(semantic.calls) == 1
    a7 = EvidenceValidationService(semantic).validate(claim, [other]).validations[0]
    assert a7.status != AttributeValidationStatus.CONTRADICTED
    assert len(semantic.calls) == 1


def test_exact_mixed_input_extracts_seven_independent_routable_claims(settings):
    claims = [
        raw_claim("claim_001", "قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الفلق",
                  "QURAN_RECORD", "QURAN", [("QURAN_TEXT", "قُلْ هُوَ اللَّهُ أَحَدٌ"),
                                              ("SURAH", "الفلق"), ("AYAH_NUMBER", "1")]),
        raw_claim("claim_002", "وتدل الآية على توحيد الله سبحانه وتعالى ونفي الشريك عنه",
                  "QURAN_INTERPRETATION", "QURAN", [("INTERPRETATION", "توحيد الله ونفي الشريك عنه")],
                  parent="claim_001", relationship="INTERPRETS"),
        raw_claim("claim_003", "وقال النبي صلى الله عليه وسلم: «إنما الأعمال بالنيات»، رواه أبو هريرة رضي الله عنه في صحيح البخاري",
                  "HADITH_RECORD", "HADITH", [("HADITH_TEXT", "إنما الأعمال بالنيات"),
                                                ("NARRATOR", "أبو هريرة"), ("SOURCE", "صحيح البخاري")]),
        raw_claim("claim_004", "ومعنى الحديث أن قبول العمل مرتبط بالنية",
                  "HADITH_INTERPRETATION", "HADITH", [("INTERPRETATION", "قبول العمل مرتبط بالنية")],
                  parent="claim_003", relationship="INTERPRETS"),
        raw_claim("claim_005", "ومن الأحكام الفقهية أن صلاة الوتر واجبة عند المذهب الحنفي",
                  "FIQH_RULING", "FIQH", [("RULING", "صلاة الوتر واجبة")], asserted_by="المذهب الحنفي"),
        raw_claim("claim_006", "ومن مسائل العقيدة أن الإيمان بالملائكة من أركان الإيمان",
                  "AQEEDAH", "AQEEDAH", [("OTHER", "الإيمان بالملائكة من أركان الإيمان")]),
        history("claim_007", date="2 هـ"),
    ]
    claims[-1]["original_text"] = "ووقعت غزوة بدر الكبرى في السنة الثانية للهجرة"
    claims[-1]["normalized_claim"] = claims[-1]["original_text"]
    result = ClaimExtractor(settings, FakeClient([valid_result(claims, "ar")])).extract(MIXED_INPUT)
    assert result.claim_count == 7
    assert [item.domain.value for item in result.claims] == [
        "QURAN", "QURAN", "HADITH", "HADITH", "FIQH", "AQEEDAH", "HISTORY",
    ]
    assert result.claims[1].parent_claim_id == "claim_001"
    assert result.claims[3].parent_claim_id == "claim_003"
    assert all(item.parent_claim_id is None for item in result.claims[4:])
    for index, provider in ((5, EvidenceProvider.DORAR_AQEEDA),
                            (6, EvidenceProvider.DORAR_HISTORY)):
        plan = create_retrieval_plan(result.claims[index])
        assert [source.provider for source in plan.sources] == [provider]
        assert plan.tasks[0].target_attribute_ids


def test_claim_count_is_derived_when_absent_or_wrong(settings):
    claims = [history(f"claim_{index:03d}", event=f"حدث تاريخي {index}")
              for index in range(1, 8)]
    absent = {"input_language": "ar", "claims": claims}
    wrong = {"input_language": "ar", "claim_count": 99, "claims": claims}
    for payload in (absent, wrong):
        client = FakeClient([payload])
        result = ClaimExtractor(settings, client).extract("سبعة أحداث تاريخية مستقلة")
        assert result.claim_count == len(result.claims) == 7
        assert len(client.messages.calls) == 1


def test_public_extraction_result_retains_derived_count_compatibility(settings):
    payload = {"input_language": "ar", "claims": [history()]}
    result = ClaimExtractor(settings, FakeClient([payload])).extract("غزوة بدر الكبرى")
    assert result.model_dump()["claim_count"] == len(result.claims) == 1


def test_six_claim_fixture_cannot_hide_missing_history(settings):
    six = [
        raw_claim("claim_001", "نص قرآني", "QURAN_TEXT", "QURAN", [("QURAN_TEXT", "نص قرآني")]),
        raw_claim("claim_002", "تفسير قرآني", "QURAN_INTERPRETATION", "QURAN",
                  [("INTERPRETATION", "تفسير قرآني")], parent="claim_001", relationship="INTERPRETS"),
        raw_claim("claim_003", "نص حديث", "HADITH_TEXT", "HADITH", [("HADITH_TEXT", "نص حديث")]),
        raw_claim("claim_004", "معنى الحديث", "HADITH_INTERPRETATION", "HADITH",
                  [("INTERPRETATION", "معنى الحديث")], parent="claim_003", relationship="INTERPRETS"),
        raw_claim("claim_005", "حكم فقهي", "FIQH_RULING", "FIQH", [("RULING", "حكم فقهي")]),
        raw_claim("claim_006", "مسألة عقدية", "AQEEDAH", "AQEEDAH", [("OTHER", "مسألة عقدية")]),
    ]
    result = ClaimExtractor(settings, FakeClient([{"input_language": "ar", "claims": six}])).extract(MIXED_INPUT)
    assert result.claim_count == 6
    with pytest.raises(AssertionError):
        assert result.claim_count == 7 and any(item.domain.value == "HISTORY" for item in result.claims)


def test_genuinely_malformed_claim_still_retries(settings):
    malformed = history()
    malformed["domain"] = "NOT_A_DOMAIN"
    valid = history()
    client = FakeClient([
        {"input_language": "ar", "claims": [malformed]},
        {"input_language": "ar", "claims": [valid]},
    ])
    result = ClaimExtractor(settings, client).extract("غزوة بدر الكبرى")
    assert result.claim_count == 1
    assert len(client.messages.calls) == 2
