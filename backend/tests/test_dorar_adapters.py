import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.models.claim import AttributeType, Claim, ClaimAttribute, ClaimType, Domain
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import ProviderErrorType, RetrievalPurpose, RetrievalTask
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.dorar_aqeeda import DorarAqeedaAdapter
from app.retrieval.providers.dorar_feqhia import DorarFeqhiaAdapter
from app.retrieval.providers.dorar_hadith import DorarHadithAdapter
from app.retrieval.providers.dorar_hadith_explanation import DorarHadithExplanationAdapter
from app.retrieval.providers.dorar_history import DorarHistoryAdapter
from app.retrieval.providers.dorar_tafseer import DorarTafseerAdapter


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "dorar_contracts.json").read_text(encoding="utf-8"))


def claim(identifier="claim_001", query="sample query"):
    return Claim(id=identifier, original_text=query, normalized_claim=query,
                 claim_type=ClaimType.GENERAL_ISLAMIC_CLAIM, domain=Domain.GENERAL,
                 search_queries=[query], attributes=[ClaimAttribute(type=AttributeType.TEXT, value=query)],
                 requires_evidence=True, reason="test")


def adapter(kind):
    return kind("https://dorar.net", client=None, cache=MemoryCache(), max_attempts=1, max_concurrency=1)


def run(awaitable):
    return asyncio.run(awaitable)


def test_schema_and_legacy_provider_are_backward_compatible():
    old = EvidenceCandidate(evidence_id="old", claim_id="claim_001", provider="DORAR",
        evidence_type="HADITH", text="original", retrieved_at=datetime.now(timezone.utc))
    assert old.provider == EvidenceProvider.DORAR
    assert old.parent_evidence_id is None and old.fragment_id is None
    assert old.structured_fields == {}
    assert {item.value for item in EvidenceProvider} >= {
        "DORAR", "DORAR_HADITH", "DORAR_HADITH_EXPLANATION", "DORAR_TAFSEER",
        "DORAR_FEQHIA", "DORAR_AQEEDA", "DORAR_HISTORY"}
    assert {item.value for item in EvidenceType} >= {
        "HADITH_EXPLANATION", "TAFSEER_SECTION", "FIQH_CONTENT",
        "AQEEDA_CONTENT", "HISTORY_EVENT"}
    task = RetrievalTask(task_id="task_001", claim_id="claim_001", target_attribute_ids=[],
                         provider="DORAR", purpose=RetrievalPurpose.HADITH_SOURCE_AND_JUDGMENT)
    assert task.query is None and task.queries == [] and task.max_results is None


def test_hadith_normalizes_multiple_records_and_preserves_original(monkeypatch):
    import app.retrieval.providers.dorar_hadith as module
    monkeypatch.setattr(module, "retrieve_hadith", lambda query, maximum: FIXTURES["hadith"])
    result = run(adapter(DorarHadithAdapter).retrieve(claim()))
    assert result.success and len(result.evidence) == 2
    first = result.evidence[0]
    row = FIXTURES["hadith"]["results"][0]
    assert first.text == row["hadith_text"] and first.source_url == row["url"]
    assert first.provider_record_id == row["hadith_id"] and first.result_rank == row["rank"]
    assert first.narrator == row["narrator"] and first.scholar == row["scholar"]
    assert first.judgment == row["grade"]
    assert first.structured_fields["explanation_available"] is True
    assert first.structured_fields["explanation_id"] == "X1"
    assert first.raw_metadata == row


def test_hadith_empty_and_failure_are_retrieval_outcomes(monkeypatch):
    import app.retrieval.providers.dorar_hadith as module
    monkeypatch.setattr(module, "retrieve_hadith", lambda query, maximum: {"results": []})
    empty = run(adapter(DorarHadithAdapter).retrieve(claim()))
    assert not empty.success and empty.error.error_type == ProviderErrorType.NO_RESULTS
    monkeypatch.setattr(module, "retrieve_hadith", lambda query, maximum: (_ for _ in ()).throw(requests.Timeout("late")))
    failed = run(adapter(DorarHadithAdapter).retrieve(claim()))
    assert not failed.success and failed.error.error_type == ProviderErrorType.TIMEOUT


def test_explanation_preserves_content_ids_parent_and_metadata(monkeypatch):
    import app.retrieval.providers.dorar_hadith_explanation as module
    row = FIXTURES["hadith_explanation"]
    monkeypatch.setattr(module, "get_sharh_by_id", lambda sharh_id, hadith_id: row)
    result = run(adapter(DorarHadithExplanationAdapter).retrieve_by_id(
        "claim_001", "X1", "H1", parent_evidence_id="dorar-hadith:H1"))
    item = result.evidence[0]
    assert item.text == row["explanation"] and item.provider_record_id == "X1"
    assert item.parent_evidence_id == "dorar-hadith:H1" and item.source_url == row["url"]
    assert item.structured_fields["hadith_id"] == "H1" and item.raw_metadata == row


def test_explanation_failure_is_structured(monkeypatch):
    import app.retrieval.providers.dorar_hadith_explanation as module
    monkeypatch.setattr(module, "get_sharh_by_id", lambda *args: (_ for _ in ()).throw(requests.ConnectionError("down")))
    result = run(adapter(DorarHadithExplanationAdapter).retrieve_by_id("claim_001", "X1"))
    assert not result.success and result.error.error_type == ProviderErrorType.NETWORK_ERROR


def test_tafseer_creates_stable_exact_fragments_and_preserves_page(monkeypatch):
    import app.retrieval.providers.dorar_tafseer as module
    monkeypatch.setattr(module, "export_tafseer", lambda query: FIXTURES["tafseer"])
    first = run(adapter(DorarTafseerAdapter).retrieve(claim()))
    second = run(adapter(DorarTafseerAdapter).retrieve(claim()))
    assert [x.evidence_id for x in first.evidence] == [x.evidence_id for x in second.evidence]
    assert [x.text for x in first.evidence] == ["Exact section A", "Exact section B"]
    assert {x.fragment_label for x in first.evidence} == {"Section A", "Section B"}
    assert all(x.raw_metadata == FIXTURES["tafseer"]["results"][0] for x in first.evidence)
    assert first.query_attempts[0].parameters["page_failures"][0]["error"] == "detail failed"


def test_tafseer_failure_is_structured(monkeypatch):
    import app.retrieval.providers.dorar_tafseer as module
    monkeypatch.setattr(module, "export_tafseer", lambda query: (_ for _ in ()).throw(requests.Timeout("late")))
    result = run(adapter(DorarTafseerAdapter).retrieve(claim()))
    assert result.error.error_type == ProviderErrorType.TIMEOUT


def test_feqhia_skipped_is_trace_not_evidence_and_no_metadata_is_invented(monkeypatch):
    import app.retrieval.providers.dorar_feqhia as module
    monkeypatch.setattr(module, "retrieve_feqhia", lambda query, maximum: FIXTURES["feqhia"])
    result = run(adapter(DorarFeqhiaAdapter).retrieve(claim()))
    item = result.evidence[0]
    assert len(result.evidence) == 1 and item.text == "Exact original fiqh content"
    assert item.source_url.endswith("/F1") and item.raw_metadata == FIXTURES["feqhia"]["results"][0]
    assert item.scholar is None and "school" not in item.structured_fields
    assert result.query_attempts[0].parameters["skipped"] == FIXTURES["feqhia"]["skipped"]


def test_aqeeda_skipped_is_trace_not_evidence_and_no_metadata_is_invented(monkeypatch):
    import app.retrieval.providers.dorar_aqeeda as module
    monkeypatch.setattr(module, "retrieve_aqeeda", lambda query, maximum: FIXTURES["aqeeda"])
    result = run(adapter(DorarAqeedaAdapter).retrieve(claim()))
    item = result.evidence[0]
    assert len(result.evidence) == 1 and item.text == "Exact original aqeeda content"
    assert item.source_url.endswith("/A1") and item.raw_metadata == FIXTURES["aqeeda"]["results"][0]
    assert item.scholar is None and "school" not in item.structured_fields
    assert result.query_attempts[0].parameters["skipped"] == FIXTURES["aqeeda"]["skipped"]


def test_feqhia_and_aqeeda_empty_and_failures_are_structured(monkeypatch):
    import app.retrieval.providers.dorar_feqhia as feqhia_module
    import app.retrieval.providers.dorar_aqeeda as aqeeda_module
    cases = [
        (DorarFeqhiaAdapter, feqhia_module, "retrieve_feqhia"),
        (DorarAqeedaAdapter, aqeeda_module, "retrieve_aqeeda"),
    ]
    for kind, module, function_name in cases:
        monkeypatch.setattr(module, function_name, lambda query, maximum: {"results": [], "skipped": []})
        assert run(adapter(kind).retrieve(claim())).error.error_type == ProviderErrorType.NO_RESULTS
        monkeypatch.setattr(module, function_name,
            lambda query, maximum: (_ for _ in ()).throw(requests.ConnectionError("down")))
        assert run(adapter(kind).retrieve(claim())).error.error_type == ProviderErrorType.NETWORK_ERROR


def test_history_preserves_event_details_years_url_empty_and_failure(monkeypatch):
    import app.retrieval.providers.dorar_history as module
    monkeypatch.setattr(module, "search_history", lambda query: FIXTURES["history"])
    result = run(adapter(DorarHistoryAdapter).retrieve(claim()))
    item = result.evidence[0]
    assert item.text == "Exact original event details" and item.provider_record_id == "E1"
    assert item.structured_fields["hijri_year"] == "10 هـ"
    assert item.structured_fields["gregorian_year"] == "632 م"
    assert item.source_url.endswith("/E1") and item.raw_metadata == FIXTURES["history"][0]
    monkeypatch.setattr(module, "search_history", lambda query: [])
    assert run(adapter(DorarHistoryAdapter).retrieve(claim())).error.error_type == ProviderErrorType.NO_RESULTS
    monkeypatch.setattr(module, "search_history", lambda query: (_ for _ in ()).throw(requests.ConnectionError("down")))
    assert run(adapter(DorarHistoryAdapter).retrieve(claim())).error.error_type == ProviderErrorType.NETWORK_ERROR


def test_fixed_debug_file_retriever_calls_are_serialized(monkeypatch):
    import app.retrieval.providers.dorar_hadith as module
    state = {"active": 0, "maximum": 0}
    guard = threading.Lock()
    def slow(query, maximum):
        with guard:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.03)
        with guard:
            state["active"] -= 1
        return FIXTURES["hadith"]
    monkeypatch.setattr(module, "retrieve_hadith", slow)
    instance = adapter(DorarHadithAdapter)
    async def both():
        return await asyncio.gather(instance.retrieve(claim("claim_001")),
                                    instance.retrieve(claim("claim_002")))
    results = run(both())
    assert all(result.success for result in results)
    assert state["maximum"] == 1
