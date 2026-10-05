from app.decision.models import (
    ClaimDecision, ClaimDecisionRequest, ClaimDecisionStatus, DecisionReasonCode, DecisionRuleTrace,
)
from app.models.validation import AttributeValidationStatus, ValidationExecutionStatus


STATUS_KEYS = tuple(status.value for status in AttributeValidationStatus)


def decide_claim(request: ClaimDecisionRequest) -> ClaimDecision:
    """Aggregate Phase 4 classifications. This function performs no I/O and reads no free text."""
    validation = request.validation
    by_id = {item.attribute_id: item for item in validation.validations}
    if request.claim:
        required_ids = sorted(item.id for item in request.claim.attributes if item.requires_evidence)
    else:
        required_ids = sorted(by_id)
    required = [by_id[item_id] for item_id in required_ids if item_id in by_id]
    missing_ids = sorted(set(required_ids) - set(by_id))
    failures = [item for item in validation.execution_failures
                if not required_ids or item.attribute_id in required_ids]
    summary = {key: 0 for key in STATUS_KEYS}
    for item in required:
        summary[item.status.value] += 1
    support_ids = sorted({evidence_id for item in required for evidence_id in item.supporting_evidence_ids})
    contradict_ids = sorted({evidence_id for item in required for evidence_id in item.contradicting_evidence_ids})
    unresolved = sorted(set(missing_ids) | {
        item.attribute_id for item in required
        if item.status in {AttributeValidationStatus.NOT_FOUND, AttributeValidationStatus.UNCERTAIN}
    } | {item.attribute_id for item in failures})
    traces: list[DecisionRuleTrace] = []

    def check(rule_id, priority, matched, reason):
        traces.append(DecisionRuleTrace(rule_id=rule_id, priority=priority, matched=matched, reason=reason))
        return matched

    specialist = request.specialist_review_required
    if check("P5_SPECIALIST_MARKER", 1, specialist, "Upstream explicitly requires specialist review."):
        return _result(validation.claim_id, ClaimDecisionStatus.REQUIRES_SPECIALIST,
                       DecisionReasonCode.SPECIALIST_REVIEW_REQUIRED,
                       "A structured upstream marker requires specialist review.", summary,
                       support_ids, contradict_ids, unresolved, traces)
    execution_failed = bool(failures) or validation.validation_status == ValidationExecutionStatus.ERROR
    if check("P5_VALIDATION_FAILURE", 1, execution_failed,
             "A required Phase 4 validation did not execute successfully."):
        return _result(validation.claim_id, ClaimDecisionStatus.REQUIRES_SPECIALIST,
                       DecisionReasonCode.VALIDATION_EXECUTION_FAILURE,
                       "A required validation failed to execute, so an automated evidence decision is unsafe.",
                       summary, support_ids, contradict_ids, unresolved, traces)

    explicit_conflict = any(item.supporting_evidence_ids and item.contradicting_evidence_ids for item in required)
    if check("P5_CONFLICT_WITHIN_ATTRIBUTE", 2, explicit_conflict,
             "A required attribute has both supporting and contradicting validated evidence."):
        return _result(validation.claim_id, ClaimDecisionStatus.CONFLICTING,
                       DecisionReasonCode.EVIDENCE_CONFLICT,
                       "Validated evidence both supports and contradicts a required attribute.",
                       summary, support_ids, contradict_ids, unresolved, traces)

    contradicted = any(item.status == AttributeValidationStatus.CONTRADICTED for item in required)
    positive = any(item.status in {AttributeValidationStatus.SUPPORTED, AttributeValidationStatus.PARTIAL}
                   for item in required)
    if check("P5_CONFLICT_CONTRADICTED", 3, contradicted,
             "At least one required attribute is explicitly contradicted by validated evidence."):
        code = DecisionReasonCode.EVIDENCE_CONFLICT if positive else DecisionReasonCode.CLAIM_CONTRADICTED_BY_EVIDENCE
        reason = ("Some required components are supported while another is contradicted by evidence."
                  if positive else "Validated evidence contradicts the claim's required attribute(s).")
        return _result(validation.claim_id, ClaimDecisionStatus.CONFLICTING, code, reason,
                       summary, support_ids, contradict_ids, unresolved, traces)

    missing = bool(missing_ids) or not required_ids or any(
        item.status == AttributeValidationStatus.NOT_FOUND for item in required)
    if check("P5_REQUIRED_EVIDENCE_MISSING", 4, missing,
             "One or more required attributes have no validated evidence result."):
        return _result(validation.claim_id, ClaimDecisionStatus.INSUFFICIENT_EVIDENCE,
                       DecisionReasonCode.REQUIRED_EVIDENCE_MISSING,
                       "Required evidence is missing for one or more claim attributes.",
                       summary, support_ids, contradict_ids, unresolved, traces)
    ambiguous = any(item.status == AttributeValidationStatus.UNCERTAIN for item in required)
    if check("P5_AMBIGUOUS_EVIDENCE", 4, ambiguous,
             "One or more required attributes remain ambiguous without explicit evidence conflict."):
        return _result(validation.claim_id, ClaimDecisionStatus.INSUFFICIENT_EVIDENCE,
                       DecisionReasonCode.AMBIGUOUS_EVIDENCE,
                       "Validated evidence is insufficiently clear for one or more required attributes.",
                       summary, support_ids, contradict_ids, unresolved, traces)
    partial = any(item.status == AttributeValidationStatus.PARTIAL for item in required)
    if check("P5_PARTIAL_EVIDENCE", 5, partial,
             "At least one required attribute is only partially supported."):
        return _result(validation.claim_id, ClaimDecisionStatus.PARTIALLY_SUPPORTED,
                       DecisionReasonCode.PARTIAL_EVIDENCE,
                       "Evidence positively establishes only part of the required claim attributes.",
                       summary, support_ids, contradict_ids, unresolved, traces)
    all_supported = bool(required) and all(
        item.status == AttributeValidationStatus.SUPPORTED for item in required)
    check("P5_SUPPORTED_ALL_REQUIRED", 6, all_supported,
          f"All {len(required)} required attributes are supported.")
    if all_supported:
        return _result(validation.claim_id, ClaimDecisionStatus.SUPPORTED,
                       DecisionReasonCode.ALL_REQUIRED_ATTRIBUTES_SUPPORTED,
                       "All required claim attributes are supported by validated evidence.",
                       summary, support_ids, contradict_ids, unresolved, traces)
    return _result(validation.claim_id, ClaimDecisionStatus.INSUFFICIENT_EVIDENCE,
                   DecisionReasonCode.REQUIRED_EVIDENCE_MISSING,
                   "No complete required validation set was available.",
                   summary, support_ids, contradict_ids, unresolved, traces)


def _result(claim_id, decision, code, reason, summary, support, contradict, unresolved, trace):
    return ClaimDecision(claim_id=claim_id, decision=decision, reason_code=code, reason=reason,
                         attribute_summary=summary, supporting_evidence_ids=support,
                         contradicting_evidence_ids=contradict,
                         unresolved_attribute_ids=unresolved, decision_trace=trace)
