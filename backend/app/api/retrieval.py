import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from app.agents.claim_extractor import ClaimExtractionError, ClaimExtractor
from app.config.settings import get_settings
from app.models.claim import Claim
from app.models.retrieval import ExtractAndRetrieveResult, RetrievalResult, RetrieveTextRequest
from app.retrieval.provider_registry import build_provider_adapters
from app.retrieval.service import RetrievalService

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def build_service(settings, client):
    return RetrievalService(build_provider_adapters(settings, client))


def timeout(settings):
    return httpx.Timeout(settings.http_read_timeout, connect=settings.http_connect_timeout)


@router.post("/retrieval", response_model=RetrievalResult)
async def retrieve_claim(claim: Claim):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=timeout(settings), follow_redirects=False) as client:
        return await build_service(settings, client).retrieve(claim)


@router.post("/verify/retrieve", response_model=ExtractAndRetrieveResult)
async def extract_and_retrieve(payload: RetrieveTextRequest):
    settings = get_settings()
    try:
        extraction = await asyncio.to_thread(ClaimExtractor(settings).extract, payload.text)
    except ClaimExtractionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    async with httpx.AsyncClient(timeout=timeout(settings), follow_redirects=False) as client:
        service = build_service(settings, client)
        retrieval = await asyncio.gather(*[service.retrieve(claim) for claim in extraction.claims])
    return ExtractAndRetrieveResult(extraction=extraction, retrieval=retrieval)

