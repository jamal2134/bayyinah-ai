import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.claims import router as claims_router
from app.api.retrieval import router as retrieval_router
from app.api.validation import router as validation_router
from app.api.decisions import router as decisions_router
from app.api.reports import router as reports_router
from app.api.verification import router as verification_router
from app.config.settings import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"level": record.levelname, "logger": record.name, "message": record.getMessage()}
        for key in ("request_id", "input_length", "detected_language", "claim_count", "processing_time_ms", "model", "success", "attempt", "error_type", "error_message", "status_code", "validation_error_count", "validation_stage", "attribute_id", "unknown_evidence_id_count"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=get_settings().log_level, handlers=[handler], force=True)

app = FastAPI(title="Bayyinah AI", version="2.0.0")
app.include_router(claims_router)
app.include_router(retrieval_router)
app.include_router(validation_router)
app.include_router(decisions_router)
app.include_router(reports_router)
app.include_router(verification_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/health")
def health():
    return {"status": "ok", "phase": 6}


frontend_dir = Path(__file__).parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

