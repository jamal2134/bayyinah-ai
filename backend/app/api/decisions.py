from fastapi import APIRouter

from app.decision.engine import decide_claim
from app.decision.models import ClaimDecision, ClaimDecisionRequest
from app.models.validation import EvidenceValidationResponse

router = APIRouter(prefix="/api/v1", tags=["decisions"])


@router.post("/decisions", response_model=ClaimDecision)
def create_decision(payload: EvidenceValidationResponse):
    """Accept an existing Phase 4 response directly."""
    return decide_claim(ClaimDecisionRequest(validation=payload))


@router.post("/decisions/with-claim", response_model=ClaimDecision)
def create_decision_with_claim(payload: ClaimDecisionRequest):
    """Use the upstream claim when optional/non-evidentiary attributes must be filtered."""
    return decide_claim(payload)
