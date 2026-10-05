import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.agents.claim_extractor import ClaimExtractor
from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate
from app.reporting.builder import build_verification_report
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.quranpedia import QuranpediaAdapter
from app.validation.deterministic import validate_candidate
from app.validation.evidence_matcher import CandidateAlignment, hadith_record_alignment
from app.validation.service import EvidenceValidationService
from conftest import FakeClient, valid_result


REGRESSION_TEXT = """قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ ۝ اللَّهُ الصَّمَدُ﴾، وهاتان الآيتان من سورة الإخلاص، وهما الآيتان الأولى والثانية من السورة. وتدل الآيات على وحدانية الله سبحانه وتعالى، وأن الله هو الصمد الذي تقصده الخلائق في حوائجها.

وقال النبي ﷺ: «الدين النصيحة»، رواه مسلم عن تميم الداري رضي الله عنه، وهو حديث صحيح. ومن معاني الحديث أن النصيحة أصل عظيم في الدين، وتشمل إرادة الخير للآخرين وإرشادهم إلى ما ينفعهم."""


def quran_claim(text, ayah_value=None):
    attributes = [
        {"type": "QURAN_TEXT", "value": "قل هو الله أحد الله الصمد"},
        {"type": "SURAH", "value": "الإخلاص"},
    ]
    if ayah_value:
        attributes.append({"type": "AYAH_NUMBER", "value": ayah_value})
    return Claim.model_validate({
        "id": "claim_001", "original_text": text, "normalized_claim": text,
        "claim_type": "QURAN_RECORD", "domain": "QURAN",
        "search_queries": ["سورة الإخلاص الآيات المطلوبة"], "entities": [],
        "attributes": attributes, "requires_evidence": True, "reason": "Quran reference.",
    })


@pytest.mark.parametrize("text,expected", [
    ("الآيتان الأولى والثانية من سورة الإخلاص", [1, 2]),
    ("الآيتان 1 و2 من سورة الإخلاص", [1, 2]),
    ("الآيات من 1 إلى 3 من سورة الإخلاص", [1, 2, 3]),
    ("الآيات 1-3 من سورة الإخلاص", [1, 2, 3]),
    ("الآيات ١-٣ من سورة الإخلاص", [1, 2, 3]),
])
def test_explicit_multi_verse_references_normalize_to_structured_range(text, expected):
    claim = quran_claim(text)
    attribute = next(item for item in claim.attributes if item.type.value == "AYAH_RANGE")
    assert attribute.ayah_numbers == expected
    assert not any(item.type.value == "AYAH_NUMBER" for item in claim.attributes)


def test_scalar_range_is_normalized_but_single_verse_is_preserved():
    range_claim = quran_claim("سورة الإخلاص", "1-2")
    assert next(item for item in range_claim.attributes if item.type.value == "AYAH_RANGE").ayah_numbers == [1, 2]
    single = quran_claim("الآية 1 من سورة الإخلاص", "1")
    assert next(item for item in single.attributes if item.type.value == "AYAH_NUMBER").value == "1"


def test_quranpedia_fetches_every_ayah_and_combines_in_canonical_order():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        number = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"id": number, "text": {
            1: "قل هو الله أحد", 2: "الله الصمد"}[number]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QuranpediaAdapter("https://provider.test", client, MemoryCache(), max_attempts=3, max_concurrency=2)
    result = asyncio.run(provider.retrieve(quran_claim("الآيتان الأولى والثانية من سورة الإخلاص")))
    asyncio.run(client.aclose())
    assert calls == ["/mushafs/1/112/1", "/mushafs/1/112/2"]
    assert result.evidence[0].text == "قل هو الله أحد الله الصمد"
    assert result.evidence[0].raw_metadata["ayah_numbers"] == [1, 2]


def test_multi_verse_text_and_range_validation_supported_partial_and_wrong():
    claim = quran_claim("الآيتان الأولى والثانية من سورة الإخلاص")
    text_attr = next(item for item in claim.attributes if item.type.value == "QURAN_TEXT")
    range_attr = next(item for item in claim.attributes if item.type.value == "AYAH_RANGE")
    evidence = candidate("quran", "قل هو الله أحد الله الصمد", "QURAN_AYAH", "QURANPEDIA",
                         raw_metadata={"ayah_numbers": [1, 2], "ayah_texts": ["قل هو الله أحد", "الله الصمد"]})
    assert validate_candidate(text_attr, evidence).status.value == "SUPPORTED"
    partial = text_attr.model_copy(update={"value": "قل هو الله أحد"})
    assert validate_candidate(partial, evidence).status.value == "PARTIAL"
    assert validate_candidate(range_attr, evidence).status.value == "SUPPORTED"
    wrong = range_attr.model_copy(update={"value": "2-3", "ayah_numbers": [2, 3]})
    assert validate_candidate(wrong, evidence).status.value == "CONTRADICTED"


@pytest.mark.parametrize("domain,claim_type,marker", [
    ("HADITH", "HADITH_RECORD", "ومن معاني الحديث أن النصيحة أصل عظيم في الدين."),
    ("HADITH", "HADITH_RECORD", "\nومن معاني الحديث أن النصيحة أصل عظيم في الدين."),
    ("QURAN", "QURAN_RECORD", "وتدل الآيات على وحدانية الله."),
    ("QURAN", "QURAN_RECORD", "\nوتدل الآية على وحدانية الله."),
])
def test_embedded_interpretation_is_stably_split(settings, domain, claim_type, marker):
    source = ("قال النبي ﷺ: «الدين النصيحة»، رواه مسلم. " if domain == "HADITH" else
              "قال الله تعالى: ﴿قل هو الله أحد﴾. ")
    attributes = ([{"type": "HADITH_TEXT", "value": "الدين النصيحة"},
                   {"type": "SOURCE", "value": "مسلم"}] if domain == "HADITH" else
                  [{"type": "QURAN_TEXT", "value": "قل هو الله أحد"},
                   {"type": "SURAH", "value": "الإخلاص"}, {"type": "AYAH_NUMBER", "value": "1"}])
    attributes.append({"type": "INTERPRETATION", "value": marker.strip(), "requires_evidence": True})
    raw = {"id": "claim_001", "original_text": source + marker, "normalized_claim": source + marker,
           "claim_type": claim_type, "domain": domain, "search_queries": [source.strip()],
           "entities": [], "attributes": attributes, "requires_evidence": True, "reason": "Mixed object."}
    result = ClaimExtractor(settings, FakeClient([valid_result([raw], "ar")])).extract(source + marker)
    expected_child = "HADITH_INTERPRETATION" if domain == "HADITH" else "QURAN_INTERPRETATION"
    assert result.claim_count == 2
    assert result.claims[1].claim_type.value == expected_child
    assert result.claims[1].parent_claim_id == result.claims[0].id
    assert all(item.type.value != "INTERPRETATION" for item in result.claims[0].attributes)


def hadith_claim():
    return Claim.model_validate({
        "id": "claim_001", "original_text": "قال النبي ﷺ: الدين النصيحة",
        "normalized_claim": "حديث الدين النصيحة عن تميم الداري رواه مسلم",
        "claim_type": "HADITH_RECORD", "domain": "HADITH",
        "search_queries": ["حديث الدين النصيحة تميم الداري"], "entities": [],
        "attributes": [{"type": "HADITH_TEXT", "value": "الدين النصيحة"},
                       {"type": "NARRATOR", "value": "تميم الداري"},
                       {"type": "SOURCE", "value": "مسلم"},
                       {"type": "AUTHENTICITY", "value": "صحيح"}],
        "requires_evidence": True, "reason": "Hadith record.",
    })


def candidate(identifier, text, evidence_type="HADITH", provider="HADEETHENC", **extra):
    return EvidenceCandidate.model_validate({
        "evidence_id": identifier, "claim_id": "claim_001", "provider": provider,
        "evidence_type": evidence_type, "text": text,
        "retrieved_at": datetime.now(timezone.utc), "raw_metadata": {}, **extra,
    })


def test_hadith_alignment_exact_overlap_and_truncation():
    claim = hadith_claim()
    exact = candidate("exact", "عن تميم الداري أن النبي ﷺ قال الدين النصيحة")
    overlap = candidate("overlap", "إن الدين يسر")
    other_advice = candidate("advice", "إن العبد إذا نصح لسيده")
    truncated = candidate("truncated", "الدين النص")
    assert hadith_record_alignment(claim, exact)[0] == CandidateAlignment.ALIGNED
    assert hadith_record_alignment(claim, overlap)[0] == CandidateAlignment.UNRELATED
    assert hadith_record_alignment(claim, other_advice)[0] == CandidateAlignment.UNRELATED
    assert hadith_record_alignment(claim, truncated)[0] == CandidateAlignment.UNRESOLVED


def test_dependent_attributes_use_only_aligned_records_and_report_filters_candidates():
    claim = hadith_claim()
    aligned = candidate("aligned", "عن تميم الداري أن النبي ﷺ قال الدين النصيحة",
                        narrator="تميم الداري", reference="صحيح مسلم (55)")
    unrelated = [candidate(f"unrelated-{i}", text, narrator="أبو هريرة", reference="صحيح البخاري")
                 for i, text in enumerate(["إن الدين يسر", "الدين المعاملة", "نصح العبد لسيده",
                                           "الدين القيم", "يسروا ولا تعسروا", "حق المسلم",
                                           "الدين الخالص"], 1)]
    unresolved = candidate("unresolved", "الدين النص", narrator="راو غير معروف", reference="مسلم")
    second_aligned = candidate("aligned-2", "الدين النصيحة", narrator="تميم الداري", reference="مسلم 55")
    candidates = [aligned, second_aligned, *unrelated, unresolved]
    validation = EvidenceValidationService().validate(claim, candidates)
    by_type = {item.attribute_type.value: item for item in validation.validations}
    assert by_type["NARRATOR"].status.value == "SUPPORTED"
    assert by_type["SOURCE"].status.value == "SUPPORTED"
    assert by_type["AUTHENTICITY"].status.value == "NOT_FOUND"
    assert set(by_type["NARRATOR"].supporting_evidence_ids) <= {"aligned", "aligned-2"}
    assert set(by_type["SOURCE"].supporting_evidence_ids) <= {"aligned", "aligned-2"}
    decision = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
    report = build_verification_report(claim, candidates, validation, decision)
    assert {item.evidence_id for item in report.sources} == {"aligned", "aligned-2"}
    assert not ({item.evidence_id for item in report.sources} &
                {item.evidence_id for item in unrelated + [unresolved]})


def test_exact_mixed_regression_becomes_four_claims_with_range_and_relationships(settings):
    quran_text, hadith_text = REGRESSION_TEXT.split("\n\n")
    raw = [
        {"id": "claim_001", "original_text": quran_text, "normalized_claim": quran_text,
         "claim_type": "QURAN_RECORD", "domain": "QURAN",
         "search_queries": ["سورة الإخلاص الآيتان الأولى والثانية"], "entities": [],
         "attributes": [{"type": "QURAN_TEXT", "value": "قل هو الله أحد الله الصمد"},
                        {"type": "SURAH", "value": "الإخلاص"},
                        {"type": "AYAH_NUMBER", "value": "1-2"},
                        {"type": "INTERPRETATION", "value": "وحدانية الله"},
                        {"type": "INTERPRETATION", "value": "الله هو الصمد الذي تقصده الخلائق في حوائجها"}],
         "requires_evidence": True, "reason": "Quran and interpretation."},
        {"id": "claim_002", "original_text": hadith_text, "normalized_claim": hadith_text,
         "claim_type": "HADITH_RECORD", "domain": "HADITH",
         "search_queries": ["حديث الدين النصيحة تميم الداري مسلم"], "entities": [],
         "attributes": [{"type": "HADITH_TEXT", "value": "الدين النصيحة"},
                        {"type": "NARRATOR", "value": "تميم الداري"},
                        {"type": "SOURCE", "value": "مسلم"},
                        {"type": "AUTHENTICITY", "value": "صحيح"},
                        {"type": "INTERPRETATION", "value": "النصيحة أصل عظيم في الدين"},
                        {"type": "INTERPRETATION", "value": "إرادة الخير للآخرين وإرشادهم إلى ما ينفعهم"}],
         "requires_evidence": True, "reason": "Hadith and interpretation."},
    ]
    result = ClaimExtractor(settings, FakeClient([valid_result(raw, "ar")])).extract(REGRESSION_TEXT)
    assert [item.claim_type.value for item in result.claims] == [
        "QURAN_RECORD", "QURAN_INTERPRETATION", "HADITH_RECORD", "HADITH_INTERPRETATION"]
    assert next(item for item in result.claims[0].attributes
                if item.type.value == "AYAH_RANGE").ayah_numbers == [1, 2]
    assert result.claims[1].parent_claim_id == "claim_001"
    assert result.claims[3].parent_claim_id == "claim_003"
    assert all(attribute.requires_evidence for index in (1, 3)
               for attribute in result.claims[index].attributes)
