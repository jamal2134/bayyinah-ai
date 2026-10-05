from datetime import datetime, timezone

import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate
from app.models.validation import AttributeValidationStatus
from app.validation.evidence_matcher import (
    QuranRecordAlignment, aggregate_quran_alignment, quran_record_alignment,
)
from app.validation.service import EvidenceValidationService


AYAT_AL_KURSI = (
    "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ "
    "لَهُ مَا فِي السَّمَاوَاتِ وَمَا فِي الْأَرْضِ مَنْ ذَا الَّذِي يَشْفَعُ عِنْدَهُ إِلَّا "
    "بِإِذْنِهِ يَعْلَمُ مَا بَيْنَ أَيْدِيهِمْ وَمَا خَلْفَهُمْ وَلَا يُحِيطُونَ بِشَيْءٍ مِنْ "
    "عِلْمِهِ إِلَّا بِمَا شَاءَ وَسِعَ كُرْسِيُّهُ السَّمَاوَاتِ وَالْأَرْضَ وَلَا يَئُودُهُ "
    "حِفْظُهُمَا وَهُوَ الْعَلِيُّ الْعَظِيمُ"
)
REAL_STATEMENT = (
    "قال الله تعالى: ﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ﴾،\n"
    "وهي بداية آية الكرسي، الآية رقم 255 من سورة البقرة."
)


def quran_claim(quote, surah="البقرة", ayah=255, *, original=None):
    return Claim.model_validate({
        "id": "claim_001",
        "original_text": original or f"{quote} سورة {surah} آية {ayah}",
        "normalized_claim": f"{quote} سورة {surah} آية {ayah}",
        "claim_type": "QURAN_RECORD",
        "domain": "QURAN",
        "search_queries": [f"سورة {surah} آية {ayah}"],
        "attributes": [
            {"type": "QURAN_TEXT", "value": quote},
            {"type": "SURAH", "value": surah},
            {"type": "AYAH_NUMBER", "value": str(ayah)},
        ],
        "requires_evidence": True,
        "reason": "Controlled Quran record fixture",
    })


def quran_evidence(text, surah=2, ayah=255, identifier="quran:record"):
    return EvidenceCandidate(
        evidence_id=identifier,
        claim_id="claim_001",
        provider="QURANPEDIA",
        evidence_type="QURAN_AYAH",
        text=text,
        reference=f"{surah}:{ayah}",
        raw_metadata={
            "surah": surah,
            "ayah": ayah,
            "ayah_numbers": [ayah],
            "ayah_texts": [text],
        },
        retrieved_at=datetime.now(timezone.utc),
    )


def statuses(claim, evidence):
    response = EvidenceValidationService().validate(claim, [evidence])
    return response, {item.attribute_type.value: item.status for item in response.validations}


@pytest.mark.parametrize("quote", [
    "الله لا إله إلا هو الحي القيوم",
    "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ",
    "﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ﴾،",
])
def test_q1_q3_q4_q5_ayat_al_kursi_partial_variants_are_supported(quote):
    claim, evidence = quran_claim(quote), quran_evidence(AYAT_AL_KURSI)
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.ALIGNED
    response, result = statuses(claim, evidence)
    assert response.quran_record_alignment == "ALIGNED"
    assert result == {
        "QURAN_TEXT": AttributeValidationStatus.SUPPORTED,
        "SURAH": AttributeValidationStatus.SUPPORTED,
        "AYAH_NUMBER": AttributeValidationStatus.SUPPORTED,
    }


def test_q2_complete_verse_remains_supported():
    response, result = statuses(quran_claim(AYAT_AL_KURSI), quran_evidence(AYAT_AL_KURSI))
    assert response.quran_record_alignment == "ALIGNED"
    assert set(result.values()) == {AttributeValidationStatus.SUPPORTED}


def test_exact_real_statement_regression_is_aligned_and_supported():
    claim = quran_claim(
        "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ",
        original=REAL_STATEMENT,
    )
    evidence = quran_evidence(AYAT_AL_KURSI)
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.ALIGNED
    _, result = statuses(claim, evidence)
    assert set(result.values()) == {AttributeValidationStatus.SUPPORTED}


def test_q6_adversarial_correct_quote_at_wrong_surah_remains_mismatch():
    claim = quran_claim("قُلْ هُوَ اللَّهُ أَحَدٌ", surah="الفلق", ayah=1)
    evidence = quran_evidence("قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ", surah=113, ayah=1)
    response, result = statuses(claim, evidence)
    assert response.quran_record_alignment == "MISMATCH"
    assert set(result.values()) == {AttributeValidationStatus.CONTRADICTED}


def test_q7_correct_quote_at_wrong_ayah_remains_mismatch():
    claim = quran_claim("الله لا إله إلا هو الحي القيوم", ayah=254)
    evidence = quran_evidence(
        "يا أيها الذين آمنوا أنفقوا مما رزقناكم من قبل أن يأتي يوم لا بيع فيه",
        ayah=254,
    )
    response, result = statuses(claim, evidence)
    assert response.quran_record_alignment == "MISMATCH"
    assert set(result.values()) == {AttributeValidationStatus.CONTRADICTED}


def test_q8_wrong_quote_at_correct_reference_is_not_supported():
    claim = quran_claim("قل هو الله أحد")
    response, result = statuses(claim, quran_evidence(AYAT_AL_KURSI))
    assert response.quran_record_alignment == "MISMATCH"
    assert result["QURAN_TEXT"] == AttributeValidationStatus.CONTRADICTED


def test_q9_tiny_generic_fragment_cannot_establish_identity():
    claim, evidence = quran_claim("الله"), quran_evidence(AYAT_AL_KURSI)
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.UNRESOLVED
    assert aggregate_quran_alignment(claim, [evidence]) == QuranRecordAlignment.UNRESOLVED


def test_q10_unrelated_valid_partial_quote_is_supported_generally():
    claim = quran_claim("إنا أعطيناك الكوثر", surah="108", ayah=1)
    evidence = quran_evidence("إِنَّا أَعْطَيْنَاكَ الْكَوْثَرَ", surah=108, ayah=1)
    response, result = statuses(claim, evidence)
    assert response.quran_record_alignment == "ALIGNED"
    assert set(result.values()) == {AttributeValidationStatus.SUPPORTED}


def test_q12_partial_quote_alignment_preserves_tafseer_parent_gate_signal():
    aligned = aggregate_quran_alignment(
        quran_claim("الله لا إله إلا هو الحي القيوم"),
        [quran_evidence(AYAT_AL_KURSI)],
    )
    mismatch = aggregate_quran_alignment(
        quran_claim("قل هو الله أحد", surah="الفلق", ayah=1),
        [quran_evidence("قل أعوذ برب الفلق", surah=113, ayah=1)],
    )
    assert aligned == QuranRecordAlignment.ALIGNED
    assert mismatch == QuranRecordAlignment.MISMATCH
