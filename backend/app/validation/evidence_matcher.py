from enum import Enum
from difflib import SequenceMatcher

from app.models.claim import AttributeType, ClaimAttribute, Domain
from app.models.evidence import EvidenceCandidate, EvidenceType
from app.validation.normalization import integer, normalize, normalize_surah


class CandidateAlignment(str, Enum):
    ALIGNED = "ALIGNED"
    UNRELATED = "UNRELATED"
    UNRESOLVED = "UNRESOLVED"


class QuranRecordAlignment(str, Enum):
    ALIGNED = "ALIGNED"
    MISMATCH = "MISMATCH"
    UNRESOLVED = "UNRESOLVED"


def _meaningful_quran_partial(value: str) -> bool:
    """Reject generic fragments while allowing deterministic contiguous quotations."""
    tokens = value.split()
    return len(tokens) >= 3 and len(value.replace(" ", "")) >= 12


def _contiguous_token_passage(quote: str, canonical: str) -> bool:
    quote_tokens = quote.split()
    canonical_tokens = canonical.split()
    width = len(quote_tokens)
    return bool(width) and any(
        canonical_tokens[index:index + width] == quote_tokens
        for index in range(len(canonical_tokens) - width + 1)
    )


def quran_record_alignment(claim, candidate: EvidenceCandidate) -> tuple[QuranRecordAlignment, str]:
    """Establish exact Quran record identity; semantic similarity is intentionally excluded."""
    if claim.domain != Domain.QURAN or candidate.evidence_type != EvidenceType.QURAN_AYAH:
        return QuranRecordAlignment.UNRESOLVED, "The candidate is not Quran ayah evidence for this claim."
    claimed_surah = next((item.value for item in claim.attributes
                          if item.type == AttributeType.SURAH), None)
    claimed_ayahs = next((item.ayah_numbers for item in claim.attributes
                          if item.type == AttributeType.AYAH_RANGE), None)
    if not claimed_ayahs:
        claimed_ayah = next((integer(item.value) for item in claim.attributes
                             if item.type == AttributeType.AYAH_NUMBER), None)
        claimed_ayahs = [claimed_ayah] if claimed_ayah is not None else None
    actual_surah = candidate.raw_metadata.get("surah") or candidate.raw_metadata.get("surah_number")
    actual_ayahs = candidate.raw_metadata.get("ayah_numbers")
    if not actual_ayahs:
        actual_ayah = (candidate.raw_metadata.get("ayah")
                       or candidate.raw_metadata.get("ayah_number"))
        actual_ayahs = [integer(actual_ayah)] if integer(actual_ayah) is not None else None
    if claimed_surah is not None and actual_surah is not None:
        if normalize_surah(claimed_surah) != normalize_surah(str(actual_surah)):
            return QuranRecordAlignment.MISMATCH, "Retrieved Quran record has a different Surah identity."
    if claimed_ayahs and actual_ayahs and claimed_ayahs != actual_ayahs:
        return QuranRecordAlignment.MISMATCH, "Retrieved Quran record has a different ayah identity."
    claimed_parts = []
    for item in claim.attributes:
        value = normalize(item.value) if item.type == AttributeType.QURAN_TEXT else ""
        if value and value not in claimed_parts:
            claimed_parts.append(value)
    retrieved = normalize(candidate.text)
    if not claimed_parts or not retrieved:
        return QuranRecordAlignment.UNRESOLVED, "Claimed or retrieved Quran text is unavailable."
    # Extractors may represent a multi-ayah quotation as one QURAN_TEXT value or
    # as one value per ayah.  Both shapes describe the same ordered record.
    if retrieved in claimed_parts or " ".join(claimed_parts) == retrieved:
        return QuranRecordAlignment.ALIGNED, "Normalized Quran text matches the claimed reference record."
    if (len(claimed_parts) == 1 and _meaningful_quran_partial(claimed_parts[0])
            and _contiguous_token_passage(claimed_parts[0], retrieved)):
        return QuranRecordAlignment.ALIGNED, (
            "A meaningful normalized contiguous quotation occurs in the claimed Quran record."
        )
    if (len(claimed_parts) == 1
            and _contiguous_token_passage(claimed_parts[0], retrieved)):
        return QuranRecordAlignment.UNRESOLVED, (
            "The quoted fragment is too short or generic to establish Quran record identity."
        )
    return QuranRecordAlignment.MISMATCH, "Retrieved Quran text at the claimed reference differs from the quotation."


def aggregate_quran_alignment(claim, candidates) -> QuranRecordAlignment:
    alignments = [quran_record_alignment(claim, item)[0] for item in candidates]
    if QuranRecordAlignment.ALIGNED in alignments:
        return QuranRecordAlignment.ALIGNED
    if QuranRecordAlignment.MISMATCH in alignments:
        return QuranRecordAlignment.MISMATCH
    return QuranRecordAlignment.UNRESOLVED


DEPENDENT_RECORD_ATTRIBUTES = {
    AttributeType.NARRATOR, AttributeType.SOURCE, AttributeType.COLLECTION,
    AttributeType.AUTHENTICITY, AttributeType.SCHOLAR,
}


def align_hadith_texts(target_texts, evidence_text) -> tuple[CandidateAlignment, str]:
    """Pure deterministic identity comparison shared by validation and dependent retrieval."""
    target_texts = [normalize(value) for value in target_texts if normalize(value)]
    evidence_text = normalize(evidence_text)
    if not target_texts or not evidence_text:
        return CandidateAlignment.UNRESOLVED, "Target or candidate Hadith text is unavailable."
    if any(target in evidence_text or (
        evidence_text in target and len(evidence_text) / max(len(target), 1) >= 0.9
    ) for target in target_texts):
        return CandidateAlignment.ALIGNED, "Normalized hadith text identifies the candidate as the target record."
    if any(SequenceMatcher(None, target, evidence_text).ratio() >= 0.75 for target in target_texts):
        return CandidateAlignment.UNRESOLVED, "The candidate is truncated or too incomplete to establish record identity."
    return CandidateAlignment.UNRELATED, "The candidate text does not identify the target hadith record."


def hadith_record_alignment(claim, candidate: EvidenceCandidate, parent_claim=None) -> tuple[CandidateAlignment, str]:
    """Align a candidate to its parent hadith using explicit record-identifying text."""
    if claim.domain not in {Domain.HADITH, Domain.ATHAR}:
        return CandidateAlignment.UNRESOLVED, "Record alignment is not applicable to this claim domain."
    if candidate.evidence_type not in {EvidenceType.HADITH, EvidenceType.HADITH_JUDGMENT, EvidenceType.ATHAR}:
        return CandidateAlignment.UNRELATED, "The candidate is not a hadith or athar record."
    claims = [item for item in (parent_claim, claim) if item is not None]
    target_texts = [item.value for current in claims for item in current.attributes
                    if item.type in {AttributeType.TEXT, AttributeType.HADITH_TEXT}]
    if claim.subject_context and claim.subject_context.type in {Domain.HADITH, Domain.ATHAR}:
        target_texts.append(claim.subject_context.text)
    if not target_texts:
        return CandidateAlignment.UNRESOLVED, "The claim has no TEXT attribute or record identifier for alignment."
    return align_hadith_texts(target_texts, candidate.text)


TYPE_COMPATIBILITY = {
    AttributeType.SURAH: {EvidenceType.QURAN_AYAH, EvidenceType.QURAN_SURAH, EvidenceType.QURAN_TAFSIR},
    AttributeType.AYAH_NUMBER: {EvidenceType.QURAN_AYAH, EvidenceType.QURAN_TAFSIR},
    AttributeType.AYAH_RANGE: {EvidenceType.QURAN_AYAH, EvidenceType.QURAN_TAFSIR},
    AttributeType.VERSE_COUNT: {EvidenceType.QURAN_SURAH},
    AttributeType.REVELATION_PERIOD: {EvidenceType.QURAN_SURAH},
    AttributeType.NARRATOR: {EvidenceType.HADITH, EvidenceType.HADITH_JUDGMENT, EvidenceType.ATHAR},
    AttributeType.SOURCE: {EvidenceType.HADITH, EvidenceType.HADITH_JUDGMENT, EvidenceType.ATHAR, EvidenceType.LIBRARY_CONTENT},
    AttributeType.COLLECTION: {EvidenceType.HADITH, EvidenceType.HADITH_JUDGMENT, EvidenceType.ATHAR, EvidenceType.LIBRARY_CONTENT},
    AttributeType.AUTHENTICITY: {EvidenceType.HADITH_JUDGMENT, EvidenceType.HADITH, EvidenceType.ATHAR},
    AttributeType.SCHOLAR: {EvidenceType.HADITH_JUDGMENT, EvidenceType.ATHAR, EvidenceType.LIBRARY_CONTENT},
    AttributeType.TEXT: {
        EvidenceType.QURAN_AYAH, EvidenceType.HADITH, EvidenceType.ATHAR,
        EvidenceType.FIQH_CONTENT, EvidenceType.AQEEDA_CONTENT, EvidenceType.HISTORY_EVENT,
    },
    AttributeType.QURAN_TEXT: {EvidenceType.QURAN_AYAH},
    AttributeType.HADITH_TEXT: {EvidenceType.HADITH, EvidenceType.HADITH_JUDGMENT},
    # Ordinary ayah/hadith records are intentionally excluded: text existence is not commentary.
    AttributeType.INTERPRETATION: {
        EvidenceType.QURAN_TAFSIR, EvidenceType.LIBRARY_CONTENT,
        EvidenceType.HADITH_EXPLANATION, EvidenceType.TAFSEER_SECTION,
    },
    AttributeType.RULING: {EvidenceType.LIBRARY_CONTENT, EvidenceType.FIQH_CONTENT},
    AttributeType.DATE: {EvidenceType.HISTORY_EVENT},
    AttributeType.LOCATION: {EvidenceType.HISTORY_EVENT},
    AttributeType.OTHER: {
        EvidenceType.FIQH_CONTENT, EvidenceType.AQEEDA_CONTENT, EvidenceType.HISTORY_EVENT,
    },
}


CONTEXTUAL_EVIDENCE_TYPES = {
    EvidenceType.TAFSEER_SECTION, EvidenceType.FIQH_CONTENT,
    EvidenceType.AQEEDA_CONTENT, EvidenceType.HISTORY_EVENT,
}

GENERIC_TERMS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "to", "and",
    "claim", "ruling", "rule", "event", "history", "belief", "says", "said",
    "حكم", "قول", "قال", "في", "من", "على", "عن", "أن", "إن", "هو", "هي", "هذا", "هذه",
}


def _tokens(value):
    return {token for token in normalize(value).split()
            if len(token) >= 3 and token not in GENERIC_TERMS and not token.isdigit()}


def _claim_quran_identity(claim):
    surah = next((item.value for item in claim.attributes if item.type == AttributeType.SURAH), None)
    ayah = next((item.value for item in claim.attributes
                 if item.type in {AttributeType.AYAH_NUMBER, AttributeType.AYAH_RANGE}), None)
    if claim.subject_context and claim.subject_context.type == Domain.QURAN:
        surah = surah or claim.subject_context.surah
        ayah = ayah or claim.subject_context.ayah_number
        if not ayah and claim.subject_context.ayah_numbers:
            numbers = claim.subject_context.ayah_numbers
            ayah = str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}-{numbers[-1]}"
    return surah, ayah


def _number(value):
    if value is None:
        return None
    digits = "".join(character for character in str(value) if character.isdigit())
    return int(digits) if digits else None


def _topic_alignment(claim, attribute, candidate):
    haystack = " ".join(filter(None, [candidate.title, candidate.text]))
    if attribute.asserted_by and normalize(attribute.asserted_by) not in normalize(haystack):
        return CandidateAlignment.UNRESOLVED, "The evidence does not establish the claimed attribution."
    subjects = [claim.normalized_claim]
    subjects.extend(item.value for item in claim.attributes
                    if item.type in {AttributeType.TEXT, AttributeType.OTHER}
                    and item.id != attribute.id)
    subjects.extend(entity.name for entity in claim.entities)
    evidence_tokens = _tokens(haystack)
    overlaps = [len(_tokens(subject) & evidence_tokens) for subject in subjects if subject]
    if any(normalize(subject) and normalize(subject) in normalize(haystack) for subject in subjects):
        return CandidateAlignment.ALIGNED, "The evidence explicitly addresses the claimed subject."
    best = max(overlaps, default=0)
    if best >= 2:
        return CandidateAlignment.ALIGNED, "The title/content identifies the same scoped subject for semantic validation."
    if best == 1:
        return CandidateAlignment.UNRESOLVED, "The available subject identity is too weak to establish relevance."
    return CandidateAlignment.UNRELATED, "The evidence does not address the claimed subject."


def evidence_context_alignment(claim, attribute, candidate):
    """Gate new Dorar content before any attribute verdict is attempted."""
    if candidate.evidence_type == EvidenceType.TAFSEER_SECTION:
        if attribute.type != AttributeType.INTERPRETATION:
            return CandidateAlignment.UNRELATED, "Tafseer sections only validate interpretation attributes."
        claimed_surah, claimed_ayah = _claim_quran_identity(claim)
        evidence_surah = candidate.structured_fields.get("surah_id")
        evidence_ayah = candidate.structured_fields.get("page_id")
        claim_surah_number, claim_ayah_number = _number(claimed_surah), _number(claimed_ayah)
        if claim_surah_number is None or claim_ayah_number is None:
            return CandidateAlignment.UNRESOLVED, "Structured Quran parent identity is insufficient for Tafseer alignment."
        if evidence_surah is None or evidence_ayah is None:
            return CandidateAlignment.UNRESOLVED, "Tafseer evidence lacks comparable Surah or page identity."
        if claim_surah_number != _number(evidence_surah) or claim_ayah_number != _number(evidence_ayah):
            return CandidateAlignment.UNRELATED, "Tafseer provenance identifies a different Quran context."
        return CandidateAlignment.ALIGNED, "Tafseer provenance matches the structured Quran parent context."
    if candidate.evidence_type == EvidenceType.FIQH_CONTENT:
        if claim.domain != Domain.FIQH or attribute.type not in {
            AttributeType.RULING, AttributeType.TEXT, AttributeType.OTHER,
        }:
            return CandidateAlignment.UNRELATED, "The evidence is not compatible with this Fiqh attribute."
        return _topic_alignment(claim, attribute, candidate)
    if candidate.evidence_type == EvidenceType.AQEEDA_CONTENT:
        if claim.domain != Domain.AQEEDAH or attribute.type not in {
            AttributeType.TEXT, AttributeType.OTHER,
        }:
            return CandidateAlignment.UNRELATED, "The evidence is not compatible with this Aqeedah attribute."
        return _topic_alignment(claim, attribute, candidate)
    if candidate.evidence_type == EvidenceType.HISTORY_EVENT:
        if claim.domain not in {Domain.HISTORY, Domain.SEERAH} or attribute.type not in {
            AttributeType.DATE, AttributeType.LOCATION, AttributeType.TEXT, AttributeType.OTHER,
        }:
            return CandidateAlignment.UNRELATED, "The evidence is not compatible with this historical attribute."
        title = normalize(candidate.title)
        claim_text = normalize(claim.normalized_claim)
        explicit_events = [normalize(item.value) for item in claim.attributes
                           if item.type in {AttributeType.TEXT, AttributeType.OTHER}]
        if title and (title in claim_text or any(title in item or item in title
                                                 for item in explicit_events if item)):
            return CandidateAlignment.ALIGNED, "The event title identifies the claimed historical event."
        return _topic_alignment(claim, attribute, candidate)
    return CandidateAlignment.UNRESOLVED, "No additional provider context alignment is required."


def relevant_evidence(attribute: ClaimAttribute, candidates: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
    targeted = [item for item in candidates if attribute.id in item.target_attribute_ids]
    if targeted:
        return targeted
    # An explicit target list for other attributes excludes this candidate.
    untargeted = [item for item in candidates if not item.target_attribute_ids]
    allowed = TYPE_COMPATIBILITY.get(attribute.type)
    if allowed is None:
        return untargeted
    return [item for item in untargeted if item.evidence_type in allowed]
