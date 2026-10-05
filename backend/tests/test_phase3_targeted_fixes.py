import asyncio

import httpx

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderResult, RetrievalStatus
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.dorar import DorarAdapter
from app.retrieval.router import create_retrieval_plan
from app.retrieval.service import RetrievalService


def make_claim(text, domain, claim_type, attributes, evidence=True):
    return Claim.model_validate({
        "id": "claim_001", "original_text": text, "normalized_claim": text,
        "domain": domain, "claim_type": claim_type, "attributes": attributes,
        "entities": [], "search_queries": [text] if evidence else [],
        "requires_evidence": evidence, "reason": "regression test",
    })


class NeverCalled:
    async def retrieve(self, claim):
        raise AssertionError("provider must not be called")


def test_missing_quran_context_stops_before_provider():
    item = make_claim("ابن كثير فسّر النور في الآية بأنه الهدى.", "QURAN", "QURAN_TAFSIR", [])
    service = RetrievalService({EvidenceProvider.QURANPEDIA: NeverCalled()})
    result = asyncio.run(service.retrieve(item))
    assert not result.retrieval_ready
    assert result.missing_context == ["SURAH", "AYAH_NUMBER"]
    assert result.retrieval_status == RetrievalStatus.MISSING_CONTEXT


def test_complete_quran_context_is_ready_and_routed():
    item = make_claim("فسّر ابن كثير سورة النور الآية 35.", "QURAN", "QURAN_TAFSIR", [
        {"id": "attr_001", "type": "SURAH", "value": "النور"},
        {"id": "attr_002", "type": "AYAH_NUMBER", "value": "35"},
    ])
    plan = create_retrieval_plan(item)
    assert [source.provider for source in plan.sources] == [
        EvidenceProvider.DORAR_TAFSEER, EvidenceProvider.QURANPEDIA]
    assert plan.tasks[0].target_attribute_ids == []
    assert plan.tasks[1].target_attribute_ids == ["attr_001", "attr_002"]


def test_unresolved_hadith_context_stops_before_provider():
    item = make_claim("الإمام الترمذي وصف هذا الحديث بأنه حسن غريب.", "HADITH",
                      "HADITH_AUTHENTICITY", [
                          {"type": "SCHOLAR", "value": "الترمذي"},
                          {"type": "AUTHENTICITY", "value": "حسن غريب"},
                      ])
    service = RetrievalService({EvidenceProvider.DORAR: NeverCalled(),
                                EvidenceProvider.HADEETHENC: NeverCalled()})
    result = asyncio.run(service.retrieve(item))
    assert result.retrieval_status == RetrievalStatus.MISSING_CONTEXT
    assert result.missing_context == ["HADITH_TEXT"]


def test_attributes_provenance_ids_and_tasks_are_preserved():
    item = make_claim("حديث إنما الأعمال بالنيات عن عمر رواه البخاري وهو صحيح.", "HADITH",
                      "HADITH_AUTHENTICITY", [
                          {"id": "attr_001", "type": "TEXT", "value": "إنما الأعمال بالنيات"},
                          {"id": "attr_002", "type": "NARRATOR", "value": "عمر بن الخطاب"},
                          {"id": "attr_003", "type": "SOURCE", "value": "صحيح البخاري"},
                          {"id": "attr_004", "type": "AUTHENTICITY", "value": "صحيح",
                           "asserted_by": "المؤلف", "qualifier": "بحسب قوله"},
                      ])
    dumped = item.model_dump(mode="json")
    assert [attribute["id"] for attribute in dumped["attributes"]] == [
        "attr_001", "attr_002", "attr_003", "attr_004"]
    assert dumped["attributes"][3]["asserted_by"] == "المؤلف"
    plan = create_retrieval_plan(item)
    dorar = next(task for task in plan.tasks if task.provider == EvidenceProvider.DORAR_HADITH)
    hadeeth = next(task for task in plan.tasks if task.provider == EvidenceProvider.HADEETHENC)
    assert dorar.target_attribute_ids == ["attr_001", "attr_002", "attr_003", "attr_004"]
    assert hadeeth.target_attribute_ids == ["attr_001", "attr_002", "attr_003", "attr_004"]


def test_dorar_403_is_access_denied_not_no_results():
    def handler(request):
        return httpx.Response(403, request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = DorarAdapter("https://dorar.test", client, MemoryCache())
    item = make_claim("إنما الأعمال بالنيات", "HADITH", "HADITH_AUTHENTICITY",
                      [{"type": "TEXT", "value": "إنما الأعمال بالنيات"}])
    result = asyncio.run(adapter.retrieve(item))
    asyncio.run(client.aclose())
    assert result.error.error_type.value == "ACCESS_DENIED"
    assert result.error.http_status == 403
    assert result.query_attempts[0].http_status == 403


def test_evidence_is_linked_to_target_attributes_and_partial_survives():
    item = make_claim("إنما الأعمال بالنيات صحيح", "HADITH", "HADITH_AUTHENTICITY", [
        {"id": "attr_001", "type": "TEXT", "value": "إنما الأعمال بالنيات"},
        {"id": "attr_002", "type": "AUTHENTICITY", "value": "صحيح"},
    ])
    candidate = EvidenceCandidate(evidence_id="h:1", claim_id=item.id, provider="HADEETHENC",
                                  evidence_type=EvidenceType.HADITH, text="حديث", source_name="HadeethEnc",
                                  provider_record_id="1", retrieved_at="2026-01-01T00:00:00Z")
    class Fake:
        def __init__(self, result): self.result = result
        async def retrieve(self, claim): return self.result
    service = RetrievalService({
        EvidenceProvider.DORAR_HADITH: Fake(ProviderResult(provider="DORAR_HADITH", success=False)),
        EvidenceProvider.HADEETHENC: Fake(ProviderResult(provider="HADEETHENC", success=True,
                                                        evidence=[candidate])),
    })
    result = asyncio.run(service.retrieve(item))
    assert result.retrieval_status == RetrievalStatus.PARTIAL
    hadeeth_result = next(p for p in result.provider_results if p.provider == EvidenceProvider.HADEETHENC)
    assert hadeeth_result.evidence[0].target_attribute_ids == ["attr_001", "attr_002"]


def test_unsupported_source_and_nonverifiable_are_distinct():
    unsupported = make_claim("مسألة غير مدعومة", "FIQH", "FIQH_RULING",
                             [{"type": "RULING", "value": "حكم"}])
    assert asyncio.run(RetrievalService({}).retrieve(unsupported)).retrieval_status == RetrievalStatus.NO_SUPPORTED_SOURCE
    skipped = make_claim("أحب هذا النص", "GENERAL", "NON_VERIFIABLE", [], evidence=False)
    assert asyncio.run(RetrievalService({}).retrieve(skipped)).retrieval_status == RetrievalStatus.SKIPPED
