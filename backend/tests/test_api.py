from fastapi.testclient import TestClient
import httpx

from app.api.retrieval import build_service
from app.api.claims import get_claim_service
from app.config.settings import Settings
from app.main import app
from app.models.evidence import EvidenceProvider
from conftest import claim, valid_result


class Service:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
    def extract(self, text, request_id=None):
        if self.error:
            raise self.error
        return self.result


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok", "phase": 6}


def test_dorar_api_is_disabled_by_default():
    service = build_service(Settings(_env_file=None), httpx.AsyncClient())
    try:
        assert EvidenceProvider.DORAR not in service.adapters
    finally:
        import asyncio
        asyncio.run(service.adapters[EvidenceProvider.QURANPEDIA].client.aclose())


def test_extract_endpoint():
    from app.models.claim import ExtractionResult
    app.dependency_overrides[get_claim_service] = lambda: Service(ExtractionResult.model_validate(valid_result([claim()])))
    try:
        response = TestClient(app).post("/api/v1/claims/extract", json={"text": "claim"})
        assert response.status_code == 200
        assert response.json()["claim_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_empty_input_rejected():
    response = TestClient(app).post("/api/v1/claims/extract", json={"text": ""})
    assert response.status_code == 422


def test_api_error():
    from app.agents.claim_extractor import ClaimExtractionError
    app.dependency_overrides[get_claim_service] = lambda: Service(error=ClaimExtractionError("upstream unavailable"))
    try:
        response = TestClient(app).post("/api/v1/claims/extract", json={"text": "claim"})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()

