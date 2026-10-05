from app.models.claim import AttributeType, Claim, ClaimType, Domain
from app.models.evidence import EvidenceProvider
from app.models.retrieval import PlannedSource, RetrievalPlan, RetrievalPurpose, RetrievalTask
from app.retrieval.query_selector import select_provider_queries


TARGET_TYPES = {
    EvidenceProvider.QURANPEDIA: {
        AttributeType.QURAN_TEXT, AttributeType.INTERPRETATION, AttributeType.SURAH,
        AttributeType.AYAH_NUMBER, AttributeType.AYAH_RANGE, AttributeType.VERSE_COUNT,
        AttributeType.REVELATION_PERIOD,
    },
    EvidenceProvider.HADEETHENC: {
        AttributeType.TEXT, AttributeType.HADITH_TEXT, AttributeType.NARRATOR,
        AttributeType.SOURCE, AttributeType.COLLECTION, AttributeType.AUTHENTICITY,
    },
    EvidenceProvider.DORAR: {
        AttributeType.AUTHENTICITY, AttributeType.SCHOLAR, AttributeType.TEXT,
    },
    EvidenceProvider.DORAR_HADITH: {
        AttributeType.TEXT, AttributeType.HADITH_TEXT, AttributeType.NARRATOR,
        AttributeType.SOURCE, AttributeType.COLLECTION, AttributeType.AUTHENTICITY,
        AttributeType.SCHOLAR,
    },
    EvidenceProvider.DORAR_TAFSEER: {AttributeType.INTERPRETATION, AttributeType.OTHER},
    EvidenceProvider.DORAR_FEQHIA: {AttributeType.RULING, AttributeType.TEXT, AttributeType.OTHER},
    EvidenceProvider.DORAR_AQEEDA: {
        AttributeType.TEXT, AttributeType.OTHER, AttributeType.INTERPRETATION,
    },
    EvidenceProvider.DORAR_HISTORY: {
        AttributeType.TEXT, AttributeType.DATE, AttributeType.LOCATION, AttributeType.OTHER,
    },
}


def _target_ids(claim, provider):
    types = TARGET_TYPES.get(provider, {attribute.type for attribute in claim.attributes})
    return [attribute.id for attribute in claim.attributes
            if attribute.id and attribute.requires_evidence and attribute.type in types]


def _source(provider, purpose, priority):
    return PlannedSource(provider=provider, purpose=purpose, priority=priority)


def create_retrieval_plan(claim: Claim, query_limits=None, result_limits=None) -> RetrievalPlan:
    if not claim.requires_evidence or claim.claim_type == ClaimType.NON_VERIFIABLE:
        return RetrievalPlan(claim_id=claim.id, sources=[])
    query_limits = query_limits or {}
    result_limits = result_limits or {}
    sources: list[PlannedSource] = []
    attribute_types = {item.type for item in claim.attributes}

    if claim.domain == Domain.QURAN:
        if claim.claim_type in {ClaimType.QURAN_TAFSIR, ClaimType.QURAN_INTERPRETATION}:
            sources.extend([
                _source(EvidenceProvider.DORAR_TAFSEER, RetrievalPurpose.QURAN_TAFSIR, 1),
                _source(EvidenceProvider.QURANPEDIA, RetrievalPurpose.QURAN_TAFSIR, 2),
            ])
        elif claim.claim_type == ClaimType.QURAN_CONTEXT:
            sources.append(_source(EvidenceProvider.DORAR_TAFSEER,
                                   RetrievalPurpose.QURAN_TAFSIR, 1))
        else:
            sources.append(_source(EvidenceProvider.QURANPEDIA,
                                   RetrievalPurpose.QURAN_RETRIEVAL, 1))
    elif claim.domain == Domain.HADITH:
        authenticity = (AttributeType.AUTHENTICITY in attribute_types
                        or claim.claim_type == ClaimType.HADITH_AUTHENTICITY)
        meaning = claim.claim_type in {ClaimType.HADITH_MEANING, ClaimType.HADITH_INTERPRETATION}
        if authenticity or meaning:
            sources.append(_source(EvidenceProvider.DORAR_HADITH,
                                   RetrievalPurpose.HADITH_SOURCE_AND_JUDGMENT, 1))
            if authenticity:
                sources.append(_source(EvidenceProvider.HADEETHENC,
                                       RetrievalPurpose.STRUCTURED_HADITH_RETRIEVAL, 2))
        else:
            sources.extend([
                _source(EvidenceProvider.HADEETHENC,
                        RetrievalPurpose.STRUCTURED_HADITH_RETRIEVAL, 1),
                _source(EvidenceProvider.DORAR_HADITH,
                        RetrievalPurpose.HADITH_SOURCE_AND_JUDGMENT, 2),
            ])
    elif claim.domain == Domain.ATHAR:
        sources.append(_source(EvidenceProvider.DORAR,
                               RetrievalPurpose.ATHAR_SOURCE_AND_JUDGMENT, 1))
    elif claim.domain == Domain.FIQH or claim.claim_type == ClaimType.FIQH_RULING:
        sources.append(_source(EvidenceProvider.DORAR_FEQHIA, RetrievalPurpose.FIQH_RETRIEVAL, 1))
    elif claim.domain == Domain.AQEEDAH or claim.claim_type == ClaimType.AQEEDAH:
        sources.append(_source(EvidenceProvider.DORAR_AQEEDA,
                               RetrievalPurpose.AQEEDAH_RETRIEVAL, 1))
    elif claim.domain in {Domain.HISTORY, Domain.SEERAH} or claim.claim_type in {
        ClaimType.ISLAMIC_HISTORY, ClaimType.SEERAH,
    }:
        sources.append(_source(EvidenceProvider.DORAR_HISTORY,
                               RetrievalPurpose.HISTORY_RETRIEVAL, 1))
    elif claim.domain == Domain.GENERAL:
        sources.append(_source(EvidenceProvider.BAYAN,
                               RetrievalPurpose.ISLAMIC_LIBRARY_SEARCH, 1))

    tasks = []
    for index, source in enumerate(sources, 1):
        maximum = query_limits.get(source.provider, 2)
        queries = select_provider_queries(claim, source.provider, maximum)
        tasks.append(RetrievalTask(
            task_id=f"task_{index:03d}", claim_id=claim.id,
            target_attribute_ids=_target_ids(claim, source.provider),
            provider=source.provider, purpose=source.purpose,
            query=queries[0] if queries else None, queries=queries,
            max_results=result_limits.get(source.provider),
        ))
    return RetrievalPlan(claim_id=claim.id, sources=sources, tasks=tasks)
