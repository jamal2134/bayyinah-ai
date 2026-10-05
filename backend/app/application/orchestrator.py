import asyncio
import logging
import time
from collections import Counter
from datetime import datetime, timezone

import httpx

from app.agents.claim_extractor import ClaimExtractor
from app.application.costs import CostTracker
from app.application.models import (
    ClaimVerificationResult, ExecutionStep, ProviderCallSummary, RequestStatus,
    StepName, StepStatus, VerificationResponse,
)
from app.config.settings import Settings
from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.reporting.builder import build_overall_report, build_verification_report
from app.retrieval.provider_registry import build_provider_adapters
from app.retrieval.service import RetrievalService
from app.validation.semantic import SemanticValidator
from app.validation.service import EvidenceValidationService
from app.validation.evidence_matcher import aggregate_quran_alignment

logger = logging.getLogger(__name__)


STEP_TITLES = {
    StepName.ANALYZE_TEXT: "تحليل النص", StepName.RETRIEVE_EVIDENCE: "البحث عن الأدلة",
    StepName.ALIGN_EVIDENCE: "مطابقة الأدلة", StepName.VALIDATE_EVIDENCE: "التحقق من الأدلة",
    StepName.MAKE_DECISION: "تحديد النتيجة", StepName.BUILD_REPORT: "إعداد التقرير",
}


def initial_steps():
    return [ExecutionStep(step=step, title_ar=STEP_TITLES[step]) for step in StepName]


class VerificationOrchestrator:
    def __init__(self, settings: Settings, *, extractor=None, retrieval_service=None,
                 validation_service=None, progress_callback=None):
        self.settings = settings
        self.extractor = extractor
        self.retrieval_service = retrieval_service
        self.validation_service = validation_service
        self.progress_callback = progress_callback

    async def verify_text(self, text: str, request_id: str) -> VerificationResponse:
        started = time.perf_counter()
        response = VerificationResponse(request_id=request_id, status=RequestStatus.PROCESSING,
                                        input_text=text, execution=initial_steps())
        tracker = CostTracker()
        http_client = None
        try:
            extractor = self.extractor or ClaimExtractor(self.settings, usage_sink=tracker.record_usage)
            await self._start(response, StepName.ANALYZE_TEXT)
            extraction = await asyncio.to_thread(extractor.extract, text)
            await self._finish(response, StepName.ANALYZE_TEXT,
                f"تم استخراج {extraction.claim_count} مطالبة قابلة للمعالجة.",
                {"claim_count": extraction.claim_count,
                 "claims": [claim.original_text for claim in extraction.claims]})

            service = self.retrieval_service
            if service is None:
                http_client = httpx.AsyncClient(timeout=httpx.Timeout(
                    self.settings.http_read_timeout, connect=self.settings.http_connect_timeout),
                    follow_redirects=False)
                service = self._retrieval_service(http_client)
            await self._start(response, StepName.RETRIEVE_EVIDENCE)
            if isinstance(service, RetrievalService):
                retrievals = [None] * len(extraction.claims)
                root_indexes = [index for index, claim in enumerate(extraction.claims)
                                if not claim.parent_claim_id]
                root_results = await asyncio.gather(*[
                    service.retrieve(extraction.claims[index]) for index in root_indexes
                ])
                for index, result in zip(root_indexes, root_results):
                    retrievals[index] = result
                by_id = {claim.id: index for index, claim in enumerate(extraction.claims)}
                for index, claim in enumerate(extraction.claims):
                    if retrievals[index] is not None:
                        continue
                    parent_alignment = None
                    parent_claim = (extraction.claims[by_id[claim.parent_claim_id]]
                                    if claim.parent_claim_id in by_id else None)
                    if claim.claim_type.value == "QURAN_INTERPRETATION" and claim.parent_claim_id in by_id:
                        parent_index = by_id[claim.parent_claim_id]
                        parent_retrieval = retrievals[parent_index]
                        parent_evidence = [evidence for provider in parent_retrieval.provider_results
                                           for evidence in provider.evidence]
                        parent_alignment = aggregate_quran_alignment(
                            extraction.claims[parent_index], parent_evidence).value
                    retrievals[index] = await service.retrieve(
                        claim, parent_quran_alignment=parent_alignment, parent_claim=parent_claim)
            else:
                retrievals = await asyncio.gather(*[service.retrieve(claim) for claim in extraction.claims])
            evidence_count = sum(item.total_evidence_candidates for item in retrievals)
            await self._finish(response, StepName.RETRIEVE_EVIDENCE,
                f"تم العثور على {evidence_count} سجلًا مرشحًا.",
                {"evidence_candidates": evidence_count})

            validator = self.validation_service or EvidenceValidationService(
                SemanticValidator(self.settings, usage_sink=tracker.record_usage)
                if self.settings.anthropic_api_key else None)
            await self._start(response, StepName.ALIGN_EVIDENCE)
            evidence_by_claim = [[e for provider in result.provider_results for e in provider.evidence]
                                 for result in retrievals]
            await self._finish(response, StepName.ALIGN_EVIDENCE,
                "تم تجهيز الأدلة المرتبطة مباشرة بالمطالبات.",
                {"candidate_count": sum(map(len, evidence_by_claim))})

            await self._start(response, StepName.VALIDATE_EVIDENCE)
            validations = [await asyncio.to_thread(validator.validate, claim, evidence, retrieval)
                           for claim, evidence, retrieval in zip(extraction.claims, evidence_by_claim, retrievals)]
            count = sum(len(item.validations) for item in validations)
            await self._finish(response, StepName.VALIDATE_EVIDENCE,
                f"تم التحقق من {count} عنصرًا.", {"attribute_count": count})

            await self._start(response, StepName.MAKE_DECISION)
            decisions = [decide_claim(ClaimDecisionRequest(validation=validation, claim=claim))
                         for claim, validation in zip(extraction.claims, validations)]
            await self._finish(response, StepName.MAKE_DECISION,
                "تم تطبيق قواعد القرار الحتمية.",
                {"decisions": [item.decision.value for item in decisions]})

            await self._start(response, StepName.BUILD_REPORT)
            reports = [build_verification_report(
                claim, evidence, validation, decision, retrieval, display_number=index)
                for index, (claim, evidence, validation, decision, retrieval) in enumerate(
                    zip(extraction.claims, evidence_by_claim, validations, decisions, retrievals), 1)]
            response.claims = [ClaimVerificationResult(claim=claim, validation=validation, report=report)
                               for claim, validation, report in zip(extraction.claims, validations, reports)]
            response.presentation = build_overall_report(response.claims)
            await self._finish(response, StepName.BUILD_REPORT, "تم إعداد التقرير النهائي.",
                               {"report_count": len(reports)})
            response.status = RequestStatus.COMPLETED
            response.completed_at = datetime.now(timezone.utc)
            provider_counts = Counter()
            for retrieval in retrievals:
                for provider in retrieval.provider_results:
                    provider_counts[provider.provider.value] += len(provider.query_attempts)
            response.cost = tracker.summary(
                [ProviderCallSummary(provider=k, request_count=v) for k, v in sorted(provider_counts.items())],
                round((time.perf_counter() - started) * 1000, 3))
            await self._publish(response)
            logger.info("verification_completed", extra={"request_id": request_id,
                        "processing_time_ms": response.cost.duration_ms, "success": True})
            return response
        except Exception as exc:
            response.status = RequestStatus.FAILED
            response.error = "تعذر إكمال عملية التحقق. يرجى المحاولة مرة أخرى."
            response.completed_at = datetime.now(timezone.utc)
            for step in response.execution:
                if step.status == StepStatus.RUNNING:
                    step.status = StepStatus.FAILED
                    step.completed_at = response.completed_at
                    step.duration_ms = (step.completed_at - step.started_at).total_seconds() * 1000
            response.cost = tracker.summary([], round((time.perf_counter() - started) * 1000, 3))
            await self._publish(response)
            logger.error("verification_failed", extra={"request_id": request_id,
                         "processing_time_ms": response.cost.duration_ms, "success": False,
                         "error_type": type(exc).__name__})
            return response
        finally:
            if http_client:
                await http_client.aclose()

    def _retrieval_service(self, client):
        return RetrievalService(build_provider_adapters(self.settings, client))

    async def _start(self, response, name):
        step = next(item for item in response.execution if item.step == name)
        step.status, step.started_at, step.summary_ar = StepStatus.RUNNING, datetime.now(timezone.utc), "جارٍ التنفيذ..."
        await self._publish(response)

    async def _finish(self, response, name, summary, details):
        step = next(item for item in response.execution if item.step == name)
        step.status, step.completed_at, step.summary_ar, step.details = StepStatus.COMPLETED, datetime.now(timezone.utc), summary, details
        step.duration_ms = round((step.completed_at - step.started_at).total_seconds() * 1000, 3)
        await self._publish(response)

    async def _publish(self, response):
        if self.progress_callback:
            result = self.progress_callback(response.model_copy(deep=True))
            if asyncio.iscoroutine(result):
                await result
