import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.application.models import VerificationAccepted, VerificationRequest, VerificationResponse
from app.application.orchestrator import VerificationOrchestrator, initial_steps
from app.application.models import RequestStatus
from app.config.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["verification"])
REQUESTS: dict[str, VerificationResponse] = {}


def _save(response):
    REQUESTS[response.request_id] = response


async def _run(request_id: str, text: str):
    await VerificationOrchestrator(get_settings(), progress_callback=_save).verify_text(text, request_id)


@router.post("/verify", response_model=VerificationAccepted, status_code=202)
async def start_verification(payload: VerificationRequest, background_tasks: BackgroundTasks):
    request_id = f"verify_{uuid.uuid4().hex}"
    REQUESTS[request_id] = VerificationResponse(request_id=request_id, status=RequestStatus.PROCESSING,
                                                input_text=payload.text, execution=initial_steps())
    background_tasks.add_task(_run, request_id, payload.text)
    return VerificationAccepted(request_id=request_id, status=RequestStatus.PROCESSING)


@router.get("/verify/{request_id}", response_model=VerificationResponse)
def get_verification(request_id: str):
    if request_id not in REQUESTS:
        raise HTTPException(status_code=404, detail="Verification request not found")
    return REQUESTS[request_id]


@router.get("/health")
def api_health():
    return {"status": "ok", "phase": 6}
