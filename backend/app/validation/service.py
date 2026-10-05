from app.models.claim import AttributeType, ClaimAttribute, ClaimType, Domain
from app.models.validation import (
    AttributeValidationResult, AttributeValidationStatus, EvidenceValidationResponse,
    ValidationExecutionStatus, ValidationTrace,
    ValidationExecutionFailure, CandidateAlignmentTrace,
)
from app.models.retrieval import RetrievalStatus
from app.validation.deterministic import CandidateDecision, grade_category, validate_candidate
from app.validation.normalization import normalize
from app.validation.evidence_matcher import (
    CONTEXTUAL_EVIDENCE_TYPES, CandidateAlignment, DEPENDENT_RECORD_ATTRIBUTES,
    QuranRecordAlignment, aggregate_quran_alignment, evidence_context_alignment,
    hadith_record_alignment, quran_record_alignment, relevant_evidence,
)
from app.validation.semantic import SemanticValidationError, SemanticValidator


class EvidenceValidationService:
    def __init__(self, semantic_validator: SemanticValidator | None = None):
        self.semantic_validator = semantic_validator

    @staticmethod
    def _aggregate(attribute: ClaimAttribute, candidates, decisions):
        support = [item.evidence_id for item, decision in decisions if decision.status in {AttributeValidationStatus.SUPPORTED, AttributeValidationStatus.PARTIAL}]
        contradict = [item.evidence_id for item, decision in decisions if decision.status == AttributeValidationStatus.CONTRADICTED]
        statuses = {decision.status for _, decision in decisions}
        if support and contradict:
            status = AttributeValidationStatus.UNCERTAIN
            rationale = "Relevant evidence explicitly conflicts; supporting and contradicting candidates are preserved."
        elif AttributeValidationStatus.SUPPORTED in statuses:
            status = AttributeValidationStatus.SUPPORTED
            rationale = "One or more structured evidence fields explicitly match the claimed value."
        elif AttributeValidationStatus.PARTIAL in statuses:
            status = AttributeValidationStatus.PARTIAL
            rationale = "The evidence establishes only part of the claimed attribute."
        elif AttributeValidationStatus.CONTRADICTED in statuses:
            status = AttributeValidationStatus.CONTRADICTED
            rationale = "Structured evidence explicitly establishes an incompatible value."
        elif AttributeValidationStatus.UNCERTAIN in statuses:
            status = AttributeValidationStatus.UNCERTAIN
            rationale = next(decision.rationale for _, decision in decisions if decision.status == status)
        else:
            status = AttributeValidationStatus.NOT_FOUND
            rationale = "Relevant evidence does not provide the field required to validate this attribute."
        fields = sorted({field for _, decision in decisions for field in decision.fields})
        return status, support, contradict, rationale, fields

    @staticmethod
    def _authenticity_target(candidate):
        hadith_id = (candidate.structured_fields.get("hadith_id")
                     or candidate.raw_metadata.get("hadith_id")
                     or candidate.provider_record_id)
        if hadith_id:
            return ("hadith_id", str(hadith_id))
        return (
            "route",
            normalize(candidate.text), normalize(candidate.narrator),
            normalize(candidate.raw_metadata.get("source")),
            normalize(candidate.page or candidate.reference),
        )

    def validate(self, claim, evidence_candidates, retrieval_result=None) -> EvidenceValidationResponse:
        if retrieval_result and retrieval_result.retrieval_status == RetrievalStatus.MISSING_CONTEXT:
            reason = retrieval_result.reason or "Required retrieval context is missing."
            validations = [AttributeValidationResult(
                attribute_id=attribute.id, attribute_type=attribute.type, claimed_value=attribute.value,
                asserted_by=attribute.asserted_by, status=AttributeValidationStatus.NOT_FOUND,
                rationale=f"Validation was not attempted because Phase 3 could not retrieve evidence: {reason}",
                validation_method="retrieval_readiness",
            ) for attribute in claim.attributes if attribute.requires_evidence]
            trace = [ValidationTrace(attribute_id=item.attribute_id, method="retrieval_readiness",
                                     candidate_ids=[], fields_compared=[], result=item.status)
                     for item in validations]
            return EvidenceValidationResponse(
                claim_id=claim.id, validations=validations,
                validation_status=ValidationExecutionStatus.SKIPPED,
                retrieval_status=RetrievalStatus.MISSING_CONTEXT,
                missing_context=retrieval_result.missing_context,
                reason=reason, warnings=["Phase 3 retrieval was skipped because required context is missing."],
                trace=trace,
            )
        contextual_claim = (
            claim.domain in {Domain.FIQH, Domain.AQEEDAH, Domain.HISTORY, Domain.SEERAH}
            or claim.claim_type in {
                ClaimType.QURAN_TAFSIR, ClaimType.QURAN_INTERPRETATION, ClaimType.QURAN_CONTEXT,
            }
        )
        if (retrieval_result and retrieval_result.retrieval_status == RetrievalStatus.SOURCE_ERROR
                and contextual_claim):
            is_quran_interpretation = claim.claim_type == ClaimType.QURAN_INTERPRETATION
            failures = [ValidationExecutionFailure(
                attribute_id=attribute.id, stage="retrieval",
                error_type=("TafsirProviderFailure" if is_quran_interpretation
                            else "DorarProviderFailure"),
                message=("Quranpedia Tafsir retrieval failed before evidence validation."
                         if is_quran_interpretation
                         else "Dorar retrieval failed before evidence validation."),
            ) for attribute in claim.attributes if attribute.requires_evidence]
            return EvidenceValidationResponse(
                claim_id=claim.id, validations=[], validation_status=ValidationExecutionStatus.ERROR,
                retrieval_status=RetrievalStatus.SOURCE_ERROR,
                reason=("TAFSIR_PROVIDER_FAILURE" if is_quran_interpretation
                        else "DORAR_PROVIDER_FAILURE"),
                warnings=["تعذر الوصول إلى مصدر التفسير لإكمال التحقق."],
                execution_failures=failures,
            )
        if not claim.requires_evidence or not claim.attributes:
            return EvidenceValidationResponse(claim_id=claim.id, validation_status=ValidationExecutionStatus.SKIPPED,
                                              warnings=["تعذر تحديد عناصر قابلة للتحقق في هذه المطالبة."])
        validations, trace, warnings, failures, authenticity_audit = [], [], [], [], []
        if retrieval_result and retrieval_result.reason == "NO_SUITABLE_INTERPRETATION_PROVIDER":
            warnings.append(
                "لم تتوفر حاليًا مصادر مناسبة للتحقق من هذا النوع من التفسير."
                if claim.claim_type == ClaimType.QURAN_INTERPRETATION else
                "لم تتوفر حاليًا مصادر مناسبة للتحقق من هذا النوع من الشرح."
            )
        alignment_by_id = {
            item.evidence_id: hadith_record_alignment(claim, item) for item in evidence_candidates
        }
        alignment_trace = [CandidateAlignmentTrace(
            evidence_id=item.evidence_id, alignment=alignment_by_id[item.evidence_id][0].value,
            reason=alignment_by_id[item.evidence_id][1],
        ) for item in evidence_candidates]
        quran_identity_types = {
            AttributeType.QURAN_TEXT, AttributeType.SURAH,
            AttributeType.AYAH_NUMBER, AttributeType.AYAH_RANGE,
        }
        claim_types = {item.type for item in claim.attributes}
        requires_quran_alignment = (
            claim.domain == Domain.QURAN
            and AttributeType.QURAN_TEXT in claim_types
            and AttributeType.SURAH in claim_types
            and bool(claim_types & {AttributeType.AYAH_NUMBER, AttributeType.AYAH_RANGE})
        )
        quran_alignment = (aggregate_quran_alignment(claim, evidence_candidates)
                           if requires_quran_alignment else None)
        had_error = False
        for attribute in claim.attributes:
            if not attribute.requires_evidence:
                continue
            candidates = relevant_evidence(attribute, evidence_candidates)
            contextual = [item for item in candidates
                          if item.evidence_type in CONTEXTUAL_EVIDENCE_TYPES]
            contextual_alignment = {
                item.evidence_id: evidence_context_alignment(claim, attribute, item)
                for item in contextual
            }
            alignment_trace.extend(CandidateAlignmentTrace(
                evidence_id=item.evidence_id, attribute_id=attribute.id,
                alignment=contextual_alignment[item.evidence_id][0].value,
                reason=contextual_alignment[item.evidence_id][1],
            ) for item in contextual)
            if contextual:
                candidates = [item for item in candidates
                              if item.evidence_type not in CONTEXTUAL_EVIDENCE_TYPES
                              or contextual_alignment[item.evidence_id][0] == CandidateAlignment.ALIGNED]
            if requires_quran_alignment and attribute.type in quran_identity_types:
                if quran_alignment == QuranRecordAlignment.MISMATCH:
                    mismatch = [item for item in candidates
                                if quran_record_alignment(claim, item)[0] == QuranRecordAlignment.MISMATCH]
                    ids = [item.evidence_id for item in mismatch]
                    result = AttributeValidationResult(
                        attribute_id=attribute.id, attribute_type=attribute.type,
                        claimed_value=attribute.value, asserted_by=attribute.asserted_by,
                        status=AttributeValidationStatus.CONTRADICTED,
                        evidence_ids=ids, contradicting_evidence_ids=ids,
                        rationale=("The Quran text retrieved at the claimed Surah and ayah reference "
                                   "does not match the quoted Quran text."),
                        validation_method="quran_record_alignment", validator_confidence=1.0,
                    )
                    validations.append(result)
                    trace.append(ValidationTrace(
                        attribute_id=attribute.id, method=result.validation_method,
                        candidate_ids=ids, fields_compared=["text", "reference"], result=result.status,
                    ))
                    continue
                if quran_alignment == QuranRecordAlignment.ALIGNED:
                    candidates = [item for item in candidates
                                  if quran_record_alignment(claim, item)[0] == QuranRecordAlignment.ALIGNED]
            requires_alignment = attribute.type in DEPENDENT_RECORD_ATTRIBUTES and any(
                item.type.value in {"TEXT", "HADITH_TEXT"} for item in claim.attributes
            )
            if claim.domain.value in {"HADITH", "ATHAR"} and attribute.type.value in {"TEXT", "HADITH_TEXT"}:
                requires_alignment = True
            if requires_alignment:
                candidates = [item for item in candidates
                              if alignment_by_id[item.evidence_id][0] == CandidateAlignment.ALIGNED]
            ids = [item.evidence_id for item in candidates]
            if not candidates:
                unresolved = [item.evidence_id for item in contextual
                              if contextual_alignment[item.evidence_id][0] == CandidateAlignment.UNRESOLVED]
                result = AttributeValidationResult(
                    attribute_id=attribute.id, attribute_type=attribute.type, claimed_value=attribute.value,
                    asserted_by=attribute.asserted_by,
                    status=(AttributeValidationStatus.UNCERTAIN if unresolved
                            else AttributeValidationStatus.NOT_FOUND),
                    evidence_ids=unresolved,
                    rationale=("Candidate context or attribution could not be resolved safely."
                               if unresolved else
                               "No suitable evidence candidate was linked or conservatively matched to this attribute."),
                    validation_method=("context_alignment" if unresolved else "evidence_matching"),
                )
                fields = []
            else:
                decisions = [(candidate, decision) for candidate in candidates
                             if (decision := validate_candidate(attribute, candidate)) is not None]
                if attribute.type == AttributeType.AUTHENTICITY:
                    if attribute.asserted_by:
                        decisions = [
                            (candidate, decision if normalize(
                                candidate.scholar or candidate.author
                                or candidate.raw_metadata.get("scholar")
                            ) == normalize(attribute.asserted_by) else CandidateDecision(
                                AttributeValidationStatus.UNCERTAIN,
                                "The grade belongs to a different or unidentified scholar.",
                                decision.fields + ["scholar", "author"],
                            ))
                            for candidate, decision in decisions
                        ]
                    supporting_targets = {
                        self._authenticity_target(candidate)
                        for candidate, decision in decisions
                        if decision.status in {
                            AttributeValidationStatus.SUPPORTED,
                            AttributeValidationStatus.PARTIAL,
                        }
                    }
                    if supporting_targets:
                        decisions = [
                            (candidate, decision) for candidate, decision in decisions
                            if decision.status != AttributeValidationStatus.CONTRADICTED
                            or self._authenticity_target(candidate) in supporting_targets
                        ]
                    participating = {candidate.evidence_id: decision.status.value
                                     for candidate, decision in decisions}
                    for candidate in candidates:
                        alignment = alignment_by_id[candidate.evidence_id][0]
                        authenticity_audit.append({
                            "attribute_id": attribute.id,
                            "evidence_id": candidate.evidence_id,
                            "hadith_id": candidate.structured_fields.get("hadith_id")
                                         or candidate.raw_metadata.get("hadith_id")
                                         or candidate.provider_record_id,
                            "alignment": alignment.value,
                            "narrator": candidate.narrator,
                            "scholar": candidate.scholar,
                            "source": candidate.raw_metadata.get("source"),
                            "reference": candidate.page or candidate.reference,
                            "raw_grade": candidate.judgment or candidate.raw_metadata.get("grade"),
                            "grade_category": grade_category(
                                candidate.judgment or candidate.raw_metadata.get("grade")),
                            "eligible": candidate.evidence_id in participating,
                            "contribution": participating.get(candidate.evidence_id),
                            "exclusion_reason": (None if candidate.evidence_id in participating else
                                "scholar attribution mismatch" if attribute.asserted_by and
                                normalize(candidate.scholar or candidate.author
                                          or candidate.raw_metadata.get("scholar"))
                                != normalize(attribute.asserted_by) else
                                "different authenticity target or unclassified grade"),
                        })
                # Different aligned transmission/collection records are alternatives, not
                # deterministic negations of a claimed Hadith narrator or source.
                conservative_hadith_attribution = (
                    claim.domain in {Domain.HADITH, Domain.ATHAR}
                    and attribute.type in {
                        AttributeType.NARRATOR, AttributeType.SOURCE, AttributeType.COLLECTION,
                    }
                )
                if conservative_hadith_attribution:
                    decisions = [
                        (candidate, decision) for candidate, decision in decisions
                        if decision.status != AttributeValidationStatus.CONTRADICTED
                    ]
                conclusive = any(decision.status != AttributeValidationStatus.NOT_FOUND for _, decision in decisions)
                if (conclusive or attribute.type == AttributeType.AUTHENTICITY
                        or conservative_hadith_attribution):
                    status, support, contradict, rationale, fields = self._aggregate(attribute, candidates, decisions)
                    result = AttributeValidationResult(
                        attribute_id=attribute.id, attribute_type=attribute.type, claimed_value=attribute.value,
                        asserted_by=attribute.asserted_by, status=status, evidence_ids=ids,
                        supporting_evidence_ids=support, contradicting_evidence_ids=contradict,
                        rationale=rationale, validation_method="deterministic", validator_confidence=1.0,
                    )
                elif self.semantic_validator:
                    try:
                        semantic = self.semantic_validator.validate(attribute, candidates)
                        result = AttributeValidationResult(
                            attribute_id=attribute.id, attribute_type=attribute.type, claimed_value=attribute.value,
                            asserted_by=attribute.asserted_by, status=semantic.status, evidence_ids=ids,
                            supporting_evidence_ids=semantic.supporting_evidence_ids,
                            contradicting_evidence_ids=semantic.contradicting_evidence_ids,
                            rationale=semantic.rationale, validation_method="semantic",
                            validator_confidence=semantic.confidence,
                        )
                        fields = ["evidence content", "provenance"]
                    except SemanticValidationError as exc:
                        had_error = True
                        warnings.append(f"Semantic validation execution failed for {attribute.id}: {exc}")
                        failures.append(ValidationExecutionFailure(
                            attribute_id=attribute.id, stage=exc.stage,
                            error_type=exc.error_type, message=str(exc),
                        ))
                        continue
                else:
                    had_error = True
                    warnings.append(f"Semantic validation unavailable for {attribute.id}.")
                    failures.append(ValidationExecutionFailure(
                        attribute_id=attribute.id, stage="configuration",
                        error_type="SemanticValidatorUnavailable",
                        message="Semantic validation is not configured.",
                    ))
                    continue
            validations.append(result)
            if requires_alignment:
                aligned_ids = {evidence_id for evidence_id, alignment in alignment_by_id.items()
                               if alignment[0] == CandidateAlignment.ALIGNED}
                assert set(result.supporting_evidence_ids + result.contradicting_evidence_ids) <= aligned_ids
            trace.append(ValidationTrace(attribute_id=attribute.id, method=result.validation_method,
                                         candidate_ids=ids, fields_compared=fields, result=result.status))
        execution = (ValidationExecutionStatus.ERROR if had_error and not validations
                     else ValidationExecutionStatus.PARTIAL if had_error
                     else ValidationExecutionStatus.COMPLETED)
        return EvidenceValidationResponse(claim_id=claim.id, validations=validations,
                                          validation_status=execution,
                                          retrieval_status=retrieval_result.retrieval_status if retrieval_result else None,
                                          warnings=warnings, trace=trace, execution_failures=failures,
                                          authenticity_audit=authenticity_audit,
                                          candidate_alignment=alignment_trace,
                                          quran_record_alignment=(quran_alignment.value
                                                                  if quran_alignment else None))
