import asyncio

from app.agents.claim_extractor import ClaimExtractor, link_explicit_interpretations
from app.config.settings import Settings
from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.models.claim import Claim
from app.models.retrieval import RetrievalStatus
from app.models.validation import EvidenceValidationResponse
from app.retrieval.query_selector import select_queries
from app.retrieval.service import RetrievalService
from app.validation.service import EvidenceValidationService
from conftest import FakeClient, valid_result


MIXED_CONTENT = """قال الله تعالى: ﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ﴾، وهي بداية آية الكرسي، الآية رقم 255 من سورة البقرة.

وتدل الآية على توحيد الله سبحانه وتعالى، وأنه الحي الذي له كمال الحياة، والقيوم القائم بنفسه والقائم على شؤون خلقه.

وقال النبي ﷺ: «إنما الأعمال بالنيات، وإنما لكل امرئ ما نوى»، وقد رواه البخاري عن عمر بن الخطاب رضي الله عنه، وهو حديث صحيح.

ومن معاني الحديث أن قيمة العمل وقبوله يرتبطان بالنية، وأن الإنسان يُجازى بحسب ما قصده بعمله."""


def make_claim(identifier, text, claim_type, domain, attributes, **extra):
    return Claim.model_validate({
        "id": identifier, "original_text": text, "normalized_claim": text,
        "claim_type": claim_type, "domain": domain, "search_queries": [text],
        "entities": [], "attributes": attributes, "requires_evidence": True,
        "reason": "Externally verifiable proposition.", **extra,
    })


def test_explicit_quran_context_normalizes_wrong_hadith_attribute():
    item = make_claim("claim_001", "قال الله تعالى: ﴿الله لا إله إلا هو الحي القيوم﴾",
        "QURAN_RECORD", "QURAN", [{"type": "HADITH_TEXT", "value": "الله لا إله إلا هو الحي القيوم"}])
    assert [a.type.value for a in item.attributes] == ["QURAN_TEXT"]
    assert item.normalization_warnings


def test_explicit_hadith_context_normalizes_wrong_quran_attribute():
    item = make_claim("claim_001", "قال النبي ﷺ: «إنما الأعمال بالنيات»",
        "HADITH_RECORD", "HADITH", [{"type": "QURAN_TEXT", "value": "إنما الأعمال بالنيات"}])
    assert [a.type.value for a in item.attributes] == ["HADITH_TEXT"]


def test_quran_reference_keeps_structured_identifiers():
    item = make_claim("claim_001", "آية الكرسي هي الآية 255 من سورة البقرة.",
        "QURAN_RECORD", "QURAN", [
            {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}])
    assert {(a.type.value, a.value) for a in item.attributes} == {("SURAH", "البقرة"), ("AYAH_NUMBER", "255")}


def test_explicit_quran_and_hadith_explanations_link_to_matching_parents():
    quran = make_claim("claim_001", "قال الله تعالى: ﴿الله لا إله إلا هو الحي القيوم﴾",
        "QURAN_RECORD", "QURAN", [
            {"type": "QURAN_TEXT", "value": "الله لا إله إلا هو الحي القيوم"},
            {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}])
    tafsir = make_claim("claim_002", "وتدل الآية على توحيد الله.",
        "GENERAL_ISLAMIC_CLAIM", "GENERAL", [{"type": "OTHER", "value": "توحيد الله"}])
    hadith = make_claim("claim_003", "قال النبي ﷺ: «إنما الأعمال بالنيات».",
        "HADITH_RECORD", "HADITH", [{"type": "HADITH_TEXT", "value": "إنما الأعمال بالنيات"}])
    explanation = make_claim("claim_004", "ومن معاني الحديث أن العمل يرتبط بالنية.",
        "GENERAL_ISLAMIC_CLAIM", "GENERAL", [{"type": "OTHER", "value": "العمل يرتبط بالنية"}])
    linked = link_explicit_interpretations([quran, tafsir, hadith, explanation])
    assert linked[1].claim_type.value == "QURAN_INTERPRETATION"
    assert linked[1].parent_claim_id == quran.id
    assert linked[1].subject_context.surah == "البقرة"
    assert linked[1].subject_context.ayah_number == "255"
    assert linked[1].subject_context.text == "الله لا إله إلا هو الحي القيوم"
    assert linked[1].attributes[0].type.value == "INTERPRETATION"
    assert linked[1].attributes[0].requires_evidence is True
    assert linked[3].claim_type.value == "HADITH_INTERPRETATION"
    assert linked[3].parent_claim_id == hadith.id
    assert linked[3].subject_context.text == "إنما الأعمال بالنيات"
    assert linked[3].attributes[0].type.value == "INTERPRETATION"
    assert linked[3].attributes[0].requires_evidence is True
    assert "إنما الأعمال بالنيات" in select_queries(linked[3], 1)[0]


def test_ambiguous_adjacent_claim_is_not_force_linked():
    parent = make_claim("claim_001", "قال الله تعالى آية كريمة.", "QURAN_RECORD", "QURAN",
                        [{"type": "QURAN_TEXT", "value": "آية كريمة"}])
    child = make_claim("claim_002", "هذا شرح عام محتمل.", "GENERAL_ISLAMIC_CLAIM", "GENERAL",
                       [{"type": "OTHER", "value": "شرح عام"}])
    assert link_explicit_interpretations([parent, child])[1].parent_claim_id is None


def test_parent_context_avoids_missing_context_but_has_no_commentary_provider():
    parent = make_claim("claim_001", "آية من البقرة 255", "QURAN_RECORD", "QURAN", [
        {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}])
    child = make_claim("claim_002", "وتدل الآية على معنى.", "GENERAL_ISLAMIC_CLAIM", "GENERAL",
                       [{"type": "OTHER", "value": "معنى"}])
    linked = link_explicit_interpretations([parent, child])[1]
    result = asyncio.run(RetrievalService({}).retrieve(linked))
    assert result.retrieval_status == RetrievalStatus.MISSING_CONTEXT
    assert result.reason == "PARENT_QURAN_REFERENCE_NOT_ALIGNED"
    assert result.retrieval_ready is False


def test_parent_support_and_evidence_do_not_propagate_to_child():
    parent = make_claim("claim_001", "آية من البقرة 255", "QURAN_RECORD", "QURAN", [
        {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}])
    child = make_claim("claim_002", "وتدل الآية على معنى.", "GENERAL_ISLAMIC_CLAIM", "GENERAL",
                       [{"type": "OTHER", "value": "معنى"}])
    linked = link_explicit_interpretations([parent, child])[1]
    retrieval = asyncio.run(RetrievalService({}).retrieve(linked))
    validation = EvidenceValidationService().validate(linked, [], retrieval)
    decision = decide_claim(ClaimDecisionRequest(validation=validation, claim=linked))
    assert all(item.status.value == "NOT_FOUND" for item in validation.validations)
    assert decision.decision.value == "INSUFFICIENT_EVIDENCE"


def test_authenticity_without_explicit_field_remains_not_found():
    hadith = make_claim("claim_001", "حديث إنما الأعمال بالنيات رواه البخاري وهو حديث صحيح", "HADITH_RECORD", "HADITH", [
        {"type": "HADITH_TEXT", "value": "إنما الأعمال بالنيات"},
        {"type": "AUTHENTICITY", "value": "صحيح"}])
    validation = EvidenceValidationService().validate(hadith, [])
    authenticity = next(item for item in validation.validations if item.attribute_type.value == "AUTHENTICITY")
    assert authenticity.status.value == "NOT_FOUND"


def test_full_mixed_content_structure_is_four_independent_linked_claims():
    raw = [
        {"id": "claim_001", "original_text": MIXED_CONTENT.split("\n\n")[0],
         "normalized_claim": "آية الكرسي من سورة البقرة، الآية 255",
         "claim_type": "QURAN_RECORD", "domain": "QURAN", "search_queries": ["سورة البقرة الآية 255"],
         "entities": [], "attributes": [{"type": "HADITH_TEXT", "value": "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ"},
             {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}],
         "requires_evidence": True, "reason": "Quran record."},
        {"id": "claim_002", "original_text": MIXED_CONTENT.split("\n\n")[1],
         "normalized_claim": MIXED_CONTENT.split("\n\n")[1], "claim_type": "GENERAL_ISLAMIC_CLAIM",
         "domain": "GENERAL", "search_queries": ["تفسير آية الكرسي الحي القيوم"], "entities": [],
         "attributes": [{"type": "OTHER", "value": "الحي له كمال الحياة والقيوم قائم على خلقه"}],
         "requires_evidence": True, "reason": "Interpretation."},
        {"id": "claim_003", "original_text": MIXED_CONTENT.split("\n\n")[2],
         "normalized_claim": MIXED_CONTENT.split("\n\n")[2], "claim_type": "HADITH_RECORD", "domain": "HADITH",
         "search_queries": ["حديث إنما الأعمال بالنيات عمر البخاري"], "entities": [],
         "attributes": [{"type": "HADITH_TEXT", "value": "إنما الأعمال بالنيات، وإنما لكل امرئ ما نوى"},
             {"type": "NARRATOR", "value": "عمر بن الخطاب"}, {"type": "SOURCE", "value": "البخاري"},
             {"type": "AUTHENTICITY", "value": "صحيح"}], "requires_evidence": True, "reason": "Hadith record."},
        {"id": "claim_004", "original_text": MIXED_CONTENT.split("\n\n")[3],
         "normalized_claim": MIXED_CONTENT.split("\n\n")[3], "claim_type": "GENERAL_ISLAMIC_CLAIM",
         "domain": "GENERAL", "search_queries": ["شرح حديث إنما الأعمال بالنيات قيمة العمل"], "entities": [],
         "attributes": [{"type": "OTHER", "value": "قيمة العمل وقبوله يرتبطان بالنية"}],
         "requires_evidence": True, "reason": "Interpretation."},
    ]
    extraction = ClaimExtractor(Settings(anthropic_api_key="test"), FakeClient([valid_result(raw, "ar")])).extract(MIXED_CONTENT)
    assert extraction.claim_count == 4
    assert [item.claim_type.value for item in extraction.claims] == [
        "QURAN_RECORD", "QURAN_INTERPRETATION", "HADITH_RECORD", "HADITH_INTERPRETATION"]
    assert extraction.claims[0].attributes[0].type.value == "QURAN_TEXT"
    assert extraction.claims[1].parent_claim_id == "claim_001"
    assert extraction.claims[3].parent_claim_id == "claim_003"
    assert all(item.attributes and all(
        attribute.type.value == "INTERPRETATION" and attribute.requires_evidence
        for attribute in item.attributes)
        for item in (extraction.claims[1], extraction.claims[3]))
