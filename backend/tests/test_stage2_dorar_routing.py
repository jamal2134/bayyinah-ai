import asyncio

import httpx

from app.application.orchestrator import VerificationOrchestrator
from app.api.retrieval import build_service
from app.config.settings import Settings
from app.models.claim import Claim
from app.models.evidence import EvidenceProvider
from app.models.retrieval import ProviderErrorType
from app.retrieval.cache import MemoryCache
from app.retrieval.provider_registry import build_provider_adapters
from app.retrieval.providers.dorar_hadith import DorarHadithAdapter
from app.retrieval.query_selector import select_provider_queries
from app.retrieval.readiness import assess_retrieval_readiness
from app.retrieval.router import create_retrieval_plan


def make_claim(claim_type, domain, attributes=None, *, text="specific claim proposition",
               queries=None, context=None, evidence=True):
    data = {
        "id": "claim_001", "original_text": text, "normalized_claim": text,
        "claim_type": claim_type, "domain": domain, "attributes": attributes or [],
        "search_queries": queries or ([text] if evidence else []),
        "requires_evidence": evidence, "reason": "stage 2 routing test",
    }
    if context:
        data["subject_context"] = context
    return Claim.model_validate(data)


def providers(item):
    return [source.provider for source in create_retrieval_plan(item).sources]


def test_quran_routes_are_specialized_and_context_does_not_fan_out():
    identity = [{"type": "SURAH", "value": "2"}, {"type": "AYAH_NUMBER", "value": "255"}]
    for kind in ("QURAN_RECORD", "QURAN_REFERENCE", "QURAN_TEXT", "QURAN_TRANSLATION"):
        assert providers(make_claim(kind, "QURAN", identity)) == [EvidenceProvider.QURANPEDIA]
    for kind in ("QURAN_TAFSIR", "QURAN_INTERPRETATION"):
        assert providers(make_claim(kind, "QURAN", identity)) == [
            EvidenceProvider.DORAR_TAFSEER, EvidenceProvider.QURANPEDIA]
    assert providers(make_claim("QURAN_CONTEXT", "QURAN", [
        {"type": "DATE", "value": "specific date"},
        {"type": "LOCATION", "value": "specific location"},
    ])) == [EvidenceProvider.DORAR_TAFSEER]


def test_hadith_routes_identity_authenticity_and_interpretation_without_explanation():
    identity = [{"type": "HADITH_TEXT", "value": "explicit hadith wording"}]
    for kind in ("HADITH_TEXT", "HADITH_RECORD", "HADITH_ATTRIBUTION"):
        assert providers(make_claim(kind, "HADITH", identity)) == [
            EvidenceProvider.HADEETHENC, EvidenceProvider.DORAR_HADITH]
    authentic = make_claim("HADITH_AUTHENTICITY", "HADITH", identity + [
        {"type": "AUTHENTICITY", "value": "claimed grade"}])
    assert providers(authentic) == [EvidenceProvider.DORAR_HADITH, EvidenceProvider.HADEETHENC]
    for kind in ("HADITH_MEANING", "HADITH_INTERPRETATION"):
        plan = create_retrieval_plan(make_claim(kind, "HADITH", identity))
        assert [source.provider for source in plan.sources] == [EvidenceProvider.DORAR_HADITH]
        assert EvidenceProvider.DORAR_HADITH_EXPLANATION not in {x.provider for x in plan.sources}


def test_specialist_general_and_unsupported_routes_never_broadcast():
    cases = [
        (make_claim("FIQH_RULING", "FIQH", [{"type": "RULING", "value": "specific ruling"}]),
         [EvidenceProvider.DORAR_FEQHIA]),
        (make_claim("AQEEDAH", "AQEEDAH", [{"type": "OTHER", "value": "doctrinal proposition"}]),
         [EvidenceProvider.DORAR_AQEEDA]),
        (make_claim("SEERAH", "SEERAH", [{"type": "TEXT", "value": "specific seerah event"}]),
         [EvidenceProvider.DORAR_HISTORY]),
        (make_claim("ISLAMIC_HISTORY", "HISTORY", [{"type": "DATE", "value": "10 AH"}]),
         [EvidenceProvider.DORAR_HISTORY]),
        (make_claim("GENERAL_ISLAMIC_CLAIM", "GENERAL"), [EvidenceProvider.BAYAN]),
        (make_claim("ISLAMIC_EDUCATION", "GENERAL"), [EvidenceProvider.BAYAN]),
        (make_claim("OTHER", "NON_ISLAMIC"), []),
        (make_claim("NON_VERIFIABLE", "GENERAL", evidence=False), []),
    ]
    for item, expected in cases:
        assert providers(item) == expected
        assert len(providers(item)) <= 2


def test_target_attributes_and_priorities_are_provider_specific():
    hadith = make_claim("HADITH_AUTHENTICITY", "HADITH", [
        {"id": "attr_001", "type": "HADITH_TEXT", "value": "explicit hadith wording"},
        {"id": "attr_002", "type": "NARRATOR", "value": "claimed narrator"},
        {"id": "attr_003", "type": "SOURCE", "value": "claimed source"},
        {"id": "attr_004", "type": "AUTHENTICITY", "value": "claimed grade"},
        {"id": "attr_005", "type": "INTERPRETATION", "value": "claimed meaning"},
    ])
    plan = create_retrieval_plan(hadith)
    assert [source.priority for source in plan.sources] == [1, 2]
    for task in plan.tasks:
        assert task.target_attribute_ids == ["attr_001", "attr_002", "attr_003", "attr_004"]
    tafsir = create_retrieval_plan(make_claim("QURAN_INTERPRETATION", "QURAN", [
        {"id": "attr_001", "type": "QURAN_TEXT", "value": "verse wording"},
        {"id": "attr_002", "type": "INTERPRETATION", "value": "claimed interpretation"},
    ]))
    assert tafsir.tasks[0].provider == EvidenceProvider.DORAR_TAFSEER
    assert tafsir.tasks[0].target_attribute_ids == ["attr_002"]
    assert "attr_001" not in tafsir.tasks[0].target_attribute_ids
    assert create_retrieval_plan(make_claim("FIQH_RULING", "FIQH", [
        {"id": "attr_001", "type": "RULING", "value": "specific ruling"},
        {"id": "attr_002", "type": "SCHOLAR", "value": "claimed scholar"},
    ])).tasks[0].target_attribute_ids == ["attr_001"]


def test_hadith_query_is_identity_first_and_wrong_attribution_does_not_bias_it():
    item = make_claim("HADITH_ATTRIBUTION", "HADITH", [
        {"type": "HADITH_TEXT", "value": "the explicit hadith wording"},
        {"type": "NARRATOR", "value": "wrong narrator"},
        {"type": "SOURCE", "value": "wrong source"},
        {"type": "AUTHENTICITY", "value": "wrong grade"},
    ], text="the explicit hadith wording is attributed to wrong narrator",
       queries=["the explicit hadith wording", "wrong narrator wrong source"])
    original = item.model_dump(mode="json")
    for provider in (EvidenceProvider.DORAR_HADITH, EvidenceProvider.HADEETHENC):
        queries = select_provider_queries(item, provider, 2)
        assert queries[0] == "the explicit hadith wording"
        assert "wrong narrator" not in queries[0]
    assert item.model_dump(mode="json") == original


def test_queries_are_provider_specific_deduplicated_bounded_and_do_not_invent_facts():
    fiqh = make_claim("FIQH_RULING", "FIQH", [{"type": "RULING", "value": "witr prayer ruling"}],
                      text="witr prayer ruling", queries=["  witr   prayer ruling  ", "another legal phrase"])
    assert select_provider_queries(fiqh, EvidenceProvider.DORAR_FEQHIA, 2) == [
        "witr prayer ruling", "another legal phrase"]
    aqeeda = make_claim("AQEEDAH", "AQEEDAH", [{"type": "OTHER", "value": "complete doctrine proposition"}],
                        text="complete doctrine proposition")
    assert select_provider_queries(aqeeda, EvidenceProvider.DORAR_AQEEDA, 1) == [
        "complete doctrine proposition"]
    history = make_claim("ISLAMIC_HISTORY", "HISTORY", [
        {"type": "TEXT", "value": "named event"}, {"type": "DATE", "value": "10 AH"},
        {"type": "LOCATION", "value": "named city"}], text="named event")
    assert select_provider_queries(history, EvidenceProvider.DORAR_HISTORY, 1) == [
        "named event 10 AH named city"]


def test_tafseer_query_uses_only_supplied_parent_context():
    item = make_claim("QURAN_INTERPRETATION", "QURAN", [
        {"type": "INTERPRETATION", "value": "claimed interpretation"}],
        text="claimed interpretation", context={"type": "QURAN", "surah": "Al-Baqarah",
                                                  "ayah_number": "255", "text": "supplied verse text"})
    query = select_provider_queries(item, EvidenceProvider.DORAR_TAFSEER, 1)[0]
    assert query == "Al-Baqarah 255 supplied verse text claimed interpretation"


def test_hadith_interpretation_readiness_requires_record_identity():
    missing = make_claim("HADITH_INTERPRETATION", "HADITH", [
        {"type": "INTERPRETATION", "value": "claimed meaning"}])
    assert assess_retrieval_readiness(missing)[:2] == (False, ["HADITH_TEXT"])
    ready = make_claim("HADITH_INTERPRETATION", "HADITH", [
        {"type": "INTERPRETATION", "value": "claimed meaning"}],
        context={"type": "HADITH", "text": "explicit parent hadith wording"})
    assert assess_retrieval_readiness(ready)[0] is True


def test_shared_registration_and_explanation_is_not_a_search_route():
    settings = Settings(anthropic_api_key="")
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(500, request=request)))
    direct = build_provider_adapters(settings, client)
    api = build_service(settings, client).adapters
    application = VerificationOrchestrator(settings)._retrieval_service(client).adapters
    assert set(direct) == set(api) == set(application)
    expected = {EvidenceProvider.DORAR_HADITH, EvidenceProvider.DORAR_TAFSEER,
                EvidenceProvider.DORAR_FEQHIA, EvidenceProvider.DORAR_AQEEDA,
                EvidenceProvider.DORAR_HISTORY, EvidenceProvider.DORAR_HADITH_EXPLANATION}
    assert expected <= set(direct)
    for kind, domain in (("HADITH_TEXT", "HADITH"), ("HADITH_INTERPRETATION", "HADITH"),
                         ("GENERAL_ISLAMIC_CLAIM", "GENERAL")):
        assert EvidenceProvider.DORAR_HADITH_EXPLANATION not in providers(make_claim(kind, domain, [
            {"type": "HADITH_TEXT", "value": "explicit hadith wording"}] if domain == "HADITH" else []))
    result = asyncio.run(direct[EvidenceProvider.DORAR_HADITH_EXPLANATION].retrieve(
        make_claim("HADITH_TEXT", "HADITH", [{"type": "HADITH_TEXT", "value": "explicit hadith wording"}])))
    assert result.error.error_type == ProviderErrorType.NO_RESULTS
    asyncio.run(client.aclose())


def test_configured_limits_flow_into_adapter_and_plan(monkeypatch):
    import app.retrieval.providers.dorar_hadith as module
    seen = {}
    def fake(query, maximum):
        seen["query"] = query
        seen["maximum"] = maximum
        return {"results": []}
    monkeypatch.setattr(module, "retrieve_hadith", fake)
    instance = DorarHadithAdapter("https://dorar.net", None, MemoryCache(),
                                  max_attempts=1, max_results=4)
    item = make_claim("HADITH_TEXT", "HADITH", [{"type": "HADITH_TEXT", "value": "explicit hadith wording"}])
    asyncio.run(instance.retrieve(item))
    assert seen == {"query": "explicit hadith wording", "maximum": 4}
    plan = create_retrieval_plan(item,
        query_limits={EvidenceProvider.DORAR_HADITH: 1},
        result_limits={EvidenceProvider.DORAR_HADITH: 4})
    task = next(task for task in plan.tasks if task.provider == EvidenceProvider.DORAR_HADITH)
    assert task.max_results == 4 and len(task.queries) == 1
