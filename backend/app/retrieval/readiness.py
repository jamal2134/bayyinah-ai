import re

from app.models.claim import AttributeType, Claim, ClaimType, Domain


UNRESOLVED_HADITH = re.compile(r"(?:هذا|هذه)\s+(?:الحديث|الرواية|الأثر|القول)")


def assess_retrieval_readiness(claim: Claim, parent_claim: Claim | None = None) -> tuple[bool, list[str], str | None]:
    """Return whether provider execution is safe, required missing context, and reason."""
    types = {attribute.type for attribute in claim.attributes}
    missing = []
    if claim.domain == Domain.QURAN and claim.claim_type in {
        ClaimType.QURAN_TAFSIR, ClaimType.QURAN_INTERPRETATION,
    }:
        context = claim.subject_context
        if AttributeType.SURAH not in types and not (context and context.surah):
            missing.append("SURAH")
        if (AttributeType.AYAH_NUMBER not in types and AttributeType.AYAH_RANGE not in types
                and not (context and (context.ayah_number or context.ayah_numbers))):
            missing.append("AYAH_NUMBER")
        if missing:
            return False, missing, "The referenced Quran verse cannot be uniquely identified."
    if claim.domain in {Domain.HADITH, Domain.ATHAR}:
        has_text = bool(types & {AttributeType.TEXT, AttributeType.HADITH_TEXT}) or bool(
            claim.subject_context and claim.subject_context.text)
        if parent_claim:
            has_text = has_text or any(item.type in {AttributeType.TEXT, AttributeType.HADITH_TEXT}
                                       and item.value for item in parent_claim.attributes)
        if claim.claim_type in {ClaimType.HADITH_MEANING, ClaimType.HADITH_INTERPRETATION} and not has_text:
            return False, ["HADITH_TEXT"], "The interpreted hadith cannot be uniquely identified."
        if not has_text and UNRESOLVED_HADITH.search(claim.normalized_claim):
            return False, ["HADITH_TEXT"], "The referenced hadith cannot be uniquely identified."
    return True, [], None
