import re

from app.models.claim import AttributeType, Claim
from app.models.evidence import EvidenceProvider


def attribute_value(claim: Claim, kind: AttributeType) -> str | None:
    return next((item.value for item in claim.attributes if item.type == kind), None)


def select_queries(claim: Claim, maximum: int = 3) -> list[str]:
    text = (attribute_value(claim, AttributeType.QURAN_TEXT)
            or attribute_value(claim, AttributeType.HADITH_TEXT)
            or attribute_value(claim, AttributeType.TEXT))
    context_query = None
    if claim.subject_context:
        context = claim.subject_context
        subject = context.text or " ".join(filter(None, [context.surah, context.ayah_number]))
        if subject:
            kind = "تفسير معنى" if context.type.value == "QURAN" else "شرح معنى الحديث"
            context_query = f"{kind} {subject} {claim.normalized_claim}"
    candidates = [context_query, text, *claim.search_queries, claim.normalized_claim]
    selected = []
    for query in candidates:
        if not query:
            continue
        query = re.sub(r"\s+", " ", query).strip()
        if query not in selected:
            selected.append(query)
    return selected[:maximum]


def _deduplicate(candidates, maximum):
    selected, keys = [], set()
    for query in candidates:
        if not query:
            continue
        query = re.sub(r"\s+", " ", str(query)).strip()
        key = query.casefold()
        if not query or key in keys:
            continue
        keys.add(key)
        selected.append(query)
    return selected[:maximum]


def _attribute_values(claim, *types):
    wanted = set(types)
    return [item.value for item in claim.attributes
            if item.requires_evidence and item.type in wanted and item.value]


def select_provider_queries(claim: Claim, provider: EvidenceProvider,
                            maximum: int = 2) -> list[str]:
    """Select bounded identity-first queries without changing the claim's factual content."""
    if maximum < 1:
        return []
    hadith_providers = {
        EvidenceProvider.DORAR_HADITH, EvidenceProvider.HADEETHENC, EvidenceProvider.DORAR,
    }
    if provider in hadith_providers:
        context_text = (claim.subject_context.text
                        if claim.subject_context and claim.subject_context.type.value in {"HADITH", "ATHAR"}
                        else None)
        candidates = [*_attribute_values(claim, AttributeType.HADITH_TEXT, AttributeType.TEXT),
                      context_text, *claim.search_queries, claim.normalized_claim]
    elif provider == EvidenceProvider.DORAR_TAFSEER:
        context = claim.subject_context if claim.subject_context and claim.subject_context.type.value == "QURAN" else None
        identity = None
        if context:
            numbers = context.ayah_numbers or ([int(context.ayah_number)]
                if context.ayah_number and str(context.ayah_number).isdigit() else [])
            verse = (str(numbers[0]) if len(numbers) == 1 else
                     f"{numbers[0]}-{numbers[-1]}" if numbers else context.ayah_number)
            identity = " ".join(filter(None, [context.surah, verse, context.text]))
        interpretation = _attribute_values(claim, AttributeType.INTERPRETATION, AttributeType.OTHER)
        contextual = " ".join(filter(None, [identity, interpretation[0] if interpretation else claim.normalized_claim]))
        candidates = [contextual, *interpretation, *claim.search_queries, claim.normalized_claim]
    elif provider == EvidenceProvider.DORAR_FEQHIA:
        candidates = [claim.normalized_claim,
                      *_attribute_values(claim, AttributeType.RULING, AttributeType.TEXT, AttributeType.OTHER),
                      *claim.search_queries]
    elif provider == EvidenceProvider.DORAR_AQEEDA:
        candidates = [claim.normalized_claim,
                      *_attribute_values(claim, AttributeType.TEXT, AttributeType.OTHER),
                      *claim.search_queries]
    elif provider == EvidenceProvider.DORAR_HISTORY:
        topics = _attribute_values(claim, AttributeType.TEXT, AttributeType.OTHER)
        topic = topics[0] if topics else claim.normalized_claim
        additions = _attribute_values(claim, AttributeType.DATE, AttributeType.LOCATION)
        enriched = " ".join([topic, *[value for value in additions
                                      if value.casefold() not in topic.casefold()]])
        candidates = [enriched, claim.normalized_claim, *topics, *claim.search_queries]
    else:
        return select_queries(claim, maximum)
    return _deduplicate(candidates, maximum)


def quran_identifiers(claim: Claim) -> tuple[str | None, str | None]:
    surah = attribute_value(claim, AttributeType.SURAH)
    ayah = attribute_value(claim, AttributeType.AYAH_NUMBER)
    if claim.subject_context and claim.subject_context.type.value == "QURAN":
        surah = surah or claim.subject_context.surah
        ayah = ayah or claim.subject_context.ayah_number
    return surah, ayah


def quran_ayah_numbers(claim: Claim) -> list[int]:
    range_attribute = next((item for item in claim.attributes
                            if item.type == AttributeType.AYAH_RANGE), None)
    if range_attribute and range_attribute.ayah_numbers:
        return range_attribute.ayah_numbers
    if claim.subject_context and claim.subject_context.ayah_numbers:
        return claim.subject_context.ayah_numbers
    _, ayah = quran_identifiers(claim)
    return [int(ayah)] if ayah and str(ayah).isdigit() else []
