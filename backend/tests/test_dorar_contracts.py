import inspect
import json
from pathlib import Path

from app.retrieval.providers.dorar_retrievers import (
    DORAR_HADITH_EXPLANATION, dorar_aqeeda_search, dorar_feqhia_search,
    dorar_hadith_clean, dorar_history_search, dorar_tafseer_clean,
)


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "dorar_contracts.json").read_text(encoding="utf-8"))


def parameters(function):
    return list(inspect.signature(function).parameters)


def test_authoritative_callable_signatures_are_frozen():
    assert parameters(dorar_hadith_clean.retrieve_hadith) == ["query", "max_results"]
    assert inspect.signature(dorar_hadith_clean.retrieve_hadith).parameters["max_results"].default == 15
    assert parameters(DORAR_HADITH_EXPLANATION.get_sharh_by_id) == ["sharh_id", "hadith_id"]
    assert inspect.signature(DORAR_HADITH_EXPLANATION.get_sharh_by_id).parameters["hadith_id"].default == ""
    assert parameters(dorar_tafseer_clean.export_tafseer) == ["query"]
    assert parameters(dorar_feqhia_search.retrieve_feqhia) == ["query", "max_results"]
    assert inspect.signature(dorar_feqhia_search.retrieve_feqhia).parameters["max_results"].default == 15
    assert parameters(dorar_aqeeda_search.retrieve_aqeeda) == ["query", "max_results"]
    assert inspect.signature(dorar_aqeeda_search.retrieve_aqeeda).parameters["max_results"].default == 15
    assert parameters(dorar_history_search.search_history) == ["query"]


def test_representative_contract_fields_are_frozen():
    assert set(FIXTURES["hadith"]["results"][0]) == {"rank", "hadith_id", "hadith_text", "narrator", "scholar", "source", "page_or_number", "grade", "takhrij", "categories", "explanation_available", "explanation_id", "url"}
    assert set(FIXTURES["hadith_explanation"]) == {"source", "hadith_id", "explanation_id", "hadith_text", "narrator", "scholar", "hadith_source", "page_or_number", "grade", "takhrij", "explanation", "url"}
    assert set(FIXTURES["tafseer"]["results"][0]) == {"search_match", "source_url", "page_url", "matched_section", "surah_id", "page_id", "page_title", "headings", "sections"}
    assert set(FIXTURES["feqhia"]["results"][0]) == {"rank", "feqhia_id", "title", "url", "content"}
    assert set(FIXTURES["aqeeda"]["results"][0]) == {"rank", "aqeeda_id", "title", "url", "content"}
    assert set(FIXTURES["history"][0]) == {"event_id", "title", "hijri_year", "gregorian_year", "details", "url"}
