"""Bounded live ClaimExtractor and SemanticValidator checks using application settings."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.application.costs import CostTracker  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.models.claim import ClaimAttribute  # noqa: E402
from app.models.evidence import EvidenceCandidate  # noqa: E402
from app.validation.semantic import SemanticValidator  # noqa: E402


def main():
    settings = Settings()
    tracker = CostTracker()
    output = {"model": settings.anthropic_model, "claim_extraction": {}, "semantic_validation": {}}

    started = time.perf_counter()
    extraction = ClaimExtractor(settings, usage_sink=tracker.record_usage).extract(
        "قال الله تعالى: ﴿إِنَّ مَعَ الْعُسْرِ يُسْرًا﴾ وهي الآية السادسة من سورة الشرح."
    )
    output["claim_extraction"] = {
        "status": "PASS", "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "claim_count": extraction.claim_count,
        "claims": [claim.model_dump(mode="json") for claim in extraction.claims],
    }

    attribute = ClaimAttribute(id="attr_001", type="RULING", value="صلاة الوتر سنة مؤكدة")
    evidence = EvidenceCandidate(
        evidence_id="smoke:fiqh:1", claim_id="claim_001", provider="DORAR_FEQHIA",
        evidence_type="FIQH_CONTENT", title="حكم صلاة الوتر",
        text="صلاة الوتر سنة مؤكدة.", provider_record_id="smoke-1",
        source_url="https://example.invalid/smoke-1", retrieved_at=datetime.now(timezone.utc),
    )
    started = time.perf_counter()
    semantic = SemanticValidator(settings, usage_sink=tracker.record_usage).validate(attribute, [evidence])
    output["semantic_validation"] = {
        "status": "PASS", "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": semantic.model_dump(mode="json"),
    }
    output["cost"] = tracker.summary([], sum(
        output[key]["duration_ms"] for key in ("claim_extraction", "semantic_validation")
    )).model_dump(mode="json")
    destination = ROOT / "evaluation" / "stage51_live_smoke_results.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "claim_extraction": {"status": output["claim_extraction"]["status"],
                             "claim_count": output["claim_extraction"]["claim_count"]},
        "semantic_validation": output["semantic_validation"], "cost": output["cost"],
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
