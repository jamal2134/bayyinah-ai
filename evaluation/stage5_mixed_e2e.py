"""Stage 5 mixed-domain E2E evaluation through the normal application orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.application.models import RequestStatus  # noqa: E402
from app.application.orchestrator import VerificationOrchestrator  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.models.claim import Claim, ExtractionResult  # noqa: E402
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType  # noqa: E402
from app.models.retrieval import (  # noqa: E402
    ProviderError, ProviderErrorType, ProviderResult, QueryAttempt, RetrievalStatus,
)
from app.models.validation import AttributeValidationStatus, SemanticValidationOutput  # noqa: E402
from app.retrieval.service import RetrievalService  # noqa: E402
from app.validation.evidence_matcher import (  # noqa: E402
    CONTEXTUAL_EVIDENCE_TYPES, TYPE_COMPATIBILITY, CandidateAlignment,
    evidence_context_alignment,
)
from app.validation.service import EvidenceValidationService  # noqa: E402


MIXED_VALID_AR = (
    "قال الله تعالى: الله لا إله إلا هو الحي القيوم، وهي الآية 255 من سورة البقرة، "
    "ومعناها أن الله كامل الحياة والقيومية. وقال النبي ﷺ: إنما الأعمال بالنيات، رواه عمر بن الخطاب، "
    "ومعناه أن صلاح العمل مرتبط بالنية. وصلاة الوتر سنة مؤكدة. والله متصف بالعلم. "
    "وكان صلح الحديبية سنة 6 هـ."
)
MIXED_ADVERSARIAL_AR = (
    "آية الكرسي من سورة آل عمران آية 7، ومعناها نفي القيومية. وحديث إنما الأعمال بالنيات رواه أبو هريرة، "
    "ومعناه أن النية لا أثر لها. والشافعية يقولون إن الوتر فرض. ونسب نفي العلم إلى أهل السنة. "
    "وكان صلح الحديبية سنة 9 هـ."
)
MIXED_PARTIAL_AR = (
    "تفسير آية غير محددة، وقول فقهي منسوب إلى عالم غير مذكور، ومكان حادثة تاريخية لم يرد في المصدر."
)


def _claim(identifier, text, claim_type, domain, attributes, *, parent=None,
           relationship=None, context=None):
    data = {
        "id": identifier, "original_text": text, "normalized_claim": text,
        "claim_type": claim_type, "domain": domain,
        "search_queries": [f"{text} مصدر"], "attributes": attributes,
        "requires_evidence": True, "reason": "Stage 5 controlled E2E fixture.",
    }
    if parent:
        data.update(parent_claim_id=parent, relationship=relationship)
    if context:
        data["subject_context"] = context
    return Claim.model_validate(data)


QURAN_TEXT = "الله لا إله إلا هو الحي القيوم"
HADITH_TEXT = "إنما الأعمال بالنيات"


def _valid_claims():
    return [
        _claim("claim_001", "الله لا إله إلا هو الحي القيوم من البقرة 255", "QURAN_RECORD", "QURAN", [
            {"type": "QURAN_TEXT", "value": QURAN_TEXT}, {"type": "SURAH", "value": "2"},
            {"type": "AYAH_NUMBER", "value": "255"},
        ]),
        _claim("claim_002", "تفسير آية الكرسي أن الله كامل الحياة والقيومية", "QURAN_INTERPRETATION", "QURAN", [
            {"type": "INTERPRETATION", "value": "الله كامل الحياة والقيومية"},
        ], parent="claim_001", relationship="INTERPRETS",
            context={"type": "QURAN", "surah": "2", "ayah_number": "255"}),
        _claim("claim_003", "حديث إنما الأعمال بالنيات رواه عمر بن الخطاب", "HADITH_RECORD", "HADITH", [
            {"type": "HADITH_TEXT", "value": HADITH_TEXT}, {"type": "NARRATOR", "value": "عمر بن الخطاب"},
        ]),
        _claim("claim_004", "شرح حديث إنما الأعمال بالنيات أن صلاح العمل مرتبط بالنية", "HADITH_INTERPRETATION", "HADITH", [
            {"type": "INTERPRETATION", "value": "صلاح العمل مرتبط بالنية"},
        ], parent="claim_003", relationship="EXPLAINS", context={"type": "HADITH", "text": HADITH_TEXT}),
        _claim("claim_005", "صلاة الوتر سنة مؤكدة", "FIQH_RULING", "FIQH", [
            {"type": "RULING", "value": "سنة مؤكدة"},
        ]),
        _claim("claim_006", "الله متصف بالعلم", "AQEEDAH", "AQEEDAH", [
            {"type": "OTHER", "value": "الله متصف بالعلم"},
        ]),
        _claim("claim_007", "صلح الحديبية سنة 6 هـ", "ISLAMIC_HISTORY", "HISTORY", [
            {"type": "DATE", "value": "6 هـ"},
        ]),
    ]


def _adversarial_claims():
    claims = _valid_claims()
    replacements = {
        "claim_001": _claim("claim_001", "آية الكرسي من آل عمران 7", "QURAN_RECORD", "QURAN", [
            {"type": "QURAN_TEXT", "value": QURAN_TEXT}, {"type": "SURAH", "value": "3"},
            {"type": "AYAH_NUMBER", "value": "7"},
        ]),
        "claim_002": _claim("claim_002", "تفسير آية الكرسي ينفي القيومية", "QURAN_INTERPRETATION", "QURAN", [
            {"type": "INTERPRETATION", "value": "الآية تنفي القيومية"},
        ], parent="claim_001", relationship="INTERPRETS", context={"type": "QURAN", "surah": "3", "ayah_number": "7"}),
        "claim_003": _claim("claim_003", "حديث إنما الأعمال بالنيات رواه أبو هريرة", "HADITH_RECORD", "HADITH", [
            {"type": "HADITH_TEXT", "value": HADITH_TEXT}, {"type": "NARRATOR", "value": "أبو هريرة"},
        ]),
        "claim_004": _claim("claim_004", "شرح حديث إنما الأعمال بالنيات أن النية لا أثر لها", "HADITH_INTERPRETATION", "HADITH", [
            {"type": "INTERPRETATION", "value": "النية لا أثر لها"},
        ], parent="claim_003", relationship="EXPLAINS", context={"type": "HADITH", "text": HADITH_TEXT}),
        "claim_005": _claim("claim_005", "الشافعية يقولون الوتر فرض", "FIQH_RULING", "FIQH", [
            {"type": "RULING", "value": "الوتر فرض", "asserted_by": "الشافعية"},
        ]),
        "claim_006": _claim("claim_006", "أهل السنة ينفون علم الله", "AQEEDAH", "AQEEDAH", [
            {"type": "OTHER", "value": "نفي علم الله", "asserted_by": "أهل السنة"},
        ]),
        "claim_007": _claim("claim_007", "صلح الحديبية سنة 9 هـ", "ISLAMIC_HISTORY", "HISTORY", [
            {"type": "DATE", "value": "9 هـ"},
        ]),
    }
    return [replacements.get(item.id, item) for item in claims]


def _partial_claims():
    return [
        _claim("claim_001", "تفسير آية غير محددة", "QURAN_TAFSIR", "QURAN", [
            {"type": "INTERPRETATION", "value": "معنى غير محدد"},
        ]),
        _claim("claim_002", "قول الوتر منسوب إلى عالم غير مذكور", "FIQH_RULING", "FIQH", [
            {"type": "RULING", "value": "الوتر مستحب", "asserted_by": "العالم المجهول"},
        ]),
        _claim("claim_003", "مكان صلح الحديبية داخل مكة", "ISLAMIC_HISTORY", "HISTORY", [
            {"type": "LOCATION", "value": "داخل مكة"},
        ]),
    ]


CASE_CLAIMS = {
    "mixed_valid": _valid_claims,
    "mixed_adversarial": _adversarial_claims,
    "partial_insufficient": _partial_claims,
}
CASE_INPUTS = {
    "mixed_valid": MIXED_VALID_AR,
    "mixed_adversarial": MIXED_ADVERSARIAL_AR,
    "partial_insufficient": MIXED_PARTIAL_AR,
}


class FixtureExtractor:
    def __init__(self, case_id):
        self.case_id = case_id

    def extract(self, text):
        claims = CASE_CLAIMS[self.case_id]()
        return ExtractionResult(input_language="ar", claim_count=len(claims), claims=claims)


def _candidate(claim_id, provider, evidence_type, evidence_id, text, **kwargs):
    return EvidenceCandidate(
        evidence_id=evidence_id, claim_id=claim_id, provider=provider,
        evidence_type=evidence_type, text=text, retrieved_at=datetime.now(timezone.utc),
        **kwargs,
    )


def fixture_evidence(case_id):
    adversarial = case_id == "mixed_adversarial"
    common = {
        "claim_001": {
            EvidenceProvider.QURANPEDIA: [_candidate(
                "claim_001", EvidenceProvider.QURANPEDIA, EvidenceType.QURAN_AYAH, "quran:2:255", QURAN_TEXT,
                provider_record_id="2:255", source_url="https://fixture.local/quran/2/255", reference="2:255",
                raw_metadata={"surah": 2, "ayah_number": 255},
            )],
        },
        "claim_002": {
            EvidenceProvider.DORAR_TAFSEER: [_candidate(
                "claim_002", EvidenceProvider.DORAR_TAFSEER, EvidenceType.TAFSEER_SECTION, "tafseer:2:255:1",
                "تثبت الآية كمال حياة الله وقيوميته", title="تفسير آية الكرسي",
                provider_record_id="taf-255", source_url="https://fixture.local/tafseer/255",
                fragment_id="section-1", fragment_label="المعنى الإجمالي",
                structured_fields={"surah_id": 2, "page_id": 255},
                raw_metadata={"fixture_semantic_status": "CONTRADICTED" if adversarial else "SUPPORTED"},
            )],
        },
        "claim_003": {
            EvidenceProvider.HADEETHENC: [_candidate(
                "claim_003", EvidenceProvider.HADEETHENC, EvidenceType.HADITH, "hadeethenc:1", HADITH_TEXT,
                narrator="عمر بن الخطاب", provider_record_id="1", source_url="https://fixture.local/hadith/1",
            )],
            EvidenceProvider.DORAR_HADITH: [_candidate(
                "claim_003", EvidenceProvider.DORAR_HADITH, EvidenceType.HADITH_JUDGMENT, "dorar-hadith:1", HADITH_TEXT,
                narrator="عمر بن الخطاب", provider_record_id="1", source_url="https://fixture.local/dorar/h/1",
                structured_fields={"hadith_id": "1", "explanation_available": True, "explanation_id": "exp-1"},
            )],
        },
        "claim_004": {
            EvidenceProvider.DORAR_HADITH: [_candidate(
                "claim_004", EvidenceProvider.DORAR_HADITH, EvidenceType.HADITH_JUDGMENT, "dorar-hadith:child-1", HADITH_TEXT,
                provider_record_id="1", source_url="https://fixture.local/dorar/h/1",
                structured_fields={"hadith_id": "1", "explanation_available": True, "explanation_id": "exp-1"},
            )],
        },
        "claim_005": {
            EvidenceProvider.DORAR_FEQHIA: [_candidate(
                "claim_005", EvidenceProvider.DORAR_FEQHIA, EvidenceType.FIQH_CONTENT, "fiqh:1",
                "صلاة الوتر سنة مؤكدة وليست فرضا", title="حكم صلاة الوتر",
                provider_record_id="fiqh-1", source_url="https://fixture.local/fiqh/1",
                raw_metadata={"fixture_semantic_status": "UNCERTAIN" if adversarial else "SUPPORTED"},
            )],
        },
        "claim_006": {
            EvidenceProvider.DORAR_AQEEDA: [_candidate(
                "claim_006", EvidenceProvider.DORAR_AQEEDA, EvidenceType.AQEEDA_CONTENT, "aqeeda:1",
                "أهل السنة يثبتون صفة العلم لله", title=("أهل السنة ينفون علم الله" if adversarial
                                                          else "الله متصف بالعلم"),
                provider_record_id="aq-1", source_url="https://fixture.local/aqeeda/1",
                raw_metadata={"fixture_semantic_status": "CONTRADICTED" if adversarial else "SUPPORTED"},
            )],
        },
        "claim_007": {
            EvidenceProvider.DORAR_HISTORY: [_candidate(
                "claim_007", EvidenceProvider.DORAR_HISTORY, EvidenceType.HISTORY_EVENT, "history:1",
                "تفاصيل صلح الحديبية", title="صلح الحديبية", provider_record_id="hist-1",
                source_url="https://fixture.local/history/1",
                structured_fields={"hijri_year": 6, "gregorian_year": 628},
            )],
        },
    }
    if case_id == "partial_insufficient":
        return {
            "claim_001": {EvidenceProvider.DORAR_TAFSEER: [_candidate(
                "claim_001", EvidenceProvider.DORAR_TAFSEER, EvidenceType.TAFSEER_SECTION, "tafseer:unknown",
                "تفسير بلا مرجع كاف", structured_fields={},
            )]},
            "claim_002": {EvidenceProvider.DORAR_FEQHIA: [_candidate(
                "claim_002", EvidenceProvider.DORAR_FEQHIA, EvidenceType.FIQH_CONTENT, "fiqh:generic",
                "الوتر مستحب", title="حكم الوتر",
            )]},
            "claim_003": {EvidenceProvider.DORAR_HISTORY: [_candidate(
                "claim_003", EvidenceProvider.DORAR_HISTORY, EvidenceType.HISTORY_EVENT, "history:location-missing",
                "تفاصيل صلح الحديبية دون ذكر المكان", title="صلح الحديبية",
                raw_metadata={"fixture_semantic_status": "NOT_FOUND"},
            )]},
        }
    return common


class FixtureProvider:
    max_attempts = 1
    max_results = 20

    def __init__(self, provider, records, *, fail=False):
        self.provider, self.records, self.fail = provider, records, fail
        self.calls = []

    async def retrieve(self, claim):
        self.calls.append(claim.id)
        attempt = QueryAttempt(query=claim.search_queries[0], attempt=1, duration_ms=0,
                               result_count=0 if self.fail else len(self.records.get(claim.id, [])),
                               success=not self.fail, endpoint="fixture://controlled")
        if self.fail:
            return ProviderResult(provider=self.provider, success=False, query_attempts=[attempt],
                                  error=ProviderError(provider=self.provider,
                                      error_type=ProviderErrorType.TIMEOUT,
                                      message="Controlled specialist timeout", retryable=True))
        return ProviderResult(provider=self.provider, success=True, query_attempts=[attempt],
                              evidence=[item.model_copy(deep=True) for item in self.records.get(claim.id, [])])


class FixtureExplanationProvider(FixtureProvider):
    def __init__(self, case_id):
        super().__init__(EvidenceProvider.DORAR_HADITH_EXPLANATION, {})
        self.case_id = case_id
        self.authorizations = []

    async def retrieve_by_id(self, claim_id, explanation_id, hadith_id="", parent_evidence_id=None):
        self.calls.append(claim_id)
        self.authorizations.append((explanation_id, hadith_id, parent_evidence_id))
        evidence = _candidate(
            claim_id, self.provider, EvidenceType.HADITH_EXPLANATION, f"hadith-explanation:{explanation_id}",
            "صلاح العمل وقبوله مرتبط بالنية", provider_record_id=explanation_id,
            source_url=f"https://fixture.local/hadith/explanation/{explanation_id}",
            parent_evidence_id=parent_evidence_id,
            structured_fields={"hadith_id": hadith_id, "explanation_id": explanation_id,
                               "hadith_text": HADITH_TEXT},
            raw_metadata={"fixture_semantic_status": ("CONTRADICTED"
                          if self.case_id == "mixed_adversarial" else "SUPPORTED")},
        )
        return ProviderResult(provider=self.provider, success=True, evidence=[evidence])


class RecordingRetrievalService(RetrievalService):
    def __init__(self, adapters):
        super().__init__(adapters)
        self.results = {}

    async def retrieve(self, claim, parent_quran_alignment=None, parent_claim=None):
        result = await super().retrieve(claim, parent_quran_alignment, parent_claim)
        self.results[claim.id] = result.model_copy(deep=True)
        return result


class FixtureSemanticValidator:
    def validate(self, attribute, candidates):
        statuses = [item.raw_metadata.get("fixture_semantic_status") for item in candidates]
        status = next((item for item in statuses if item), "NOT_FOUND")
        support = [item.evidence_id for item in candidates
                   if status in {"SUPPORTED", "PARTIAL"}]
        contradict = [item.evidence_id for item in candidates if status == "CONTRADICTED"]
        return SemanticValidationOutput(
            status=AttributeValidationStatus(status), supporting_evidence_ids=support,
            contradicting_evidence_ids=contradict,
            rationale="Controlled relationship derived only from supplied fixture evidence.", confidence=1,
        )


def _adapters(case_id, *, failed_provider=None):
    by_claim = fixture_evidence(case_id)
    providers = list(EvidenceProvider)
    adapters = {}
    for provider in providers:
        if provider in {EvidenceProvider.DORAR, EvidenceProvider.BAYAN}:
            continue
        records = {claim_id: mapping.get(provider, []) for claim_id, mapping in by_claim.items()}
        adapters[provider] = FixtureProvider(provider, records, fail=provider == failed_provider)
    explanation = FixtureExplanationProvider(case_id)
    adapters[EvidenceProvider.DORAR_HADITH_EXPLANATION] = explanation
    return adapters, explanation


def _routing_expected(domain, claim_type):
    if domain == "QURAN":
        return {"DORAR_TAFSEER", "QURANPEDIA"} if claim_type in {"QURAN_TAFSIR", "QURAN_INTERPRETATION"} else {"QURANPEDIA"}
    return {
        "HADITH": {"HADEETHENC", "DORAR_HADITH"}, "FIQH": {"DORAR_FEQHIA"},
        "AQEEDAH": {"DORAR_AQEEDA"}, "HISTORY": {"DORAR_HISTORY"},
    }.get(domain, set())


def _serialize_case(case_id, response, retrieval, explanation, input_text=None):
    claims, routing, retrieval_rows, dependencies, validations, decisions = [], [], [], [], [], []
    candidate_by_id = {}
    claim_by_id = {item.claim.id: item.claim for item in response.claims}
    for result in response.claims:
        item = result.claim
        claims.append(item.model_dump(mode="json"))
        retrieved = retrieval.results[item.id]
        routing.append({
            "claim_id": item.id,
            "expected_provider_family": sorted(_routing_expected(item.domain.value, item.claim_type.value)),
            "planned_sources": [source.model_dump(mode="json") for source in retrieved.retrieval_plan.sources],
            "tasks": [task.model_dump(mode="json") for task in retrieved.retrieval_plan.tasks],
        })
        providers = []
        for provider_result in retrieved.provider_results:
            candidates = []
            for evidence in provider_result.evidence:
                candidate_by_id[evidence.evidence_id] = evidence
                candidates.append({key: value for key, value in evidence.model_dump(mode="json").items()
                                   if key not in {"raw_metadata"} and key in {
                                       "evidence_id", "provider", "evidence_type", "provider_record_id",
                                       "target_attribute_ids", "source_url", "parent_evidence_id", "fragment_id",
                                       "fragment_label", "title", "text", "structured_fields",
                                   }})
            providers.append({
                "provider": provider_result.provider.value, "success": provider_result.success,
                "query_attempts": [attempt.model_dump(mode="json") for attempt in provider_result.query_attempts],
                "candidate_count": len(candidates), "candidates": candidates,
                "error": provider_result.error.model_dump(mode="json") if provider_result.error else None,
            })
        retrieval_rows.append({"claim_id": item.id, "status": retrieved.retrieval_status.value,
                               "providers": providers})
        dependencies.extend({"claim_id": item.id, **trace.model_dump(mode="json")}
                            for trace in retrieved.dependency_trace)
        validations.append({"claim_id": item.id, **result.validation.model_dump(mode="json")})
        decisions.append({
            "claim_id": item.id, "phase4_statuses": [row.status.value for row in result.validation.validations],
            "final_status": result.report.decision.value, "reason_code": result.report.reason_code.value,
            "evidence_ids": result.report.trace.evidence_ids,
        })

    relationship_decisions = []
    unsupported = 0
    for row in validations:
        alignment = {(item["attribute_id"], item["evidence_id"]): item["alignment"]
                     for item in row["candidate_alignment"] if item.get("attribute_id")}
        for attribute in row["validations"]:
            for role, key in (("SUPPORT", "supporting_evidence_ids"),
                              ("CONTRADICTION", "contradicting_evidence_ids")):
                for evidence_id in attribute[key]:
                    evidence = candidate_by_id.get(evidence_id)
                    claim = claim_by_id[row["claim_id"]]
                    claim_attribute = next(item for item in claim.attributes
                                           if item.id == attribute["attribute_id"])
                    compatible = (evidence is not None and evidence.evidence_type in
                                  TYPE_COMPATIBILITY.get(claim_attribute.type, set()))
                    if evidence is not None and evidence.evidence_type in CONTEXTUAL_EVIDENCE_TYPES:
                        contextual = evidence_context_alignment(claim, claim_attribute, evidence)[0]
                        aligned = contextual == CandidateAlignment.ALIGNED
                    else:
                        aligned = alignment.get((attribute["attribute_id"], evidence_id), "ALIGNED") == "ALIGNED"
                    valid = compatible and aligned
                    unsupported += not valid
                    relationship_decisions.append({"claim_id": row["claim_id"],
                        "attribute_id": attribute["attribute_id"], "evidence_id": evidence_id,
                        "role": role, "compatible_and_aligned": valid})
    traceable = sum(bool(item["evidence_id"]) for item in relationship_decisions)
    routable = len(routing)
    precise = sum(set(source["provider"] for source in item["planned_sources"])
                  <= set(item["expected_provider_family"]) for item in routing)
    accepted_parents = {trace["parent_evidence_id"] for trace in dependencies
                        if trace["status"] == "ACCEPTED"}
    unauthorized = sum(not parent_id or parent_id not in accepted_parents
                       for _, _, parent_id in explanation.authorizations)
    metrics = {
        "unsupported_inference_count": unsupported,
        "total_support_or_contradiction_decisions": len(relationship_decisions),
        "unsupported_inference_rate": unsupported / len(relationship_decisions) if relationship_decisions else 0,
        "validated_decisions_with_evidence_ids": traceable,
        "total_evidence_based_decisions": len(relationship_decisions),
        "evidence_traceability": traceable / len(relationship_decisions) if relationship_decisions else 1,
        "claims_with_only_expected_provider_family": precise, "total_routable_claims": routable,
        "routing_precision": precise / routable if routable else 1,
        "unauthorized_explanation_calls": unauthorized,
    }
    return {"case_id": case_id, "input_text": input_text if input_text is not None else CASE_INPUTS[case_id], "claims": claims,
            "routing": routing, "retrieval": retrieval_rows, "dependencies": dependencies,
            "validations": validations, "decisions": decisions, "relationship_audit": relationship_decisions,
            "metrics": metrics, "explanation_calls": explanation.authorizations,
            "cost": response.cost.model_dump(mode="json") if response.cost else None,
            "failures": [failure for validation in validations for failure in validation["execution_failures"]]}


async def run_offline_case(case_id, *, failed_provider=None):
    adapters, explanation = _adapters(case_id, failed_provider=failed_provider)
    retrieval = RecordingRetrievalService(adapters)
    orchestrator = VerificationOrchestrator(
        Settings(_env_file=None), extractor=FixtureExtractor(case_id), retrieval_service=retrieval,
        validation_service=EvidenceValidationService(FixtureSemanticValidator()),
    )
    response = await orchestrator.verify_text(CASE_INPUTS[case_id], f"stage5_{case_id}")
    if response.status != RequestStatus.COMPLETED:
        raise RuntimeError(f"Offline orchestration failed: {response.error}")
    return _serialize_case(case_id, response, retrieval, explanation)


def aggregate_metrics(cases):
    relationships = sum(item["metrics"]["total_support_or_contradiction_decisions"] for item in cases)
    unsupported = sum(item["metrics"]["unsupported_inference_count"] for item in cases)
    evidence_based = sum(item["metrics"]["total_evidence_based_decisions"] for item in cases)
    traced = sum(item["metrics"]["validated_decisions_with_evidence_ids"] for item in cases)
    routable = sum(item["metrics"]["total_routable_claims"] for item in cases)
    precise = sum(item["metrics"]["claims_with_only_expected_provider_family"] for item in cases)
    return {
        "unsupported_inference_count": unsupported,
        "total_support_or_contradiction_decisions": relationships,
        "unsupported_inference_rate": unsupported / relationships if relationships else 0,
        "validated_decisions_with_evidence_ids": traced,
        "total_evidence_based_decisions": evidence_based,
        "evidence_traceability": traced / evidence_based if evidence_based else 1,
        "routing_precision": precise / routable if routable else 1,
        "unauthorized_explanation_calls": sum(item["metrics"]["unauthorized_explanation_calls"] for item in cases),
    }


def markdown_summary(report):
    lines = ["# Stage 5 Mixed E2E Evaluation", "", "INPUT → CLAIMS → ROUTES → EVIDENCE → VALIDATION → FINAL DECISIONS", ""]
    for case in report["cases"]:
        lines.extend([f"## {case['case_id']}", "", "| Claim | Providers | Evidence used | Attribute results | Final status |",
                      "|---|---|---|---|---|"])
        routes = {item["claim_id"]: ", ".join(source["provider"] for source in item["planned_sources"])
                  for item in case["routing"]}
        for decision in case["decisions"]:
            claim = next(item for item in case["claims"] if item["id"] == decision["claim_id"])
            lines.append(f"| {claim['normalized_claim']} | {routes[claim['id']]} | "
                         f"{', '.join(decision['evidence_ids']) or '—'} | "
                         f"{', '.join(decision['phase4_statuses'])} | {decision['final_status']} |")
        lines.append("")
    lines.extend(["## Metrics", "", *[f"- {key}: {value}" for key, value in report["metrics"].items()]])
    return "\n".join(lines) + "\n"


async def run_offline():
    cases = [await run_offline_case(case_id) for case_id in CASE_CLAIMS]
    failure = await run_offline_case("mixed_valid", failed_provider=EvidenceProvider.DORAR_FEQHIA)
    failure["case_id"] = "provider_failure_isolation"
    cases.append(failure)
    # Reordered fixture execution proves stable Phase 5 output for unchanged relationships.
    repeated = await run_offline_case("mixed_valid")
    deterministic = cases[0]["decisions"] == repeated["decisions"]
    report = {"evaluation_version": "stage5", "mode": "offline", "generated_at": datetime.now(timezone.utc).isoformat(),
              "cases": cases, "metrics": aggregate_metrics(cases),
              "phase5_deterministic_repeat": deterministic, "failures": []}
    return report


async def run_live():
    settings = Settings()
    if not settings.anthropic_api_key:
        return {"evaluation_version": "stage5", "mode": "live", "status": "skipped",
                "reason": "ANTHROPIC_API_KEY is not configured; live results were not fabricated."}
    orchestrator = VerificationOrchestrator(settings)
    cases = []
    for case_id, text in CASE_INPUTS.items():
        response = await orchestrator.verify_text(text, f"stage5_live_{case_id}")
        cases.append(response.model_dump(mode="json"))
    completed = sum(item["status"] == "COMPLETED" for item in cases)
    status = "completed" if completed == len(cases) else "partial" if completed else "failed"
    costs = [item.get("cost") or {} for item in cases]
    return {
        "evaluation_version": "stage5", "mode": "live", "status": status,
        "reason": (None if status == "completed" else
                   "One or more real orchestration requests failed; no missing live results were fabricated."),
        "cases": cases,
        "cost": {
            "duration_ms": sum(item.get("duration_ms", 0) for item in costs),
            "llm_calls_with_recorded_usage": sum(item.get("llm_calls", 0) for item in costs),
            "provider_calls": sum(item.get("provider_calls", 0) for item in costs),
            "estimated_cost_usd": sum(float(item.get("estimated_cost_usd") or 0) for item in costs),
            "estimated_cost_sar": sum(float(item.get("estimated_cost_sar") or 0) for item in costs),
            "note": "Failed API attempts without usage records are not assigned an invented cost.",
        },
        "failures": [{"request_id": item["request_id"], "status": item["status"],
                      "error": item.get("error")} for item in cases if item["status"] != "COMPLETED"],
    }


async def main(mode):
    report = await (run_live() if mode == "live" else run_offline())
    suffix = "live" if mode == "live" else "offline"
    json_path = ROOT / "evaluation" / f"stage5_mixed_e2e_{suffix}_results.json"
    md_path = ROOT / "evaluation" / f"stage5_mixed_e2e_{suffix}_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown_summary(report) if report.get("cases") and mode == "offline"
                       else f"# Stage 5 Live E2E\n\nStatus: {report.get('status')}\n\n{report.get('reason', '')}\n", encoding="utf-8")
    print(json.dumps(report.get("metrics", {"status": report.get("status"), "reason": report.get("reason")}),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    asyncio.run(main(parser.parse_args().mode))
