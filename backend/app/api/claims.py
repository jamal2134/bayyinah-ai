from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.claim_extractor import ClaimExtractionError, ClaimExtractor
from app.config.settings import get_settings
from app.models.claim import ExtractionRequest, ExtractionResult
from app.services.claim_service import ClaimService

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


def get_claim_service() -> ClaimService:
    # Delay client construction until after FastAPI has validated the request body.
    class LazyExtractor:
        settings = get_settings()

        def extract(self, text: str):
            return ClaimExtractor(self.settings).extract(text)

    return ClaimService(LazyExtractor())


@router.post("/extract", response_model=ExtractionResult)
def extract_claims(payload: ExtractionRequest, request: Request, service: ClaimService = Depends(get_claim_service)):
    try:
        return service.extract(payload.text, getattr(request.state, "request_id", None))
    except ClaimExtractionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

