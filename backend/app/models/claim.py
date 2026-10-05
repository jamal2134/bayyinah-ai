from enum import Enum
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


ARABIC_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def quran_ayah_numbers_from_text(text: str) -> list[int] | None:
    """Parse only explicit consecutive Quran references; never infer an unstated verse."""
    normalized = text.translate(ARABIC_DIGIT_TRANSLATION)
    if re.search(r"الآيتان\s+(?:الأولى|الاولى)\s+والثانية", normalized):
        return [1, 2]
    patterns = (
        r"الآيتان\s+(\d+)\s*و\s*(\d+)",
        r"الآيات\s+من\s+(\d+)\s+إلى\s+(\d+)",
        r"الآيات\s+(\d+)\s*[-–—]\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            start, end = map(int, match.groups())
            if 1 <= start <= end <= 286:
                return list(range(start, end + 1))
    return None


class ClaimType(str, Enum):
    QURAN_RECORD = "QURAN_RECORD"
    QURAN_REFERENCE = "QURAN_REFERENCE"
    QURAN_TEXT = "QURAN_TEXT"
    QURAN_TAFSIR = "QURAN_TAFSIR"
    QURAN_INTERPRETATION = "QURAN_INTERPRETATION"
    QURAN_TRANSLATION = "QURAN_TRANSLATION"
    QURAN_CONTEXT = "QURAN_CONTEXT"
    HADITH_TEXT = "HADITH_TEXT"
    HADITH_AUTHENTICITY = "HADITH_AUTHENTICITY"
    HADITH_MEANING = "HADITH_MEANING"
    HADITH_INTERPRETATION = "HADITH_INTERPRETATION"
    HADITH_ATTRIBUTION = "HADITH_ATTRIBUTION"
    HADITH_RECORD = "HADITH_RECORD"
    ATHAR_TEXT = "ATHAR_TEXT"
    ATHAR_ATTRIBUTION = "ATHAR_ATTRIBUTION"
    ATHAR_AUTHENTICITY = "ATHAR_AUTHENTICITY"
    ATHAR_RECORD = "ATHAR_RECORD"
    FIQH_RULING = "FIQH_RULING"
    AQEEDAH = "AQEEDAH"
    SEERAH = "SEERAH"
    ISLAMIC_HISTORY = "ISLAMIC_HISTORY"
    ISLAMIC_EDUCATION = "ISLAMIC_EDUCATION"
    GENERAL_ISLAMIC_CLAIM = "GENERAL_ISLAMIC_CLAIM"
    NON_VERIFIABLE = "NON_VERIFIABLE"
    OTHER = "OTHER"


class Domain(str, Enum):
    QURAN = "QURAN"
    HADITH = "HADITH"
    ATHAR = "ATHAR"
    FIQH = "FIQH"
    AQEEDAH = "AQEEDAH"
    SEERAH = "SEERAH"
    HISTORY = "HISTORY"
    GENERAL = "GENERAL"
    NON_ISLAMIC = "NON_ISLAMIC"


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)


class AttributeType(str, Enum):
    TEXT = "TEXT"
    QURAN_TEXT = "QURAN_TEXT"
    HADITH_TEXT = "HADITH_TEXT"
    INTERPRETATION = "INTERPRETATION"
    NARRATOR = "NARRATOR"
    SOURCE = "SOURCE"
    COLLECTION = "COLLECTION"
    AUTHENTICITY = "AUTHENTICITY"
    SURAH = "SURAH"
    AYAH_NUMBER = "AYAH_NUMBER"
    AYAH_RANGE = "AYAH_RANGE"
    VERSE_COUNT = "VERSE_COUNT"
    REVELATION_PERIOD = "REVELATION_PERIOD"
    SCHOLAR = "SCHOLAR"
    SCHOOL = "SCHOOL"
    RULING = "RULING"
    DATE = "DATE"
    LOCATION = "LOCATION"
    OTHER = "OTHER"


class ClaimRelationship(str, Enum):
    INTERPRETS = "INTERPRETS"
    EXPLAINS = "EXPLAINS"


class SubjectContext(BaseModel):
    """Retrieval context inherited from a parent, never evidence for this claim."""
    model_config = ConfigDict(extra="forbid")
    type: Domain
    surah: str | None = None
    ayah_number: str | None = None
    ayah_numbers: list[int] | None = None
    text: str | None = None


class ClaimAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, pattern=r"^attr_\d{3,}$")
    type: AttributeType
    value: str = Field(min_length=1)
    ayah_numbers: list[int] | None = None
    asserted_by: str | None = None
    qualifier: str | None = None
    requires_evidence: bool = True


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^claim_\d{3,}$")
    original_text: str = Field(min_length=1)
    normalized_claim: str = Field(min_length=1)
    claim_type: ClaimType
    domain: Domain
    search_queries: list[str] = Field(default_factory=list, max_length=3)
    entities: list[Entity] = Field(default_factory=list)
    attributes: list[ClaimAttribute] = Field(default_factory=list)
    parent_claim_id: str | None = Field(default=None, pattern=r"^claim_\d{3,}$")
    relationship: ClaimRelationship | None = None
    subject_context: SubjectContext | None = None
    normalization_warnings: list[str] = Field(default_factory=list)
    requires_evidence: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_query_policy(self):
        interpretation_types = {
            ClaimType.QURAN_INTERPRETATION, ClaimType.HADITH_INTERPRETATION,
        }
        if self.claim_type in interpretation_types:
            self.requires_evidence = True
            converted = []
            for attribute in self.attributes:
                if attribute.type == AttributeType.OTHER:
                    attribute = attribute.model_copy(update={
                        "type": AttributeType.INTERPRETATION, "requires_evidence": True,
                    })
                elif attribute.type == AttributeType.INTERPRETATION and not attribute.requires_evidence:
                    attribute = attribute.model_copy(update={"requires_evidence": True})
                converted.append(attribute)
            self.attributes = converted
            if not any(item.type == AttributeType.INTERPRETATION for item in self.attributes):
                self.attributes.append(ClaimAttribute(
                    type=AttributeType.INTERPRETATION,
                    value=self.normalized_claim,
                    requires_evidence=True,
                ))
        self.attributes = [attribute.model_copy(update={"id": attribute.id or f"attr_{index:03d}"})
                           for index, attribute in enumerate(self.attributes, 1)]
        normalized_attributes = []
        for attribute in self.attributes:
            numbers = attribute.ayah_numbers
            if attribute.type == AttributeType.AYAH_NUMBER:
                match = re.fullmatch(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", attribute.value)
                if match:
                    start, end = map(int, match.groups())
                    if 1 <= start <= end <= 286:
                        numbers = list(range(start, end + 1))
                        attribute = attribute.model_copy(update={
                            "type": AttributeType.AYAH_RANGE,
                            "value": f"{start}-{end}",
                            "ayah_numbers": numbers,
                        })
            if attribute.type == AttributeType.AYAH_RANGE:
                if not numbers:
                    match = re.fullmatch(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", attribute.value)
                    if match:
                        start, end = map(int, match.groups())
                        numbers = list(range(start, end + 1)) if start <= end else []
                if not numbers or len(numbers) < 2 or numbers != list(range(numbers[0], numbers[-1] + 1)):
                    raise ValueError("AYAH_RANGE requires two or more consecutive ayah_numbers")
                attribute = attribute.model_copy(update={
                    "value": f"{numbers[0]}-{numbers[-1]}", "ayah_numbers": numbers,
                })
            normalized_attributes.append(attribute)
        self.attributes = normalized_attributes
        explicit_range = quran_ayah_numbers_from_text(self.original_text) if self.domain == Domain.QURAN else None
        if explicit_range:
            self.attributes = [item for item in self.attributes
                               if item.type not in {AttributeType.AYAH_NUMBER, AttributeType.AYAH_RANGE}]
            self.attributes.append(ClaimAttribute(
                id=f"attr_{len(self.attributes) + 1:03d}", type=AttributeType.AYAH_RANGE,
                value=f"{explicit_range[0]}-{explicit_range[-1]}", ayah_numbers=explicit_range,
                requires_evidence=True,
            ))
        self.attributes = [item.model_copy(update={"id": f"attr_{index:03d}"})
                           for index, item in enumerate(self.attributes, 1)]
        repaired = []
        warnings = list(self.normalization_warnings)
        for attribute in self.attributes:
            if self.domain == Domain.QURAN and attribute.type == AttributeType.HADITH_TEXT:
                attribute = attribute.model_copy(update={"type": AttributeType.QURAN_TEXT})
                warnings.append("Normalized HADITH_TEXT to QURAN_TEXT because the claim is explicitly Quranic.")
            elif self.domain == Domain.HADITH and attribute.type == AttributeType.QURAN_TEXT:
                attribute = attribute.model_copy(update={"type": AttributeType.HADITH_TEXT})
                warnings.append("Normalized QURAN_TEXT to HADITH_TEXT because the claim is explicitly Hadith.")
            repaired.append(attribute)
        self.attributes = repaired
        self.normalization_warnings = list(dict.fromkeys(warnings))
        if (self.requires_evidence and not self.attributes
                and (self.domain == Domain.AQEEDAH or self.claim_type == ClaimType.AQEEDAH)):
            raise ValueError("evidence-requiring Aqeedah claims must contain at least one verifiable attribute")
        if bool(self.parent_claim_id) != bool(self.relationship):
            raise ValueError("parent_claim_id and relationship must be supplied together")
        if self.requires_evidence and not 1 <= len(self.search_queries) <= 3:
            raise ValueError("verifiable claims require 1-3 search queries")
        if not self.requires_evidence and self.search_queries:
            raise ValueError("non-verifiable content must not have search queries")
        if self.requires_evidence and any(len(query.split()) < 2 for query in self.search_queries):
            raise ValueError("search queries must include a subject and retrieval context")
        normalized = self.normalized_claim.strip(" .،,:;؛!?؟\"'«»")
        contextual_start = re.compile(
            r"^(?:و\s*)?(?:هو|هي|إنه|أنها|نسبه|رواه|أخرجه|قال إنه|في السنة)\b"
            r"|^(?:and\s+)?(?:it|he|she|they)\b"
            r"|^(?:was\s+)?(?:narrated|reported|attributed|recorded)\s+by\b",
            re.IGNORECASE,
        )
        if self.requires_evidence and (len(normalized.split()) == 1 or contextual_start.search(normalized)):
            raise ValueError("claim must be self-contained; merge the fragment with its subject")
        return self


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_language: str = Field(pattern=r"^(ar|en|mixed|other)$")
    claim_count: int = Field(ge=0)
    claims: list[Claim]

    @model_validator(mode="after")
    def count_matches(self):
        if self.claim_count != len(self.claims):
            raise ValueError("claim_count must equal the number of claims")
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim ids must be unique")
        known = set(ids)
        for claim in self.claims:
            if claim.parent_claim_id and claim.parent_claim_id not in known:
                raise ValueError("parent_claim_id must reference a claim in the same extraction")
            if claim.parent_claim_id == claim.id:
                raise ValueError("a claim cannot be its own parent")
        return self


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50_000)

