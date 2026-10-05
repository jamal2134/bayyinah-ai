import asyncio
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.application.costs import CostTracker
from app.application.models import CostStatus, ProviderCallSummary, RequestStatus, StepName
from app.application.orchestrator import VerificationOrchestrator
from app.config.settings import Settings
from app.main import app
from app.models.claim import Claim, ExtractionResult
from app.models.retrieval import RetrievalPlan, RetrievalResult, RetrievalStatus
from app.models.validation import EvidenceValidationResponse


def claim(identifier, text):
    return Claim.model_validate({"id": identifier, "original_text": text, "normalized_claim": text,
        "claim_type": "GENERAL_ISLAMIC_CLAIM", "domain": "GENERAL", "search_queries": ["اختبار مطالبة عربية"],
        "entities": [], "attributes": [{"id": "attr_001", "type": "TEXT", "value": text,
        "requires_evidence": True}], "requires_evidence": True, "reason": "Test claim."})


class FakeExtractor:
    def __init__(self, claims, calls): self.claims, self.calls = claims, calls
    def extract(self, text):
        self.calls.append("extract")
        return ExtractionResult(input_language="ar", claim_count=len(self.claims), claims=self.claims)


class FakeRetrieval:
    def __init__(self, calls): self.calls = calls
    async def retrieve(self, item):
        self.calls.append(f"retrieve:{item.id}")
        return RetrievalResult(claim_id=item.id, retrieval_plan=RetrievalPlan(claim_id=item.id, sources=[]),
            provider_results=[], total_evidence_candidates=0, retrieval_status=RetrievalStatus.NO_RESULTS)


class FakeValidation:
    def __init__(self, calls): self.calls = calls
    def validate(self, item, evidence, retrieval):
        self.calls.append(f"validate:{item.id}")
        return EvidenceValidationResponse.model_validate({"claim_id": item.id, "validation_status": "COMPLETED",
            "validations": [{"attribute_id": "attr_001", "attribute_type": "TEXT", "claimed_value": item.original_text,
            "status": "SUPPORTED", "rationale": "fixture", "validation_method": "deterministic"}]})


def test_cost_calculation_aggregation_cache_categories_and_sar():
    tracker = CostTracker()
    usage = SimpleNamespace(input_tokens=1000, output_tokens=100,
                            cache_creation_input_tokens=200, cache_read_input_tokens=300)
    tracker.record_usage("CLAIM_EXTRACTION", "claude-sonnet-4-5", usage)
    tracker.record_usage("SEMANTIC_VALIDATION", "claude-sonnet-4-5",
                         SimpleNamespace(input_tokens=500, output_tokens=50))
    summary = tracker.summary([ProviderCallSummary(provider="QURANPEDIA", request_count=2)], 123)
    expected = Decimal("0.0045") + Decimal("0.00075") + Decimal("0.00009") + Decimal("0.00225")
    assert summary.estimated_cost_usd == expected
    assert summary.estimated_cost_sar == expected * Decimal("3.75")
    assert summary.input_tokens == 1500 and summary.output_tokens == 150
    assert summary.provider_calls == 2 and summary.duration_ms == 123


def test_unknown_model_never_fabricates_cost():
    tracker = CostTracker()
    tracker.record_usage("CLAIM_EXTRACTION", "unknown-model", SimpleNamespace(input_tokens=10, output_tokens=5))
    summary = tracker.summary([], 1)
    assert summary.cost_status == CostStatus.PRICING_UNAVAILABLE
    assert summary.estimated_cost_usd is None and summary.estimated_cost_sar is None


def test_orchestrator_multiple_claims_order_trace_and_decision_preservation():
    calls, snapshots = [], []
    claims = [claim("claim_001", "المطالبة الأولى"), claim("claim_002", "المطالبة الثانية")]
    orchestrator = VerificationOrchestrator(Settings(), extractor=FakeExtractor(claims, calls),
        retrieval_service=FakeRetrieval(calls), validation_service=FakeValidation(calls),
        progress_callback=lambda value: snapshots.append(value))
    result = asyncio.run(orchestrator.verify_text("نص متعدد", "verify_test"))
    assert result.status == RequestStatus.COMPLETED
    assert [x.report.decision.value for x in result.claims] == ["SUPPORTED", "SUPPORTED"]
    assert [x.step for x in result.execution] == list(StepName)
    assert all(x.status.value == "COMPLETED" for x in result.execution)
    assert calls[0] == "extract"
    assert calls.index("retrieve:claim_002") < calls.index("validate:claim_001")
    assert snapshots and result.cost.duration_ms >= 0


def test_api_accepts_and_returns_structured_failure_without_secret(monkeypatch):
    from app.api import verification
    async def fake_run(request_id, text):
        item = verification.REQUESTS[request_id]
        item.status = RequestStatus.FAILED
        item.error = "تعذر إكمال عملية التحقق."
        verification.REQUESTS[request_id] = item
    monkeypatch.setattr(verification, "_run", fake_run)
    response = TestClient(app).post("/api/v1/verify", json={"text": "اختبار مطالبة عربية"})
    assert response.status_code == 202
    final = TestClient(app).get(f"/api/v1/verify/{response.json()['request_id']}")
    assert final.json()["status"] == "FAILED"
    assert "ANTHROPIC_API_KEY" not in final.text


def test_api_success_contract(monkeypatch):
    from app.api import verification
    async def fake_run(request_id, text):
        item = verification.REQUESTS[request_id]
        item.status = RequestStatus.COMPLETED
        verification.REQUESTS[request_id] = item
    monkeypatch.setattr(verification, "_run", fake_run)
    response = TestClient(app).post("/api/v1/verify", json={"text": "اختبار مطالبة عربية"})
    final = TestClient(app).get(f"/api/v1/verify/{response.json()['request_id']}")
    assert response.status_code == 202 and final.status_code == 200
    assert final.json()["status"] == "COMPLETED"
    assert len(final.json()["execution"]) == 6


def test_frontend_is_arabic_rtl_and_contains_safe_states():
    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert 'lang="ar" dir="rtl"' in page.text
    script = TestClient(app).get("/assets/app.js").text
    assert "status-INSUFFICIENT_EVIDENCE" not in script  # styles status; script does not decide it
    assert "تعذر إكمال عملية التحقق" in script
    assert "نص المصدر أو الدليل" in script
    assert "النتيجة النهائية" in script
    assert "التفاصيل التقنية" not in script
