import asyncio
import os

import httpx
import pytest

from app.config.settings import Settings
from app.retrieval.cache import MemoryCache
from app.retrieval.providers.quranpedia import QuranpediaAdapter
from test_retrieval import make_claim


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_RETRIEVAL_TESTS") != "1",
                    reason="set RUN_LIVE_RETRIEVAL_TESTS=1 to call real providers")
def test_live_quranpedia_ayat_al_kursi():
    settings = Settings()
    async def run():
        async with httpx.AsyncClient(timeout=20) as client:
            provider = QuranpediaAdapter(settings.quranpedia_base_url, client, MemoryCache())
            claim = make_claim("QURAN", "QURAN_RECORD", attributes=[
                {"type": "SURAH", "value": "البقرة"}, {"type": "AYAH_NUMBER", "value": "255"}])
            return await provider.retrieve(claim)
    result = asyncio.run(run())
    assert result.success
    assert result.evidence[0].provider == "QURANPEDIA"
