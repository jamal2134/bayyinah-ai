import logging
import time
import uuid

from app.agents.claim_extractor import ClaimExtractor
from app.models.claim import ExtractionResult

logger = logging.getLogger(__name__)


class ClaimService:
    def __init__(self, extractor: ClaimExtractor):
        self.extractor = extractor

    def extract(self, text: str, request_id: str | None = None) -> ExtractionResult:
        request_id = request_id or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            result = self.extractor.extract(text)
            logger.info("claim_extraction", extra={
                "request_id": request_id, "input_length": len(text),
                "detected_language": result.input_language, "claim_count": result.claim_count,
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
                "model": self.extractor.settings.anthropic_model, "success": True,
            })
            return result
        except Exception:
            logger.exception("claim_extraction", extra={
                "request_id": request_id, "input_length": len(text),
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
                "model": self.extractor.settings.anthropic_model, "success": False,
            })
            raise

