import asyncio

import httpx

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderResult, RetrievalStatus
from app.retrieval.cache import MemoryCache
from app.retrieval.parsers.dorar_html import parse_dorar_html
from app.retrieval.providers.bayan import BayanAdapter
from app.retrieval.providers.dorar import DorarAdapter
from app.retrieval.providers.hadeethenc import HadeethEncAdapter
from app.retrieval.providers.quranpedia import QuranpediaAdapter
from app.retrieval.query_selector import select_queries
from app.retrieval.router import create_retrieval_plan
from app.retrieval.service import RetrievalService, deduplicate_evidence


def make_claim(domain="HADITH", claim_type="HADITH_RECORD", evidence=True, attributes=None):
    return Claim.model_validate({
        "id": "claim_001", "original_text": "إنما الأعمال بالنيات عن عمر",
        "normalized_claim": "حديث إنما الأعمال بالنيات من رواية عمر بن الخطاب",
        "claim_type": claim_type, "domain": domain,
        "attributes": ([{"type": "TEXT", "value": "إنما الأعمال بالنيات"}]
                       if attributes is None else attributes),
        "search_queries": ["إنما الأعمال بالنيات عمر بن الخطاب"] if evidence else [],
        "entities": [], "requires_evidence": evidence, "reason": "test",
    })


def adapter(cls, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cls("https://provider.test", client, MemoryCache(), max_attempts=3, max_concurrency=2), client


def test_router_rules():
    quran = make_claim("QURAN", "QURAN_REFERENCE", attributes=[{"type": "SURAH", "value": "2"},
                                                                 {"type": "AYAH_NUMBER", "value": "255"}])
    assert [x.provider for x in create_retrieval_plan(quran).sources] == [EvidenceProvider.QURANPEDIA]
    hadith = make_claim(attributes=[{"type": "TEXT", "value": "إنما الأعمال بالنيات"},
                                     {"type": "AUTHENTICITY", "value": "صحيح"}])
    assert [x.provider for x in create_retrieval_plan(hadith).sources] == [EvidenceProvider.DORAR_HADITH,
                                                                           EvidenceProvider.HADEETHENC]
    athar = make_claim("ATHAR", "ATHAR_AUTHENTICITY", attributes=[{"type": "AUTHENTICITY", "value": "صحيح"}])
    assert [x.provider for x in create_retrieval_plan(athar).sources] == [EvidenceProvider.DORAR]
    assert create_retrieval_plan(make_claim("GENERAL", "NON_VERIFIABLE", False)).sources == []


def test_query_selector_prefers_distinctive_text():
    claim = make_claim()
    assert select_queries(claim)[0] == "إنما الأعمال بالنيات"


def test_quranpedia_structured_ayah_and_metadata():
    def handler(request):
        assert request.url.path.endswith("/mushafs/1/2/255")
        return httpx.Response(200, json={"id": 262, "surah": 2, "number": 255, "page_number": 42,
                                         "text": "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ", "options": ["tafsir"]})
    provider, client = adapter(QuranpediaAdapter, handler)
    claim = make_claim("QURAN", "QURAN_RECORD", attributes=[{"type": "SURAH", "value": "البقرة"},
                                                              {"type": "AYAH_NUMBER", "value": "255"}])
    result = asyncio.run(provider.retrieve(claim)); asyncio.run(client.aclose())
    assert result.success and result.evidence[0].reference == "2:255"
    assert result.evidence[0].provider_score is None


def test_hadeethenc_search_then_detail_preserves_grade():
    def handler(request):
        if request.url.path.endswith("/hadeeths/search/"):
            return httpx.Response(200, json=[{"id": "1", "title": "actions", "similarity": 0.91}])
        return httpx.Response(200, json={"id": "1", "title": "Actions", "hadeeth": "Actions are by intentions",
                                         "attribution": "Umar", "grade": "Sahih", "categories": [2]})
    provider, client = adapter(HadeethEncAdapter, handler)
    result = asyncio.run(provider.retrieve(make_claim())); asyncio.run(client.aclose())
    assert result.success and result.evidence[0].judgment == "Sahih"
    assert result.evidence[0].provider_score == 0.91
    assert result.evidence[0].provider_score_type == "similarity"
    assert result.evidence[0].raw_metadata["attribution"] == "Umar"


def test_dorar_parser_keeps_multiple_scholars_separate():
    html = """<div class='hadith'><div class='hadith-text'>حديث واحد</div>الراوي: عمر\nالمحدث: البخاري\nالمصدر: الصحيح\nخلاصة حكم المحدث: صحيح</div>
    <div class='hadith'><div class='hadith-text'>حديث واحد</div>الراوي: عمر\nالمحدث: عالم آخر\nالمصدر: كتاب\nخلاصة حكم المحدث: ضعيف</div>"""
    records = parse_dorar_html(html)
    assert len(records) == 2
    assert {item["judgment"] for item in records} == {"صحيح", "ضعيف"}


def test_dorar_json_html_normalization():
    html = "<div class='hadith'><div class='hadith-text'>إنما الأعمال بالنيات</div>الراوي: عمر\nالمحدث: البخاري\nالمصدر: الصحيح\nالصفحة أو الرقم: 1\nخلاصة حكم المحدث: صحيح</div>"
    provider, client = adapter(DorarAdapter, lambda request: httpx.Response(200, json={"ahadith": {"result": html}}))
    result = asyncio.run(provider.retrieve(make_claim())); asyncio.run(client.aclose())
    assert result.success and result.evidence[0].scholar == "البخاري"
    assert "<div" not in result.evidence[0].text


def test_bayan_confirmed_list_and_404():
    provider, client = adapter(BayanAdapter, lambda request: httpx.Response(200, json=[
        {"id": 4, "name": "Prayer guide", "description": "A guide to prayer", "language": "en"}]))
    claim = make_claim("GENERAL", "GENERAL_ISLAMIC_CLAIM", attributes=[])
    claim = claim.model_copy(update={"normalized_claim": "prayer guide", "search_queries": ["prayer guide"]})
    result = asyncio.run(provider.retrieve(claim)); asyncio.run(client.aclose())
    assert result.success and result.evidence[0].provider_record_id == "4"
    failed, client = adapter(BayanAdapter, lambda request: httpx.Response(404, request=request))
    result = asyncio.run(failed.retrieve(claim)); asyncio.run(client.aclose())
    assert result.error.error_type.value == "ENDPOINT_UNAVAILABLE"


def test_invalid_json_rate_limit_and_empty_results():
    invalid, client = adapter(QuranpediaAdapter, lambda request: httpx.Response(200, text="not-json"))
    claim = make_claim("QURAN", "QURAN_RECORD", attributes=[{"type": "SURAH", "value": "2"},
                                                              {"type": "AYAH_NUMBER", "value": "255"}])
    assert asyncio.run(invalid.retrieve(claim)).error.error_type.value == "INVALID_RESPONSE"; asyncio.run(client.aclose())
    limited, client = adapter(DorarAdapter, lambda request: httpx.Response(429, request=request))
    assert asyncio.run(limited.retrieve(make_claim())).error.error_type.value == "RATE_LIMIT"; asyncio.run(client.aclose())
    empty, client = adapter(DorarAdapter, lambda request: httpx.Response(200, json={"ahadith": {"result": ""}}))
    assert asyncio.run(empty.retrieve(make_claim())).error.error_type.value == "NO_RESULTS"; asyncio.run(client.aclose())


def test_provider_timeout_is_structured():
    def handler(request):
        raise httpx.ReadTimeout("slow provider", request=request)
    provider, client = adapter(DorarAdapter, handler)
    result = asyncio.run(provider.retrieve(make_claim())); asyncio.run(client.aclose())
    assert result.error.error_type.value == "TIMEOUT"
    assert result.error.retryable is True


def test_dedup_preserves_different_scholar_judgments():
    from datetime import datetime, timezone
    base = dict(evidence_id="1", claim_id="claim_001", provider="DORAR", evidence_type="HADITH_JUDGMENT",
                text="same", source_name="book", retrieved_at=datetime.now(timezone.utc), raw_metadata={})
    first = EvidenceCandidate(**base, scholar="A", judgment="صحيح")
    second = EvidenceCandidate(**{**base, "evidence_id": "2"}, scholar="B", judgment="ضعيف")
    duplicate = EvidenceCandidate(**base, scholar="A", judgment="صحيح")
    assert len(deduplicate_evidence([first, second, duplicate])) == 2


def test_service_isolates_failure_and_skips_nonverifiable():
    class Fake:
        def __init__(self, result): self.result = result
        async def retrieve(self, claim): return self.result
    ok = ProviderResult(provider="HADEETHENC", success=True, evidence=[])
    fail = ProviderResult(provider="DORAR_HADITH", success=False)
    service = RetrievalService({EvidenceProvider.HADEETHENC: Fake(ok), EvidenceProvider.DORAR_HADITH: Fake(fail)})
    result = asyncio.run(service.retrieve(make_claim()))
    assert result.retrieval_status == RetrievalStatus.NO_RESULTS
    skipped = asyncio.run(service.retrieve(make_claim("GENERAL", "NON_VERIFIABLE", False)))
    assert skipped.retrieval_status == RetrievalStatus.SKIPPED
