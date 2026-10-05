from fastapi import APIRouter

from app.reporting.builder import build_verification_report
from app.reporting.models import TraceableVerificationReport, VerificationReportRequest

router = APIRouter(prefix="/api/v1", tags=["reports"])


@router.post("/reports", response_model=TraceableVerificationReport)
def create_report(payload: VerificationReportRequest):
    """Render Phase 2–5 structured output without retrieval, validation, or decision-making."""
    return build_verification_report(payload.claim, payload.evidence_candidates,
                                     payload.validation, payload.decision)
