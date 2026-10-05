import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.agents.claim_extractor import link_explicit_interpretations
from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider
from app.models.retrieval import ProviderResult, RetrievalStatus
from app.reporting.builder import build_verification_report
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.quranpedia import QuranpediaAdapter
from app.retrieval.service import deduplicate_evidence
from app.retrieval.service import RetrievalService
from app.validation.evidence_matcher import (
    QuranRecordAlignment, aggregate_quran_alignment, quran_record_alignment,
)
from app.validation.service import EvidenceValidationService


REGRESSION_A = """قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ ۝ اللَّهُ الصَّمَدُ﴾، وهما الآيتان الأولى والثانية من سورة الفلق. وتدل الآيتان على وحدانية الله سبحانه وتعالى، وأن الله هو الصمد الذي تقصده الخلائق في حوائجها.

وقال الله تعالى: ﴿إِنَّ مَعَ الْعُسْرِ يُسْرًا﴾، وهي الآية رقم 6 من سورة الشرح، ومن معانيها أن مع الضيق فرجًا وتيسيرًا.

وقال النبي ﷺ: «المسلم من سلم المسلمون من لسانه ويده»، رواه الترمذي عن أبي هريرة رضي الله عنه، وهو حديث صحيح. ومن معاني الحديث أن المسلم ينبغي أن يمتنع عن إيذاء الآخرين بلسانه أو بيده."""

REGRESSION_B = """قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ ۝ اللَّهُ الصَّمَدُ﴾، وهاتان الآيتان من سورة الإخلاص، وهما الآيتان الأولى والثانية من السورة. وتدل الآيات على وحدانية الله سبحانه وتعالى، وأن الله هو الصمد الذي تقصده الخلائق في حوائجها.

وقال النبي ﷺ: «الدين النصيحة»، رواه مسلم عن تميم الداري رضي الله عنه، وهو حديث صحيح. ومن معاني الحديث أن النصيحة أصل عظيم في الدين، وتشمل إرادة الخير للآخرين وإرشادهم إلى ما ينفعهم."""


def quran_claim(surah, ayahs, text):
    verse_attribute = ({"type": "AYAH_NUMBER", "value": str(ayahs[0])} if len(ayahs) == 1 else
                       {"type": "AYAH_RANGE", "value": f"{ayahs[0]}-{ayahs[-1]}",
                        "ayah_numbers": ayahs})
    return Claim.model_validate({
        "id": "claim_001", "original_text": text, "normalized_claim": text,
        "claim_type": "QURAN_RECORD", "domain": "QURAN",
        "search_queries": [f"سورة {surah} الآيات المطلوبة"], "entities": [],
        "attributes": [{"type": "QURAN_TEXT", "value": text},
                       {"type": "SURAH", "value": surah}, verse_attribute],
        "requires_evidence": True, "reason": "Quran quotation and reference.",
    })


def quran_evidence(identifier, reference, text, surah, ayahs):
    return EvidenceCandidate(
        evidence_id=identifier, claim_id="claim_001", provider="QURANPEDIA",
        evidence_type="QURAN_AYAH", text=text, reference=reference,
        retrieved_at=datetime.now(timezone.utc),
        raw_metadata={"surah": surah,
                      "ayah": ayahs[0] if len(ayahs) == 1 else None,
                      "ayah_numbers": ayahs, "ayah_texts": [text]},
    )


@pytest.mark.parametrize("claim,evidence", [
    (quran_claim("الشرح", [6], "إن مع العسر يسرا"),
     quran_evidence("q94", "94:6", "إِنَّ مَعَ الْعُسْرِ يُسْرًا", 94, [6])),
    (quran_claim("الإخلاص", [1, 2], "قل هو الله أحد الله الصمد"),
     quran_evidence("q112", "112:1-2", "قُلْ هُوَ اللَّهُ أَحَدٌ اللَّهُ الصَّمَدُ", 112, [1, 2])),
])
def test_quran_record_alignment_exact_single_multi_and_diacritics(claim, evidence):
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.ALIGNED
    assert aggregate_quran_alignment(claim, [evidence]) == QuranRecordAlignment.ALIGNED


def test_quran_record_alignment_accepts_one_text_attribute_per_ayah():
    claim = quran_claim("الإخلاص", [1, 2], "قل هو الله أحد")
    claim.attributes.insert(1, claim.attributes[0].model_copy(update={
        "id": "attr_second_ayah", "value": "الله الصمد",
    }))
    evidence = quran_evidence("q112", "112:1-2", "قُلْ هُوَ اللَّهُ أَحَدٌ اللَّهُ الصَّمَدُ", 112, [1, 2])
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.ALIGNED


@pytest.mark.parametrize("claim,evidence", [
    (quran_claim("الفلق", [1, 2], "قل هو الله أحد الله الصمد"),
     quran_evidence("wrong-surah", "113:1-2", "قل أعوذ برب الفلق من شر ما خلق", 113, [1, 2])),
    (quran_claim("الشرح", [5], "إن مع العسر يسرا"),
     quran_evidence("wrong-ayah", "94:5", "فإن مع العسر يسرا", 94, [5])),
])
def test_wrong_quran_reference_is_mismatch_and_relational_contradiction(claim, evidence):
    assert quran_record_alignment(claim, evidence)[0] == QuranRecordAlignment.MISMATCH
    validation = EvidenceValidationService().validate(claim, [evidence])
    assert validation.quran_record_alignment == "MISMATCH"
    assert {item.status.value for item in validation.validations} == {"CONTRADICTED"}
    assert all(item.contradicting_evidence_ids == [evidence.evidence_id]
               for item in validation.validations)
    decision = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
    report = build_verification_report(claim, [evidence], validation, decision)
    assert decision.decision.value == "CONFLICTING"
    assert all("لا يتوافق مع المرجع القرآني" in item.user_message for item in report.attributes)


def test_quran_alignment_unresolved_without_usable_provider_record():
    claim = quran_claim("الشرح", [6], "إن مع العسر يسرا")
    assert aggregate_quran_alignment(claim, []) == QuranRecordAlignment.UNRESOLVED


def interpretation_child(parent):
    child = Claim.model_validate({
        "id": "claim_002", "original_text": "وتدل الآيات على وحدانية الله",
        "normalized_claim": "وحدانية الله", "claim_type": "GENERAL_ISLAMIC_CLAIM",
        "domain": "GENERAL", "search_queries": ["تفسير الآيات وحدانية الله"],
        "entities": [], "attributes": [{"type": "OTHER", "value": "وحدانية الله"}],
        "requires_evidence": True, "reason": "Interpretation.",
    })
    return link_explicit_interpretations([parent, child])[1]


def test_parent_range_is_preserved_in_child_context():
    parent = quran_claim("الإخلاص", [1, 2], "قل هو الله أحد الله الصمد")
    child = interpretation_child(parent)
    assert child.subject_context.ayah_numbers == [1, 2]


def test_tafsir_gate_blocks_mismatch_and_unresolved_but_allows_aligned():
    class Fake:
        def __init__(self): self.calls = 0
        async def retrieve(self, claim):
            self.calls += 1
            return ProviderResult(provider="QURANPEDIA", success=True, evidence=[])
    fake = Fake()
    service = RetrievalService({EvidenceProvider.QURANPEDIA: fake})
    child = interpretation_child(quran_claim("الإخلاص", [1, 2], "قل هو الله أحد الله الصمد"))
    for alignment in ("MISMATCH", "UNRESOLVED", None):
        result = asyncio.run(service.retrieve(child, parent_quran_alignment=alignment))
        assert result.retrieval_status == RetrievalStatus.MISSING_CONTEXT
        assert result.reason == "PARENT_QURAN_REFERENCE_NOT_ALIGNED"
    assert fake.calls == 0
    allowed = asyncio.run(service.retrieve(child, parent_quran_alignment="ALIGNED"))
    assert fake.calls == 1 and allowed.retrieval_status == RetrievalStatus.NO_RESULTS


def test_multiverse_tafsir_expands_and_preserves_per_ayah_provenance():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        parts = request.url.path.split("/")
        ayah = int(parts[3])
        if request.url.path.endswith("/tafsir"):
            return httpx.Response(200, json=[{"id": 2012, "name": "التفسير الميسر"}])
        return httpx.Response(200, json={
            "book": {"id": 2012, "name": "التفسير الميسر",
                     "author": {"ar_name": "مجمع الملك فهد"}, "language": {"code": "ar"}},
            "content": [{"text": f"تفسير الآية {ayah}", "page": ayah}],
        })
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QuranpediaAdapter("https://provider.test", client, MemoryCache())
    child = interpretation_child(quran_claim("الإخلاص", [1, 2], "قل هو الله أحد الله الصمد"))
    result = asyncio.run(provider.retrieve(child)); asyncio.run(client.aclose())
    assert calls == ["/ayah/112/1/tafsir", "/ayah/112/1/book/2012",
                     "/ayah/112/2/tafsir", "/ayah/112/2/book/2012"]
    assert [item.reference for item in result.evidence] == ["112:1", "112:2"]
    assert [item.evidence_id for item in result.evidence] == [
        "quranpedia:tafsir:112:1:2012", "quranpedia:tafsir:112:2:2012"]
    assert [item.reference for item in deduplicate_evidence(result.evidence)] == ["112:1", "112:2"]


def test_partial_multiverse_tafsir_returns_only_actual_content():
    def handler(request):
        parts = request.url.path.split("/")
        ayah = int(parts[3])
        if request.url.path.endswith("/tafsir"):
            return httpx.Response(200, json=[{"id": 2012, "name": "التفسير الميسر"}])
        content = [{"text": "تفسير متاح"}] if ayah == 1 else []
        return httpx.Response(200, json={
            "book": {"id": 2012, "name": "التفسير الميسر", "author": {}, "language": {}},
            "content": content,
        })
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QuranpediaAdapter("https://provider.test", client, MemoryCache())
    child = interpretation_child(quran_claim("الإخلاص", [1, 2], "قل هو الله أحد الله الصمد"))
    result = asyncio.run(provider.retrieve(child)); asyncio.run(client.aclose())
    assert [item.reference for item in result.evidence] == ["112:1"]
    assert any(attempt.query == "2012" and not attempt.success for attempt in result.query_attempts)

