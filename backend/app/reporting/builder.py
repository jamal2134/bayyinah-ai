from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.decision.models import ClaimDecision, ClaimDecisionStatus, DecisionReasonCode
from app.models.claim import AttributeType, Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider
from app.models.validation import AttributeValidationResult, AttributeValidationStatus, EvidenceValidationResponse
from app.models.retrieval import RetrievalResult
from app.reporting.models import (
    AttributeReport, AttributeSourceRole, ClaimNumberMapping, EvidenceRole,
    OverallVerificationReport, ProviderFailureReport, ReportTrace, SourceReport,
    StatusCount, StatusPresentation, TraceableVerificationReport, UnresolvedItem,
)


PROVIDER_LABELS_AR = {
    EvidenceProvider.QURANPEDIA: "الموسوعة القرآنية",
    EvidenceProvider.HADEETHENC: "موسوعة الأحاديث النبوية",
    EvidenceProvider.DORAR: "الدرر السنية",
    EvidenceProvider.DORAR_HADITH: "الدرر السنية — الحديث",
    EvidenceProvider.DORAR_HADITH_EXPLANATION: "الدرر السنية — شرح الحديث",
    EvidenceProvider.DORAR_TAFSEER: "الدرر السنية — التفسير",
    EvidenceProvider.DORAR_FEQHIA: "الدرر السنية — الموسوعة الفقهية",
    EvidenceProvider.DORAR_AQEEDA: "الدرر السنية — الموسوعة العقدية",
    EvidenceProvider.DORAR_HISTORY: "الدرر السنية — التاريخ",
    EvidenceProvider.BAYAN: "بيان",
}
from app.reporting.templates_ar import (
    ATTRIBUTE_MESSAGES, AUTHENTICITY_MISSING_NOTE, EXECUTION_FAILURE_NOTE,
    REASON_EXPLANATIONS, SPECIALIST_NOTE, STATUS_PRESENTATION, STATUS_SUMMARIES,
)


def _value(item: EvidenceCandidate | Mapping[str, Any], name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name)


def _optional_value(item: EvidenceCandidate | Mapping[str, Any], name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)


def build_verification_report(
    claim: Claim,
    evidence_candidates: Sequence[EvidenceCandidate | Mapping[str, Any]],
    validation: EvidenceValidationResponse,
    decision: ClaimDecision,
    retrieval_result: RetrievalResult | None = None,
    display_number: int = 1,
) -> TraceableVerificationReport:
    """Render structured upstream results. It deliberately performs no retrieval or classification."""
    if claim.id != validation.claim_id or claim.id != decision.claim_id:
        raise ValueError("claim, validation, and decision claim IDs must match")

    candidates = {_value(item, "evidence_id"): item for item in evidence_candidates}
    validations = {item.attribute_id: item for item in validation.validations}
    required_ids = [item.id for item in claim.attributes if item.requires_evidence]
    selected = [validations[item_id] for item_id in required_ids if item_id in validations]
    referenced = sorted({eid for item in selected for eid in
                         item.supporting_evidence_ids + item.contradicting_evidence_ids})
    missing_sources = sorted(set(referenced) - set(candidates))
    if missing_sources:
        raise ValueError(f"validated evidence is absent from Phase 3 candidates: {missing_sources}")

    attributes = [_attribute_report(item) for item in selected]
    sources = [_source_report(eid, candidates[eid], selected) for eid in referenced]
    unresolved = [_unresolved(item_id, validations.get(item_id))
                  for item_id in decision.unresolved_attribute_ids]
    warnings = list(validation.warnings)
    if any(item.attribute_type == AttributeType.AUTHENTICITY and
           item.status == AttributeValidationStatus.NOT_FOUND for item in selected):
        warnings.append(AUTHENTICITY_MISSING_NOTE)
    if decision.reason_code == DecisionReasonCode.VALIDATION_EXECUTION_FAILURE:
        warnings.append(EXECUTION_FAILURE_NOTE)
    elif decision.reason_code == DecisionReasonCode.SPECIALIST_REVIEW_REQUIRED:
        warnings.append(SPECIALIST_NOTE)

    label, icon = STATUS_PRESENTATION[decision.decision]
    provider_failures = _provider_failures(retrieval_result)
    report = TraceableVerificationReport(
        report_id=f"report_{claim.id}", claim_id=claim.id, claim_text=claim.original_text,
        decision=decision.decision, reason_code=decision.reason_code,
        summary_ar=STATUS_SUMMARIES[decision.decision],
        reason_explanation_ar=REASON_EXPLANATIONS[decision.reason_code],
        presentation=StatusPresentation(label_ar=label, icon=icon), attributes=attributes,
        sources=sources, unresolved_items=unresolved, warnings=warnings,
        trace=ReportTrace(phase5_decision=decision.decision,
                          phase5_reason_code=decision.reason_code,
                          phase4_validation_ids=[item.attribute_id for item in selected],
                          evidence_ids=referenced, decision_trace=decision.decision_trace),
        technical_details={"claim_id": claim.id,
                           "reason_code": decision.reason_code.value,
                           "validation_methods": {item.attribute_id: item.validation_method for item in selected}},
        display_number=display_number, normalized_claim=claim.normalized_claim,
        domain=claim.domain.value, claim_type=claim.claim_type.value,
        provider_failures=provider_failures,
        final_explanation_ar=REASON_EXPLANATIONS[decision.reason_code],
    )
    _assert_invariants(report, decision, validation, referenced)
    return report


def _attribute_report(item: AttributeValidationResult) -> AttributeReport:
    message = ("النص القرآني المذكور لا يتوافق مع المرجع القرآني المدعى."
               if item.validation_method == "quran_record_alignment"
               and item.status == AttributeValidationStatus.CONTRADICTED
               else ATTRIBUTE_MESSAGES[item.status])
    return AttributeReport(attribute_id=item.attribute_id, attribute_type=item.attribute_type,
                           claimed_value=item.claimed_value, validation_status=item.status,
                           validation_method=item.validation_method,
                           supporting_evidence_ids=sorted(set(item.supporting_evidence_ids)),
                           contradicting_evidence_ids=sorted(set(item.contradicting_evidence_ids)),
                           user_message=message)


def _source_report(eid: str, candidate: EvidenceCandidate | Mapping[str, Any],
                   validations: list[AttributeValidationResult]) -> SourceReport:
    roles = []
    for item in validations:
        if eid in item.supporting_evidence_ids:
            role = (EvidenceRole.PARTIALLY_SUPPORTING
                    if item.status == AttributeValidationStatus.PARTIAL else EvidenceRole.SUPPORTING)
            roles.append(AttributeSourceRole(attribute_id=item.attribute_id, role=role))
        if eid in item.contradicting_evidence_ids:
            roles.append(AttributeSourceRole(attribute_id=item.attribute_id, role=EvidenceRole.CONTRADICTING))
    roles.sort(key=lambda role: (role.attribute_id, role.role.value))
    provider = _value(candidate, "provider")
    provider = EvidenceProvider(provider)
    structured = _optional_value(candidate, "structured_fields") or {}
    metadata = {key: value for key, value in {
        "narrator": _optional_value(candidate, "narrator"),
        "scholar": _optional_value(candidate, "scholar"),
        "judgment": _optional_value(candidate, "judgment"),
        "page": _optional_value(candidate, "page"),
        "fragment_label": _optional_value(candidate, "fragment_label"),
        "surah_id": structured.get("surah_id"), "page_id": structured.get("page_id"),
        "hadith_id": structured.get("hadith_id"),
        "explanation_id": structured.get("explanation_id"),
        "hijri_year": structured.get("hijri_year"),
        "gregorian_year": structured.get("gregorian_year"),
    }.items() if value is not None and value != ""}
    return SourceReport(evidence_id=eid, provider=provider,
                        provider_record_id=_value(candidate, "provider_record_id"),
                        source_url=_value(candidate, "source_url"),
                        title=_optional_value(candidate, "title"),
                        evidence_type=_optional_value(candidate, "evidence_type"),
                        author=_optional_value(candidate, "author"),
                        evidence_text=(_optional_value(candidate, "text") or
                                       _optional_value(candidate, "short_identifying_information")),
                        reference=_optional_value(candidate, "reference"),
                        provider_label_ar=PROVIDER_LABELS_AR.get(provider, provider.value),
                        parent_evidence_id=_optional_value(candidate, "parent_evidence_id"),
                        metadata=metadata,
                        used_for_attributes=sorted({role.attribute_id for role in roles}), roles=roles)


def _provider_failures(retrieval_result: RetrievalResult | None) -> list[ProviderFailureReport]:
    if retrieval_result is None:
        return []
    failures = []
    for result in retrieval_result.provider_results:
        if (result.success or result.error is None
                or result.error.error_type.value == "NO_RESULTS"):
            continue
        provider = result.provider
        failures.append(ProviderFailureReport(
            provider=provider, provider_label_ar=PROVIDER_LABELS_AR.get(provider, provider.value),
            error_type=result.error.error_type.value,
            message_ar=(f"تعذر الوصول إلى {PROVIDER_LABELS_AR.get(provider, provider.value)} "
                        "أثناء عملية التحقق. لا تمثل هذه المشكلة حكمًا على صحة المطالبة."),
            retryable=result.error.retryable,
        ))
    return failures


def build_overall_report(claim_results) -> OverallVerificationReport:
    """Build a deterministic request-level projection from completed claim reports."""
    reports = [item.report for item in claim_results]
    counts = Counter(report.decision for report in reports)
    priority = (
        ClaimDecisionStatus.REQUIRES_SPECIALIST, ClaimDecisionStatus.CONFLICTING,
        ClaimDecisionStatus.INSUFFICIENT_EVIDENCE, ClaimDecisionStatus.PARTIALLY_SUPPORTED,
        ClaimDecisionStatus.SUPPORTED,
    )
    overall = next((status for status in priority if counts[status]), ClaimDecisionStatus.INSUFFICIENT_EVIDENCE)
    return OverallVerificationReport(
        overall_status=overall, status_label_ar=STATUS_PRESENTATION[overall][0],
        total_claims=len(reports),
        status_counts=[StatusCount(status=status, label_ar=STATUS_PRESENTATION[status][0],
                                   count=counts[status]) for status in ClaimDecisionStatus],
        claim_numbers=[ClaimNumberMapping(
            claim_id=report.claim_id, display_number=report.display_number,
            original_claim_text=report.claim_text,
        ) for report in reports],
    )


def _unresolved(attribute_id: str, item: AttributeValidationResult | None) -> UnresolvedItem:
    if item is None:
        return UnresolvedItem(attribute_id=attribute_id,
                              message="تعذر إكمال نتيجة التحقق لهذا العنصر.")
    return UnresolvedItem(attribute_id=attribute_id, attribute_type=item.attribute_type,
                          claimed_value=item.claimed_value, status=item.status,
                          message=ATTRIBUTE_MESSAGES[item.status])


def _assert_invariants(report: TraceableVerificationReport, decision: ClaimDecision,
                       validation: EvidenceValidationResponse, referenced: list[str]) -> None:
    assert report.decision == decision.decision
    assert report.reason_code == decision.reason_code
    assert {source.evidence_id for source in report.sources} == set(referenced)
    upstream = {eid for item in validation.validations
                for eid in item.supporting_evidence_ids + item.contradicting_evidence_ids}
    assert set(referenced) <= upstream
    original = {item.attribute_id: item.status for item in validation.validations}
    assert all(original[item.attribute_id] == item.validation_status for item in report.attributes)
