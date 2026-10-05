import asyncio

import httpx
import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceType
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.quranpedia import QuranpediaAdapter
from app.retrieval.router import create_retrieval_plan
from app.validation.evidence_matcher import relevant_evidence
from app.validation.service import EvidenceValidationService
from app.agents.claim_extractor import ClaimExtractor
from conftest import FakeClient, valid_result


REGRESSION_TEXT = """قال الله تعالى: ﴿إِنَّ مَعَ الْعُسْرِ يُسْرًا﴾، وهي الآية رقم 6 من سورة الشرح. وتدل الآية على أن الشدة لا تدوم، وأن الله يجعل مع العسر تيسيرًا وفرجًا.

وقال النبي ﷺ: «المسلم من سلم المسلمون من لسانه ويده»، رواه البخاري عن عبد الله بن عمرو رضي الله عنهما، وهو حديث صحيح. ومن معاني الحديث أن المسلم ينبغي أن يكف أذاه عن الآخرين، سواء كان الأذى بالقول أو بالفعل."""


def adapter(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return QuranpediaAdapter("https://provider.test", client, MemoryCache(),
                             max_attempts=3, max_concurrency=2), client


def quran_claim(surah="الشرح", ayah="6"):
    return Claim.model_validate({
        "id": "claim_001", "original_text": "إن مع العسر يسرا",
        "normalized_claim": "سورة الشرح الآية 6: إن مع العسر يسرا",
        "claim_type": "QURAN_RECORD", "domain": "QURAN",
        "search_queries": ["سورة الشرح الآية السادسة"], "entities": [],
        "attributes": [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"},
                       {"type": "SURAH", "value": surah},
                       {"type": "AYAH_NUMBER", "value": ayah}],
        "requires_evidence": True, "reason": "Quran record.",
    })


def interpretation(surah="الشرح", ayah="6"):
    return Claim.model_validate({
        "id": "claim_002", "original_text": "وتدل الآية على الفرج مع الضيق",
        "normalized_claim": "الله يجعل مع العسر تيسيرا وفرجا",
        "claim_type": "QURAN_INTERPRETATION", "domain": "QURAN",
        "search_queries": ["تفسير سورة الشرح الآية 6"], "entities": [],
        "attributes": [{"type": "INTERPRETATION", "value": "الله يجعل مع العسر تيسيرا وفرجا"}],
        "parent_claim_id": "claim_001", "relationship": "INTERPRETS",
        "subject_context": {"type": "QURAN", "surah": surah, "ayah_number": ayah,
                            "text": "إن مع العسر يسرا"},
        "requires_evidence": True, "reason": "Quran interpretation.",
    })


@pytest.mark.parametrize("name,number", [
    ("الشرح", 94), ("الانشراح", 94), ("المسد", 111), ("تبت", 111),
    ("غافر", 40), ("المؤمن", 40), ("الإسراء", 17), ("بني إسرائيل", 17),
    ("البقرة", 2), ("الإخلاص", 112),
])
def test_deterministic_surah_aliases(name, number):
    assert QuranpediaAdapter.surah_number(name) == number


def test_94_6_request_candidate_and_validation():
    def handler(request):
        assert request.url.path == "/mushafs/1/94/6"
        return httpx.Response(200, json={"id": 6096, "number": 6, "surah": "94",
            "page_number": 597, "text": "إِنَّ مَعَ الْعُسْرِ يُسْرًا", "options": ["tafsir"]})
    provider, client = adapter(handler)
    claim = quran_claim()
    result = asyncio.run(provider.retrieve(claim)); asyncio.run(client.aclose())
    evidence = result.evidence[0]
    validation = EvidenceValidationService().validate(claim, [evidence])
    assert evidence.raw_metadata["surah"] == 94 and evidence.raw_metadata["ayah"] == 6
    assert [item.status.value for item in validation.validations] == ["SUPPORTED"] * 3


def test_quran_interpretation_routes_to_quranpedia_tafsir():
    plan = create_retrieval_plan(interpretation())
    assert [source.provider.value for source in plan.sources] == ["DORAR_TAFSEER", "QURANPEDIA"]
    assert all(source.purpose.value == "QURAN_TAFSIR" for source in plan.sources)
    assert plan.tasks[0].target_attribute_ids == ["attr_001"]


def tafsir_discovery():
    return [{"id": 2012, "name": "التفسير الميسر", "fundamental": 1},
            {"id": 3, "name": "تيسير الكريم الرحمن", "fundamental": 1},
            {"id": 331, "name": "تفسير القرآن العظيم", "fundamental": 1}]


def book_payload(book_id, content):
    names = {2012: "التفسير الميسر", 3: "تيسير الكريم الرحمن", 331: "تفسير القرآن العظيم"}
    return {"book": {"id": book_id, "name": names[book_id], "short_name": names[book_id],
                     "author": {"id": 1, "ar_name": "مؤلف موثوق"},
                     "language": {"id": 1, "name": "العربية", "code": "ar"}},
            "content": content}


def test_tafsir_selects_2012_normalizes_html_and_preserves_provenance():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/tafsir"):
            return httpx.Response(200, json=tafsir_discovery())
        return httpx.Response(200, json=book_payload(2012, [{"text": "فإن مع <strong>الضيق</strong><br>فرجًا.",
                                                             "part": "1", "page": 6096, "ayahs": "6096"}]))
    provider, client = adapter(handler)
    result = asyncio.run(provider.retrieve(interpretation())); asyncio.run(client.aclose())
    evidence = result.evidence[0]
    assert calls == ["/ayah/94/6/tafsir", "/ayah/94/6/book/2012"]
    assert evidence.evidence_type == EvidenceType.QURAN_TAFSIR
    assert evidence.provider_record_id == "2012"
    assert evidence.title == "التفسير الميسر" and evidence.author == "مؤلف موثوق"
    assert evidence.text == "فإن مع الضيق فرجًا."
    assert evidence.raw_metadata["surah"] == 94 and evidence.raw_metadata["ayah"] == 6
    assert evidence.raw_metadata["content"][0]["page"] == 6096


def test_empty_2012_falls_back_to_3():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/tafsir"):
            return httpx.Response(200, json=tafsir_discovery())
        book_id = int(request.url.path.rsplit("/", 1)[-1])
        content = [] if book_id == 2012 else [{"text": "مع الضيق فرج"}]
        return httpx.Response(200, json=book_payload(book_id, content))
    provider, client = adapter(handler)
    result = asyncio.run(provider.retrieve(interpretation())); asyncio.run(client.aclose())
    assert result.evidence[0].provider_record_id == "3"
    assert calls[-1] == "/ayah/94/6/book/3"


def test_empty_discovery_and_all_empty_content_return_no_evidence():
    for discovery in ([], tafsir_discovery()):
        def handler(request, discovery=discovery):
            if request.url.path.endswith("/tafsir"):
                return httpx.Response(200, json=discovery)
            book_id = int(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=book_payload(book_id, []))
        provider, client = adapter(handler)
        result = asyncio.run(provider.retrieve(interpretation())); asyncio.run(client.aclose())
        assert not result.success and not result.evidence
        assert result.error.message == "NO_TAFSIR_AVAILABLE"


def test_quran_text_evidence_cannot_validate_interpretation():
    claim = interpretation()
    ayah = asyncio.run(_ayah_fixture(claim.id))
    attribute = claim.attributes[0]
    assert relevant_evidence(attribute, [ayah]) == []


async def _ayah_fixture(claim_id):
    from datetime import datetime, timezone
    from app.models.evidence import EvidenceCandidate
    return EvidenceCandidate(
        evidence_id="quranpedia:94:6", claim_id=claim_id, provider="QURANPEDIA",
        evidence_type="QURAN_AYAH", text="إن مع العسر يسرا",
        retrieved_at=datetime.now(timezone.utc), raw_metadata={"surah": 94, "ayah": 6})


def test_exact_regression_keeps_four_claim_structure(settings):
    quran_text, hadith_text = REGRESSION_TEXT.split("\n\n")
    raw = [
        {"id": "claim_001", "original_text": quran_text, "normalized_claim": quran_text,
         "claim_type": "QURAN_RECORD", "domain": "QURAN", "search_queries": ["سورة الشرح الآية 6"],
         "entities": [], "attributes": [{"type": "QURAN_TEXT", "value": "إن مع العسر يسرا"},
            {"type": "SURAH", "value": "الشرح"}, {"type": "AYAH_NUMBER", "value": "6"},
            {"type": "INTERPRETATION", "value": "الشدة لا تدوم"},
            {"type": "INTERPRETATION", "value": "الله يجعل مع العسر تيسيرا وفرجا"}],
         "requires_evidence": True, "reason": "Quran record and interpretation."},
        {"id": "claim_002", "original_text": hadith_text, "normalized_claim": hadith_text,
         "claim_type": "HADITH_RECORD", "domain": "HADITH",
         "search_queries": ["حديث المسلم من سلم المسلمون عبد الله بن عمرو البخاري"], "entities": [],
         "attributes": [{"type": "HADITH_TEXT", "value": "المسلم من سلم المسلمون من لسانه ويده"},
            {"type": "NARRATOR", "value": "عبد الله بن عمرو"}, {"type": "SOURCE", "value": "البخاري"},
            {"type": "AUTHENTICITY", "value": "صحيح"},
            {"type": "INTERPRETATION", "value": "المسلم يكف أذاه عن الآخرين بالقول والفعل"}],
         "requires_evidence": True, "reason": "Hadith record and interpretation."},
    ]
    result = ClaimExtractor(settings, FakeClient([valid_result(raw, "ar")])).extract(REGRESSION_TEXT)
    assert [claim.claim_type.value for claim in result.claims] == [
        "QURAN_RECORD", "QURAN_INTERPRETATION", "HADITH_RECORD", "HADITH_INTERPRETATION"]
    assert result.claims[1].parent_claim_id == "claim_001"
    assert result.claims[3].parent_claim_id == "claim_003"
