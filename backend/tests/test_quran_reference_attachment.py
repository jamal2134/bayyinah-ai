from app.agents.claim_extractor import (
    attach_quran_reference_continuations, link_explicit_interpretations,
)
from app.models.claim import Claim, ClaimType


def claim(identifier, text, attributes, *, domain="QURAN", claim_type="QURAN_REFERENCE",
          normalized=None):
    return Claim.model_validate({
        "id": identifier,
        "original_text": text,
        "normalized_claim": normalized or text,
        "claim_type": claim_type,
        "domain": domain,
        "search_queries": ["مرجع ديني مطلوب"],
        "attributes": attributes,
        "requires_evidence": True,
        "reason": "Structured extraction test.",
    })


def quotation(identifier="claim_001", text="﴿قُلْ هُوَ اللَّهُ أَحَدٌ اللَّهُ الصَّمَدُ﴾"):
    return claim(identifier, text, [{"type": "QURAN_TEXT", "value": "قل هو الله أحد الله الصمد"}],
                 claim_type="QURAN_TEXT")


def reference(identifier, text, surah="الإخلاص", *, ayah=1, end=None):
    verse = ({"type": "AYAH_NUMBER", "value": str(ayah)} if end is None else
             {"type": "AYAH_RANGE", "value": f"{ayah}-{end}",
              "ayah_numbers": list(range(ayah, end + 1))})
    normalized = f"الآية {ayah if end is None else f'{ayah}-{end}'} من سورة {surah}"
    return claim(identifier, text, [{"type": "SURAH", "value": surah}, verse],
                 normalized=normalized)


def test_quotation_and_reference_same_sentence_remain_one_quran_claim():
    item = claim("claim_001", "﴿إن مع العسر يسرا﴾، وهي الآية رقم 6 من سورة الشرح",
                 [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"},
                  {"type": "SURAH", "value": "الشرح"},
                  {"type": "AYAH_NUMBER", "value": "6"}], claim_type="QURAN_RECORD")
    assert attach_quran_reference_continuations([item]) == [item]


def test_reference_continuation_attaches_to_previous_quotation():
    output = attach_quran_reference_continuations([
        quotation(), reference("claim_002", "وهي الآية رقم 1 من سورة الإخلاص"),
    ])
    assert len(output) == 1
    assert {a.type.value for a in output[0].attributes} == {"QURAN_TEXT", "SURAH", "AYAH_NUMBER"}


def test_multi_verse_range_continuation_attaches_once():
    output = attach_quran_reference_continuations([
        quotation(), reference("claim_002", "وهما الآيتان الأولى والثانية من سورة الإخلاص",
                               ayah=1, end=2),
    ])
    assert len(output) == 1
    assert next(a.ayah_numbers for a in output[0].attributes if a.type.value == "AYAH_RANGE") == [1, 2]


def test_wrong_reference_attaches_without_factual_correction():
    output = attach_quran_reference_continuations([
        quotation(), reference("claim_002", "وهما الآيتان الأولى والثانية من سورة الفلق",
                               surah="الفلق", ayah=1, end=2),
    ])
    assert len(output) == 1
    assert next(a.value for a in output[0].attributes if a.type.value == "SURAH") == "الفلق"


def test_interpretation_after_reference_remains_separate_child():
    parent = attach_quran_reference_continuations([
        quotation(), reference("claim_002", "وهما الآيتان الأولى والثانية من سورة الإخلاص",
                               ayah=1, end=2),
    ])[0]
    interpretation = claim("claim_003", "وتدل الآيات على وحدانية الله",
                           [{"type": "INTERPRETATION", "value": "وحدانية الله"}],
                           domain="GENERAL", claim_type="GENERAL_ISLAMIC_CLAIM")
    output = link_explicit_interpretations([parent, interpretation])
    assert len(output) == 2
    assert output[1].claim_type == ClaimType.QURAN_INTERPRETATION
    assert output[1].parent_claim_id == parent.id


def test_existing_parent_link_gets_missing_reference_context_enriched():
    parent = claim("claim_001", "﴿إن مع العسر يسرا﴾ وهي الآية 6 من سورة الشرح",
                   [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"},
                    {"type": "SURAH", "value": "الشرح"},
                    {"type": "AYAH_NUMBER", "value": "6"}], claim_type="QURAN_RECORD")
    child = Claim.model_validate({
        "id": "claim_002", "original_text": "ومن معانيها أن مع الضيق فرجًا",
        "normalized_claim": "مع الضيق فرجًا", "claim_type": "QURAN_INTERPRETATION",
        "domain": "QURAN", "search_queries": ["تفسير الشرح المطلوب"],
        "attributes": [{"type": "INTERPRETATION", "value": "مع الضيق فرجًا"}],
        "parent_claim_id": "claim_001", "relationship": "INTERPRETS",
        "subject_context": {"type": "QURAN", "text": "إن مع العسر يسرا"},
        "requires_evidence": True, "reason": "Interpretation.",
    })
    enriched = link_explicit_interpretations([parent, child])[1]
    assert enriched.subject_context.surah == "الشرح"
    assert enriched.subject_context.ayah_number == "6"


def test_second_independent_quran_quotation_is_not_merged():
    output = attach_quran_reference_continuations([quotation(), quotation("claim_002", "﴿إن مع العسر يسرا﴾")])
    assert len(output) == 2


def test_hadith_after_quran_is_not_merged():
    hadith = claim("claim_002", "قال النبي ﷺ: «الدين النصيحة»",
                   [{"type": "HADITH_TEXT", "value": "الدين النصيحة"}],
                   domain="HADITH", claim_type="HADITH_RECORD")
    assert len(attach_quran_reference_continuations([quotation(), hadith])) == 2


def test_conflicting_continuation_is_preserved_with_warning():
    parent = claim("claim_001", "﴿إن مع العسر يسرا﴾ وهي الآية 6 من سورة الشرح",
                   [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"},
                    {"type": "SURAH", "value": "الشرح"},
                    {"type": "AYAH_NUMBER", "value": "6"}], claim_type="QURAN_RECORD")
    conflicting = reference("claim_002", "وهي الآية 5 من سورة الشرح", surah="الشرح", ayah=5)
    merged = attach_quran_reference_continuations([parent, conflicting])[0]
    assert [a.value for a in merged.attributes if a.type.value == "AYAH_NUMBER"] == ["6", "5"]
    assert any("Conflicting Quran reference" in warning for warning in merged.normalization_warnings)


def test_valid_al_ikhlas_reference_is_preserved():
    merged = attach_quran_reference_continuations([
        quotation(), reference("claim_002", "وهاتان الآيتان من سورة الإخلاص", ayah=1, end=2),
    ])[0]
    assert [(a.type.value, a.value) for a in merged.attributes] == [
        ("QURAN_TEXT", "قل هو الله أحد الله الصمد"), ("SURAH", "الإخلاص"), ("AYAH_RANGE", "1-2")]


def test_ash_sharh_single_verse_reference_is_preserved():
    quote = claim("claim_001", "﴿إن مع العسر يسرا﴾",
                  [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"}], claim_type="QURAN_TEXT")
    merged = attach_quran_reference_continuations([
        quote, reference("claim_002", "وهي الآية رقم 6 من سورة الشرح", surah="الشرح", ayah=6),
    ])[0]
    assert [(a.type.value, a.value) for a in merged.attributes] == [
        ("QURAN_TEXT", "إن مع العسر يسرا"), ("SURAH", "الشرح"), ("AYAH_NUMBER", "6")]
