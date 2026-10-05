from datetime import datetime, timezone

import pytest

from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate, EvidenceProvider, EvidenceType
from app.models.retrieval import RetrievalPlan, RetrievalResult, RetrievalStatus
from app.models.validation import AttributeValidationStatus, SemanticValidationOutput
from app.validation.service import EvidenceValidationService


def claim(domain, claim_type, attribute_type, value, *, normalized, asserted_by=None,
          subject_context=None):
    data = {
        "id": "claim_001", "original_text": normalized, "normalized_claim": normalized,
        "claim_type": claim_type, "domain": domain,
        "attributes": [{"id": "attr_001", "type": attribute_type, "value": value,
                        "asserted_by": asserted_by}],
        "search_queries": [f"{normalized} evidence"], "requires_evidence": True,
        "reason": "Stage 4 validation test",
    }
    if subject_context:
        data["subject_context"] = subject_context
    return Claim.model_validate(data)


def candidate(evidence_type, identifier, text, *, title=None, structured=None,
              score=None, rank=None):
    providers = {
        EvidenceType.TAFSEER_SECTION: EvidenceProvider.DORAR_TAFSEER,
        EvidenceType.FIQH_CONTENT: EvidenceProvider.DORAR_FEQHIA,
        EvidenceType.AQEEDA_CONTENT: EvidenceProvider.DORAR_AQEEDA,
        EvidenceType.HISTORY_EVENT: EvidenceProvider.DORAR_HISTORY,
    }
    return EvidenceCandidate(
        evidence_id=identifier, claim_id="claim_001", provider=providers[evidence_type],
        evidence_type=evidence_type, title=title, text=text,
        provider_score=score, result_rank=rank, retrieved_at=datetime.now(timezone.utc),
        structured_fields=structured or {},
    )


class Semantic:
    def __init__(self, status=AttributeValidationStatus.SUPPORTED, support=None, contradict=None):
        self.status = status
        self.support = support
        self.contradict = contradict or []
        self.calls = []

    def validate(self, attribute, candidates):
        self.calls.append(list(candidates))
        support = self.support
        if support is None and self.status in {
            AttributeValidationStatus.SUPPORTED, AttributeValidationStatus.PARTIAL,
        }:
            support = [item.evidence_id for item in candidates]
        return SemanticValidationOutput(
            status=self.status, supporting_evidence_ids=support or [],
            contradicting_evidence_ids=self.contradict,
            rationale="Verdict is limited to the supplied aligned evidence.", confidence=.9,
        )


def validate(item, evidence, semantic=None, retrieval=None):
    return EvidenceValidationService(semantic).validate(item, evidence, retrieval)


@pytest.mark.parametrize("status", [
    AttributeValidationStatus.SUPPORTED,
    AttributeValidationStatus.PARTIAL,
    AttributeValidationStatus.CONTRADICTED,
])
def test_tafseer_aligned_context_reaches_semantic_verdict(status):
    item = claim("QURAN", "QURAN_TAFSIR", "INTERPRETATION", "Allah is the protector",
                 normalized="interpretation of ayat al kursi",
                 subject_context={"type": "QURAN", "surah": "2", "ayah_number": "255"})
    evidence = candidate(EvidenceType.TAFSEER_SECTION, "tafseer:1", "Detailed interpretation",
                         structured={"surah_id": 2, "page_id": 255})
    semantic = Semantic(status, support=[] if status == AttributeValidationStatus.CONTRADICTED else None,
                        contradict=["tafseer:1"] if status == AttributeValidationStatus.CONTRADICTED else [])
    response = validate(item, [evidence], semantic)
    assert response.validations[0].status == status
    assert [row.evidence_id for row in response.candidate_alignment
            if row.attribute_id == "attr_001" and row.alignment == "ALIGNED"] == ["tafseer:1"]


def test_tafseer_wrong_or_unresolved_parent_never_reaches_semantic():
    semantic = Semantic()
    aligned_claim = claim("QURAN", "QURAN_TAFSIR", "INTERPRETATION", "meaning",
                          normalized="interpretation of a verse",
                          subject_context={"type": "QURAN", "surah": "2", "ayah_number": "255"})
    wrong = candidate(EvidenceType.TAFSEER_SECTION, "tafseer:wrong", "Other tafseer",
                      structured={"surah_id": 3, "page_id": 7})
    assert validate(aligned_claim, [wrong], semantic).validations[0].status == AttributeValidationStatus.NOT_FOUND
    unresolved_claim = claim("QURAN", "QURAN_TAFSIR", "INTERPRETATION", "meaning",
                             normalized="interpretation without verse identity")
    unresolved = validate(unresolved_claim, [wrong], semantic).validations[0]
    assert unresolved.status == AttributeValidationStatus.UNCERTAIN
    assert unresolved.evidence_ids == ["tafseer:wrong"]
    assert semantic.calls == []


def test_multiple_tafseer_sections_remain_distinct_and_cannot_validate_quran_text():
    context = {"type": "QURAN", "surah": "2", "ayah_number": "255"}
    sections = [candidate(EvidenceType.TAFSEER_SECTION, f"tafseer:{number}", f"section {number}",
                          structured={"surah_id": 2, "page_id": 255}) for number in (1, 2)]
    semantic = Semantic()
    interpretation = claim("QURAN", "QURAN_TAFSIR", "INTERPRETATION", "meaning",
                           normalized="interpretation of ayat al kursi", subject_context=context)
    response = validate(interpretation, sections, semantic)
    assert response.validations[0].evidence_ids == ["tafseer:1", "tafseer:2"]
    assert [item.evidence_id for item in semantic.calls[0]] == ["tafseer:1", "tafseer:2"]
    text_claim = claim("QURAN", "QURAN_TEXT", "QURAN_TEXT", "verse text",
                       normalized="quoted Quran verse text", subject_context=context)
    assert validate(text_claim, sections, semantic).validations[0].status == AttributeValidationStatus.NOT_FOUND


@pytest.mark.parametrize("domain,claim_type,evidence_type,attribute_type", [
    ("FIQH", "FIQH_RULING", EvidenceType.FIQH_CONTENT, "RULING"),
    ("AQEEDAH", "AQEEDAH", EvidenceType.AQEEDA_CONTENT, "OTHER"),
])
def test_fiqh_and_aqeeda_require_topic_and_claimed_attribution(
        domain, claim_type, evidence_type, attribute_type):
    attributed = claim(domain, claim_type, attribute_type, "the position is permitted",
                       normalized="witr prayer legal position", asserted_by="Shafii")
    generic = candidate(evidence_type, "generic", "witr prayer legal position is discussed",
                        title="witr prayer legal position")
    semantic = Semantic()
    generic_result = validate(attributed, [generic], semantic).validations[0]
    assert generic_result.status == AttributeValidationStatus.UNCERTAIN
    assert semantic.calls == []
    explicit = candidate(evidence_type, "explicit", "Shafii: witr prayer legal position is permitted",
                         title="Shafii witr prayer legal position")
    explicit_result = validate(attributed, [explicit], semantic).validations[0]
    assert explicit_result.status == AttributeValidationStatus.SUPPORTED
    unrelated = candidate(evidence_type, "unrelated", "rules for commercial leases",
                          title="commercial leases")
    assert validate(attributed.model_copy(update={
        "attributes": [attributed.attributes[0].model_copy(update={"asserted_by": None})]}),
        [unrelated], semantic).validations[0].status == AttributeValidationStatus.NOT_FOUND


def test_different_attribution_is_not_a_contradiction_and_scores_do_not_create_support():
    item = claim("FIQH", "FIQH_RULING", "RULING", "permitted",
                 normalized="witr prayer legal position", asserted_by="Shafii")
    other_school = candidate(EvidenceType.FIQH_CONTENT, "fiqh:hanafi",
                             "Hanafi witr prayer legal position is required",
                             title="Hanafi witr prayer legal position", score=999, rank=1)
    semantic = Semantic(AttributeValidationStatus.CONTRADICTED, contradict=["fiqh:hanafi"])
    result = validate(item, [other_school], semantic).validations[0]
    assert result.status == AttributeValidationStatus.UNCERTAIN
    assert result.contradicting_evidence_ids == []
    assert semantic.calls == []


@pytest.mark.parametrize("domain,claim_type,evidence_type,attribute_type", [
    ("FIQH", "FIQH_RULING", EvidenceType.FIQH_CONTENT, "RULING"),
    ("AQEEDAH", "AQEEDAH", EvidenceType.AQEEDA_CONTENT, "OTHER"),
])
@pytest.mark.parametrize("status", [
    AttributeValidationStatus.SUPPORTED, AttributeValidationStatus.CONTRADICTED,
])
def test_aligned_fiqh_and_aqeeda_preserve_explicit_semantic_verdict(
        domain, claim_type, evidence_type, attribute_type, status):
    item = claim(domain, claim_type, attribute_type, "proposition A",
                 normalized="fasting intention legal proposition")
    evidence = candidate(evidence_type, "domain:1", "fasting intention legal proposition B",
                         title="fasting intention legal proposition")
    semantic = Semantic(status, support=[] if status == AttributeValidationStatus.CONTRADICTED else None,
                        contradict=["domain:1"] if status == AttributeValidationStatus.CONTRADICTED else [])
    result = validate(item, [evidence], semantic).validations[0]
    assert result.status == status
    assert len(semantic.calls) == 1


@pytest.mark.parametrize("value,structured,expected", [
    ("8 AH", {"hijri_year": 8, "gregorian_year": 630}, AttributeValidationStatus.SUPPORTED),
    ("9 AH", {"hijri_year": 8, "gregorian_year": 630}, AttributeValidationStatus.CONTRADICTED),
    ("630 CE", {"hijri_year": 8, "gregorian_year": 630}, AttributeValidationStatus.SUPPORTED),
    ("8 AH", {"gregorian_year": 630}, AttributeValidationStatus.UNCERTAIN),
    ("630", {"hijri_year": 8, "gregorian_year": 630}, AttributeValidationStatus.UNCERTAIN),
])
def test_history_date_compares_only_same_calendar_on_aligned_event(value, structured, expected):
    item = claim("HISTORY", "ISLAMIC_HISTORY", "DATE", value,
                 normalized="Treaty of Hudaybiyyah date")
    evidence = candidate(EvidenceType.HISTORY_EVENT, "history:1", "Treaty details",
                         title="Treaty of Hudaybiyyah", structured=structured)
    result = validate(item, [evidence]).validations[0]
    assert result.status == expected


def test_history_different_event_year_never_becomes_contradiction():
    item = claim("HISTORY", "ISLAMIC_HISTORY", "DATE", "8 AH",
                 normalized="Treaty of Hudaybiyyah date")
    evidence = candidate(EvidenceType.HISTORY_EVENT, "history:other", "Birth event details",
                         title="Birth of a scholar", structured={"hijri_year": 99})
    result = validate(item, [evidence]).validations[0]
    assert result.status == AttributeValidationStatus.NOT_FOUND
    assert result.contradicting_evidence_ids == []


def test_history_location_and_detail_use_semantic_only_after_event_alignment():
    semantic = Semantic(AttributeValidationStatus.PARTIAL)
    item = claim("HISTORY", "ISLAMIC_HISTORY", "LOCATION", "near Makkah",
                 normalized="Treaty of Hudaybiyyah location")
    evidence = candidate(EvidenceType.HISTORY_EVENT, "history:1", "The treaty occurred nearby",
                         title="Treaty of Hudaybiyyah")
    result = validate(item, [evidence], semantic).validations[0]
    assert result.status == AttributeValidationStatus.PARTIAL
    assert semantic.calls


@pytest.mark.parametrize("status", [
    AttributeValidationStatus.SUPPORTED,
    AttributeValidationStatus.CONTRADICTED,
    AttributeValidationStatus.NOT_FOUND,
])
def test_history_detail_and_missing_location_preserve_semantic_relationship(status):
    semantic = Semantic(status, support=[] if status != AttributeValidationStatus.SUPPORTED else None,
                        contradict=["history:1"] if status == AttributeValidationStatus.CONTRADICTED else [])
    item = claim("HISTORY", "ISLAMIC_HISTORY", "LOCATION", "inside Madinah",
                 normalized="Constitution of Madinah location")
    evidence = candidate(EvidenceType.HISTORY_EVENT, "history:1", "Event details supplied here",
                         title="Constitution of Madinah")
    result = validate(item, [evidence], semantic).validations[0]
    assert result.status == status


def test_multiple_unrelated_candidates_produce_no_semantic_or_factual_verdict():
    item = claim("AQEEDAH", "AQEEDAH", "OTHER", "doctrinal proposition",
                 normalized="divine attributes doctrinal proposition")
    evidence = [
        candidate(EvidenceType.AQEEDA_CONTENT, "aqeeda:1", "commercial lease rules",
                  title="commercial leases"),
        candidate(EvidenceType.AQEEDA_CONTENT, "aqeeda:2", "historical chronology",
                  title="historical chronology"),
    ]
    semantic = Semantic()
    result = validate(item, evidence, semantic).validations[0]
    assert result.status == AttributeValidationStatus.NOT_FOUND
    assert result.supporting_evidence_ids == result.contradicting_evidence_ids == []
    assert semantic.calls == []


def test_mixed_aligned_and_unrelated_evidence_filters_before_semantic_and_preserves_conflict_ids():
    item = claim("FIQH", "FIQH_RULING", "RULING", "permitted",
                 normalized="witr prayer legal position")
    aligned = candidate(EvidenceType.FIQH_CONTENT, "fiqh:aligned",
                        "witr prayer legal position is permitted", title="witr prayer legal position")
    unrelated = candidate(EvidenceType.FIQH_CONTENT, "fiqh:other",
                          "commercial lease details", title="commercial lease")
    semantic = Semantic(AttributeValidationStatus.UNCERTAIN,
                        support=["fiqh:aligned"], contradict=["fiqh:aligned"])
    result = validate(item, [aligned, unrelated], semantic).validations[0]
    assert [row.evidence_id for row in semantic.calls[0]] == ["fiqh:aligned"]
    assert result.supporting_evidence_ids == ["fiqh:aligned"]
    assert result.contradicting_evidence_ids == ["fiqh:aligned"]


def test_dorar_provider_failure_is_execution_error_not_not_found():
    item = claim("AQEEDAH", "AQEEDAH", "OTHER", "a doctrinal proposition",
                 normalized="divine attributes doctrinal proposition")
    retrieval = RetrievalResult(
        claim_id=item.id, retrieval_plan=RetrievalPlan(claim_id=item.id, sources=[]),
        total_evidence_candidates=0, retrieval_status=RetrievalStatus.SOURCE_ERROR,
        reason="provider timed out",
    )
    response = validate(item, [], retrieval=retrieval)
    assert response.validation_status.value == "ERROR"
    assert response.validations == []
    assert response.reason == "DORAR_PROVIDER_FAILURE"
    assert response.execution_failures[0].error_type == "DorarProviderFailure"
