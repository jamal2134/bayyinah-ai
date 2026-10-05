import asyncio
import re

from app.models.claim import AttributeType, ClaimType
from app.models.evidence import EvidenceProvider, EvidenceType
from app.models.retrieval import (
    DependencyStatus, DependencyTrace, RetrievalPurpose, RetrievalResult,
    RetrievalStatus, RetrievalTask,
)
from app.retrieval.router import create_retrieval_plan
from app.retrieval.readiness import assess_retrieval_readiness
from app.validation.evidence_matcher import CandidateAlignment, align_hadith_texts, hadith_record_alignment


def deduplicate_evidence(items):
    seen, output = set(), []
    for item in items:
        if item.evidence_type == EvidenceType.QURAN_TAFSIR:
            # A Tafsir book is reused for every ayah.  The book ID alone is not
            # a record identity, otherwise a multi-verse lookup collapses all
            # verses after the first one.
            key = (item.provider.value, "tafsir", item.provider_record_id, item.reference)
        elif item.provider_record_id:
            key = (item.provider.value, "id", item.provider_record_id, item.scholar, item.judgment)
        else:
            normalize = lambda value: re.sub(r"\s+", " ", (value or "").casefold()).strip()
            key = (item.provider.value, normalize(item.source_name), normalize(item.text),
                   normalize(item.reference), normalize(item.scholar), normalize(item.judgment))
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


class RetrievalService:
    def __init__(self, adapters):
        self.adapters = adapters

    @staticmethod
    def _explanation_identity(parent, explanation):
        parent_id = (parent.structured_fields.get("hadith_id")
                     or parent.raw_metadata.get("hadith_id"))
        explanation_id = (explanation.structured_fields.get("hadith_id")
                          or explanation.raw_metadata.get("hadith_id"))
        if parent_id and explanation_id and str(parent_id) != str(explanation_id):
            return CandidateAlignment.UNRELATED, "Explanation Hadith ID differs from the aligned parent Hadith ID."
        explanation_text = (explanation.structured_fields.get("hadith_text")
                            or explanation.raw_metadata.get("hadith_text"))
        return align_hadith_texts([parent.text], explanation_text)

    async def _retrieve_hadith_explanations(self, claim, parent_claim, plan, results):
        traces = []
        if claim.claim_type not in {ClaimType.HADITH_MEANING, ClaimType.HADITH_INTERPRETATION}:
            return [], traces
        interpretation_ids = [item.id for item in claim.attributes
                              if item.id and item.requires_evidence
                              and item.type == AttributeType.INTERPRETATION]
        explanation_adapter = self.adapters.get(EvidenceProvider.DORAR_HADITH_EXPLANATION)
        if not interpretation_ids or explanation_adapter is None:
            return [], traces
        parent_task = next((task for task in plan.tasks
                            if task.provider == EvidenceProvider.DORAR_HADITH), None)
        if parent_task is None:
            return [], traces
        parents = [candidate for result in results
                   if result.provider == EvidenceProvider.DORAR_HADITH
                   for candidate in result.evidence]
        eligible = {}
        for parent in parents:
            alignment, reason = hadith_record_alignment(claim, parent, parent_claim=parent_claim)
            dependency_id = str(parent.structured_fields.get("explanation_id") or "").strip()
            if alignment != CandidateAlignment.ALIGNED:
                traces.append(DependencyTrace(
                    provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                    status=(DependencyStatus.PARENT_UNRELATED
                            if alignment == CandidateAlignment.UNRELATED
                            else DependencyStatus.PARENT_UNRESOLVED),
                    parent_task_id=parent_task.task_id, parent_evidence_id=parent.evidence_id,
                    dependency_record_id=dependency_id or None, reason=reason))
                continue
            if parent.structured_fields.get("explanation_available") is not True:
                traces.append(DependencyTrace(
                    provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                    status=DependencyStatus.EXPLANATION_NOT_AVAILABLE,
                    parent_task_id=parent_task.task_id, parent_evidence_id=parent.evidence_id,
                    dependency_record_id=dependency_id or None,
                    reason="The aligned Hadith record does not advertise an explanation."))
                continue
            if not dependency_id:
                traces.append(DependencyTrace(
                    provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                    status=DependencyStatus.EXPLANATION_ID_MISSING,
                    parent_task_id=parent_task.task_id, parent_evidence_id=parent.evidence_id,
                    reason="The aligned Hadith record has no usable explanation ID."))
                continue
            eligible.setdefault(dependency_id, []).append(parent)

        dependent_results = []
        for dependency_id, aligned_parents in eligible.items():
            authorizing_parent = aligned_parents[0]
            task_id = f"task_{len(plan.tasks) + 1:03d}"
            task = RetrievalTask(
                task_id=task_id, claim_id=claim.id, target_attribute_ids=interpretation_ids,
                provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                purpose=RetrievalPurpose.HADITH_EXPLANATION,
                depends_on_task_id=parent_task.task_id,
                dependency_evidence_id=authorizing_parent.evidence_id,
                execution_condition="PARENT_ALIGNED_AND_EXPLANATION_AVAILABLE_AND_ID_PRESENT",
            )
            plan.tasks.append(task)
            hadith_id = (authorizing_parent.structured_fields.get("hadith_id")
                         or authorizing_parent.raw_metadata.get("hadith_id") or "")
            result = await explanation_adapter.retrieve_by_id(
                claim.id, dependency_id, str(hadith_id),
                parent_evidence_id=authorizing_parent.evidence_id)
            dependent_results.append(result)
            if not result.success or not result.evidence:
                status = (DependencyStatus.NO_RESULTS if result.error and
                          result.error.error_type.value == "NO_RESULTS"
                          else DependencyStatus.PROVIDER_FAILURE)
                traces.append(DependencyTrace(
                    provider=EvidenceProvider.DORAR_HADITH_EXPLANATION, status=status,
                    parent_task_id=parent_task.task_id, dependent_task_id=task_id,
                    parent_evidence_id=authorizing_parent.evidence_id,
                    dependency_record_id=dependency_id,
                    reason=(result.error.message if result.error else
                            "Dependent explanation retrieval returned no usable evidence.")))
                for duplicate_parent in aligned_parents[1:]:
                    traces.append(DependencyTrace(
                        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                        status=DependencyStatus.DUPLICATE_EXPLANATION_SKIPPED,
                        parent_task_id=parent_task.task_id, dependent_task_id=task_id,
                        parent_evidence_id=duplicate_parent.evidence_id,
                        dependency_record_id=dependency_id,
                        reason="The shared explanation ID was called once; its failure applies to this parent too."))
                continue

            accepted = None
            accepted_parent = None
            rejection = CandidateAlignment.UNRESOLVED
            rejection_reason = "Explanation identity could not be resolved."
            for parent in aligned_parents:
                for candidate in result.evidence:
                    alignment, reason = self._explanation_identity(parent, candidate)
                    if alignment == CandidateAlignment.ALIGNED:
                        accepted, accepted_parent = candidate, parent
                        break
                    if alignment == CandidateAlignment.UNRELATED:
                        rejection = alignment
                    rejection_reason = reason
                if accepted:
                    break
            if accepted is None:
                result.evidence = []
                result.success = False
                traces.append(DependencyTrace(
                    provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                    status=(DependencyStatus.EXPLANATION_IDENTITY_MISMATCH
                            if rejection == CandidateAlignment.UNRELATED
                            else DependencyStatus.EXPLANATION_IDENTITY_UNRESOLVED),
                    parent_task_id=parent_task.task_id, dependent_task_id=task_id,
                    parent_evidence_id=authorizing_parent.evidence_id,
                    dependency_record_id=dependency_id, reason=rejection_reason))
                for duplicate_parent in aligned_parents[1:]:
                    traces.append(DependencyTrace(
                        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                        status=DependencyStatus.DUPLICATE_EXPLANATION_SKIPPED,
                        parent_task_id=parent_task.task_id, dependent_task_id=task_id,
                        parent_evidence_id=duplicate_parent.evidence_id,
                        dependency_record_id=dependency_id,
                        reason="The shared explanation ID was fetched once and rejected by identity checks."))
                continue
            accepted.parent_evidence_id = accepted_parent.evidence_id
            accepted.target_attribute_ids = interpretation_ids
            result.evidence = [accepted]
            traces.append(DependencyTrace(
                provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                status=DependencyStatus.ACCEPTED, parent_task_id=parent_task.task_id,
                dependent_task_id=task_id, parent_evidence_id=accepted_parent.evidence_id,
                dependency_record_id=dependency_id,
                reason="Explanation identity is aligned to the authorizing Hadith record."))
            for duplicate_parent in aligned_parents:
                if duplicate_parent.evidence_id != accepted_parent.evidence_id:
                    traces.append(DependencyTrace(
                        provider=EvidenceProvider.DORAR_HADITH_EXPLANATION,
                        status=DependencyStatus.DUPLICATE_EXPLANATION_SKIPPED,
                        parent_task_id=parent_task.task_id, dependent_task_id=task_id,
                        parent_evidence_id=duplicate_parent.evidence_id,
                        dependency_record_id=dependency_id,
                        reason="The same explanation ID was fetched once for multiple aligned records."))
        return dependent_results, traces

    async def retrieve(self, claim, parent_quran_alignment: str | None = None, parent_claim=None):
        query_limits = {provider: getattr(adapter, "max_attempts", 2)
                        for provider, adapter in self.adapters.items()}
        result_limits = {provider: adapter.max_results for provider, adapter in self.adapters.items()
                         if getattr(adapter, "max_results", None) is not None}
        plan = create_retrieval_plan(claim, query_limits=query_limits, result_limits=result_limits)
        plan.sources = [source for source in plan.sources if source.provider in self.adapters]
        plan.tasks = [task for task in plan.tasks if task.provider in self.adapters]
        if not claim.requires_evidence:
            return RetrievalResult(claim_id=claim.id, retrieval_plan=plan, provider_results=[],
                                   total_evidence_candidates=0, retrieval_status=RetrievalStatus.SKIPPED,
                                   reason="CLAIM_DOES_NOT_REQUIRE_EXTERNAL_EVIDENCE")
        if (claim.claim_type == ClaimType.QURAN_INTERPRETATION
                and parent_quran_alignment != "ALIGNED"):
            return RetrievalResult(
                claim_id=claim.id, retrieval_ready=False,
                missing_context=["PARENT_QURAN_ALIGNMENT"], retrieval_plan=plan,
                provider_results=[], total_evidence_candidates=0,
                retrieval_status=RetrievalStatus.MISSING_CONTEXT,
                reason="PARENT_QURAN_REFERENCE_NOT_ALIGNED",
            )
        ready, missing, readiness_reason = assess_retrieval_readiness(claim, parent_claim=parent_claim)
        if not ready:
            return RetrievalResult(claim_id=claim.id, retrieval_ready=False, missing_context=missing,
                                   retrieval_plan=plan, provider_results=[], total_evidence_candidates=0,
                                   retrieval_status=RetrievalStatus.MISSING_CONTEXT,
                                   reason=readiness_reason)
        if not plan.sources:
            interpretation = claim.claim_type in {
                ClaimType.QURAN_INTERPRETATION, ClaimType.HADITH_INTERPRETATION,
            }
            return RetrievalResult(claim_id=claim.id, retrieval_plan=plan, provider_results=[],
                                   total_evidence_candidates=0,
                                   retrieval_status=RetrievalStatus.NO_SUPPORTED_SOURCE,
                                   reason=("NO_SUITABLE_INTERPRETATION_PROVIDER" if interpretation
                                           else "NO_SUPPORTED_PROVIDER_ROUTE"))
        results = await asyncio.gather(*[
            self.adapters[source.provider].retrieve(claim) for source in plan.sources
        ])
        for result in results:
            target_ids = next((task.target_attribute_ids for task in plan.tasks
                               if task.provider == result.provider), [])
            for candidate in result.evidence:
                candidate.target_attribute_ids = target_ids
            result.evidence = deduplicate_evidence(result.evidence)
        dependent_results, dependency_trace = await self._retrieve_hadith_explanations(
            claim, parent_claim, plan, results)
        results.extend(dependent_results)
        for result in dependent_results:
            result.evidence = deduplicate_evidence(result.evidence)
        all_evidence = deduplicate_evidence([item for result in results for item in result.evidence])
        successes = sum(result.success for result in results)
        if all_evidence and successes == len(results):
            status = RetrievalStatus.COMPLETED
        elif all_evidence:
            status = RetrievalStatus.PARTIAL
        elif successes:
            status = RetrievalStatus.NO_RESULTS
        else:
            status = (RetrievalStatus.NO_RESULTS if results and all(
                result.error and result.error.error_type.value == "NO_RESULTS" for result in results)
                else RetrievalStatus.SOURCE_ERROR)
        return RetrievalResult(claim_id=claim.id, retrieval_plan=plan, provider_results=results,
                               total_evidence_candidates=len(all_evidence), retrieval_status=status,
                               dependency_trace=dependency_trace)

