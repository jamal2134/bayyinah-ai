from fastapi import APIRouter

from app.config.settings import get_settings
from app.models.validation import EvidenceValidationRequest, EvidenceValidationResponse
from app.validation.semantic import SemanticValidator
from app.validation.service import EvidenceValidationService

router = APIRouter(prefix="/api/v1", tags=["validation"])


def get_validation_service() -> EvidenceValidationService:
    settings = get_settings()
    semantic = SemanticValidator(settings) if settings.anthropic_api_key else None
    return EvidenceValidationService(semantic)


@router.post("/validation", response_model=EvidenceValidationResponse)
def validate_evidence(payload: EvidenceValidationRequest):
    candidates = list(payload.evidence_candidates)
    if payload.retrieval_result:
        candidates.extend(
            item
            for provider_result in payload.retrieval_result.provider_results
            for item in provider_result.evidence
            if item.evidence_id not in {candidate.evidence_id for candidate in candidates}
        )
    return get_validation_service().validate(payload.claim, candidates, payload.retrieval_result)
