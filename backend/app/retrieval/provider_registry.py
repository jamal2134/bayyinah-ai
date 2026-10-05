from app.models.evidence import EvidenceProvider
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.bayan import BayanAdapter
from app.retrieval.providers.dorar import DorarAdapter
from app.retrieval.providers.dorar_aqeeda import DorarAqeedaAdapter
from app.retrieval.providers.dorar_feqhia import DorarFeqhiaAdapter
from app.retrieval.providers.dorar_hadith import DorarHadithAdapter
from app.retrieval.providers.dorar_hadith_explanation import DorarHadithExplanationAdapter
from app.retrieval.providers.dorar_history import DorarHistoryAdapter
from app.retrieval.providers.dorar_tafseer import DorarTafseerAdapter
from app.retrieval.providers.hadeethenc import HadeethEncAdapter
from app.retrieval.providers.quranpedia import QuranpediaAdapter


def build_provider_adapters(settings, client):
    """Build the single provider set shared by the retrieval API and full application."""
    cache = MemoryCache()
    adapters = {
        EvidenceProvider.QURANPEDIA: QuranpediaAdapter(
            settings.quranpedia_base_url, client, cache,
            max_attempts=settings.max_provider_query_attempts,
            max_concurrency=settings.quranpedia_max_concurrency),
        EvidenceProvider.HADEETHENC: HadeethEncAdapter(
            settings.hadeethenc_base_url, client, cache,
            max_attempts=settings.max_provider_query_attempts,
            max_concurrency=settings.hadeethenc_max_concurrency),
        EvidenceProvider.BAYAN: BayanAdapter(
            settings.bayan_base_url, client, cache,
            max_attempts=settings.max_provider_query_attempts,
            max_concurrency=settings.bayan_max_concurrency),
    }
    common = {"base_url": settings.dorar_base_url, "client": client, "cache": cache,
              "max_concurrency": settings.dorar_max_concurrency}
    if settings.dorar_enabled:
        adapters[EvidenceProvider.DORAR] = DorarAdapter(
            max_attempts=settings.max_provider_query_attempts, **common)
    if settings.dorar_hadith_enabled:
        adapters[EvidenceProvider.DORAR_HADITH] = DorarHadithAdapter(
            max_attempts=settings.dorar_hadith_max_queries,
            max_results=settings.dorar_hadith_max_results, **common)
    if settings.dorar_hadith_explanation_enabled:
        adapters[EvidenceProvider.DORAR_HADITH_EXPLANATION] = DorarHadithExplanationAdapter(
            max_attempts=1, **common)
    if settings.dorar_tafseer_enabled:
        adapters[EvidenceProvider.DORAR_TAFSEER] = DorarTafseerAdapter(
            max_attempts=settings.dorar_tafseer_max_queries, **common)
    if settings.dorar_feqhia_enabled:
        adapters[EvidenceProvider.DORAR_FEQHIA] = DorarFeqhiaAdapter(
            max_attempts=settings.dorar_feqhia_max_queries,
            max_results=settings.dorar_feqhia_max_results, **common)
    if settings.dorar_aqeeda_enabled:
        adapters[EvidenceProvider.DORAR_AQEEDA] = DorarAqeedaAdapter(
            max_attempts=settings.dorar_aqeeda_max_queries,
            max_results=settings.dorar_aqeeda_max_results, **common)
    if settings.dorar_history_enabled:
        adapters[EvidenceProvider.DORAR_HISTORY] = DorarHistoryAdapter(
            max_attempts=settings.dorar_history_max_queries, **common)
    return adapters
