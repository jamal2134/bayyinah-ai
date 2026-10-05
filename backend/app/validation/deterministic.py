from dataclasses import dataclass, field
import re

from app.models.claim import AttributeType, ClaimAttribute
from app.models.evidence import EvidenceCandidate
from app.models.validation import AttributeValidationStatus
from app.validation.normalization import (
    SOURCE_ALIASES, compound_parts, integer, normalize, normalize_source, normalize_surah,
)


@dataclass
class CandidateDecision:
    status: AttributeValidationStatus
    rationale: str
    fields: list[str] = field(default_factory=list)


def _values(candidate: EvidenceCandidate, attribute_type: AttributeType):
    raw = candidate.raw_metadata
    if attribute_type == AttributeType.SURAH:
        values = [raw.get("surah"), raw.get("surah_number")]
        if candidate.reference and ":" in candidate.reference:
            values.append(candidate.reference.split(":", 1)[0].replace("surah", ""))
        return values, ["raw_metadata.surah", "raw_metadata.surah_number", "reference"]
    if attribute_type == AttributeType.AYAH_NUMBER:
        values = [raw.get("ayah"), raw.get("ayah_number")]
        if candidate.reference and ":" in candidate.reference:
            values.append(candidate.reference.rsplit(":", 1)[-1])
        return values, ["raw_metadata.ayah", "raw_metadata.ayah_number", "reference"]
    if attribute_type == AttributeType.AYAH_RANGE:
        return [raw.get("ayah_numbers")], ["raw_metadata.ayah_numbers"]
    if attribute_type == AttributeType.VERSE_COUNT:
        values = [raw.get("verse_count")]
        for row in raw.get("ayahs_count", []) if isinstance(raw.get("ayahs_count"), list) else []:
            values.append(row.get("value") if isinstance(row, dict) else row)
        return values, ["raw_metadata.verse_count", "raw_metadata.ayahs_count"]
    if attribute_type == AttributeType.REVELATION_PERIOD:
        return [raw.get("revelation_period"), raw.get("surah_type")], ["raw_metadata.revelation_period", "raw_metadata.surah_type"]
    if attribute_type == AttributeType.NARRATOR:
        # Provider "attribution" commonly names a collection, not the narrator.
        return [candidate.narrator, raw.get("narrator")], ["narrator", "raw_metadata.narrator"]
    if attribute_type in {AttributeType.SOURCE, AttributeType.COLLECTION}:
        # Provider/aggregator identity is intentionally excluded.
        return [candidate.reference, raw.get("source"), raw.get("collection"), raw.get("book")], ["reference", "raw_metadata.source", "raw_metadata.collection", "raw_metadata.book"]
    if attribute_type == AttributeType.AUTHENTICITY:
        return [candidate.judgment, raw.get("grade"), raw.get("judgment")], ["judgment", "raw_metadata.grade", "raw_metadata.judgment"]
    if attribute_type == AttributeType.SCHOLAR:
        return [candidate.scholar, candidate.author, raw.get("scholar")], ["scholar", "author", "raw_metadata.scholar"]
    if attribute_type == AttributeType.DATE and candidate.evidence_type.value == "HISTORY_EVENT":
        return [candidate.structured_fields.get("hijri_year"),
                candidate.structured_fields.get("gregorian_year")], [
                    "structured_fields.hijri_year", "structured_fields.gregorian_year"]
    if attribute_type in {AttributeType.TEXT, AttributeType.QURAN_TEXT, AttributeType.HADITH_TEXT}:
        return [candidate.text], ["text"]
    return [], []


def _compare_text(claimed: str, actual: str, attribute_type: AttributeType):
    converter = normalize_source if attribute_type in {AttributeType.SOURCE, AttributeType.COLLECTION} else normalize_surah if attribute_type == AttributeType.SURAH else normalize
    wanted, found = converter(claimed), converter(actual)
    if not wanted or not found:
        return None
    if wanted == found:
        return AttributeValidationStatus.SUPPORTED
    if attribute_type in {AttributeType.SOURCE, AttributeType.COLLECTION}:
        actual_text = normalize(actual)
        aliases = [normalize(alias) for alias, canonical in SOURCE_ALIASES.items()
                   if canonical == wanted]
        if wanted in found or any(alias and alias in actual_text for alias in aliases):
            return AttributeValidationStatus.SUPPORTED
    if attribute_type in {AttributeType.TEXT, AttributeType.QURAN_TEXT, AttributeType.HADITH_TEXT}:
        if wanted in found or found in wanted:
            return AttributeValidationStatus.SUPPORTED
        return None  # different text may be a different retrieved record, not a contradiction
    parts = compound_parts(claimed)
    if len(parts) > 1:
        matched = sum(converter(part) == found or converter(part) in found for part in parts)
        if 0 < matched < len(parts):
            return AttributeValidationStatus.PARTIAL
    return AttributeValidationStatus.CONTRADICTED


def grade_category(value: object) -> str:
    """Classify only explicit, deterministic Hadith grade language."""
    text = normalize(value)
    if not text:
        return "UNKNOWN"
    negative_patterns = (
        r"(?:^| )لا يصح(?: |$)", r"(?:^| )ليس بصحيح(?: |$)",
        r"(?:^| )ضعيف(?: |$)", r"(?:^| )موضوع(?: |$)",
        r"(?:^| )منكر(?: |$)", r"(?:^| )وهم(?: |$)",
    )
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return "NEGATIVE"
    if re.search(r"(?:^| )(?:صحيح|صحيحة)(?: |$)", text):
        return "POSITIVE_STRONG"
    if re.search(r"(?:^| )حسن(?: |$)", text):
        return "POSITIVE_ACCEPTABLE"
    if (re.search(r"(?:^| )غريب(?: |$)", text)
            or text in {"لا اعرفه", "فيه نظر"}):
        return "MIXED_OR_QUALIFIED"
    return "UNKNOWN"


def _compare_authenticity(claimed: str, actual: str):
    wanted_text, found_text = normalize(claimed), normalize(actual)
    if wanted_text == found_text:
        return AttributeValidationStatus.SUPPORTED
    wanted, found = grade_category(claimed), grade_category(actual)
    if "UNKNOWN" in {wanted, found} or "MIXED_OR_QUALIFIED" in {wanted, found}:
        return None
    if wanted == found == "POSITIVE_STRONG":
        return AttributeValidationStatus.SUPPORTED
    if wanted == "POSITIVE_STRONG" and found == "POSITIVE_ACCEPTABLE":
        return AttributeValidationStatus.PARTIAL
    if ((wanted in {"POSITIVE_STRONG", "POSITIVE_ACCEPTABLE"} and found == "NEGATIVE")
            or (wanted == "NEGATIVE" and found in {"POSITIVE_STRONG", "POSITIVE_ACCEPTABLE"})):
        return AttributeValidationStatus.CONTRADICTED
    return None


def validate_candidate(attribute: ClaimAttribute, candidate: EvidenceCandidate) -> CandidateDecision | None:
    if attribute.type == AttributeType.DATE and candidate.evidence_type.value == "HISTORY_EVENT":
        claimed_text = attribute.value.casefold()
        hijri = bool(re.search(r"(?:هجري|هجرية|هـ|\bah\b)", claimed_text))
        gregorian = bool(re.search(r"(?:ميلادي|ميلادية|\b(?:ad|ce)\b|(?:^|\s)م(?:\s|$))", claimed_text))
        if hijri == gregorian:
            return CandidateDecision(
                AttributeValidationStatus.UNCERTAIN,
                "The claimed date does not identify one safely comparable calendar.",
                ["claimed_value"])
        field_name = "hijri_year" if hijri else "gregorian_year"
        actual = candidate.structured_fields.get(field_name)
        claimed_year, actual_year = integer(attribute.value), integer(actual)
        if claimed_year is None or actual_year is None:
            return CandidateDecision(
                AttributeValidationStatus.UNCERTAIN,
                f"The {field_name} values are not safely comparable.",
                [f"structured_fields.{field_name}"])
        status = (AttributeValidationStatus.SUPPORTED if claimed_year == actual_year
                  else AttributeValidationStatus.CONTRADICTED)
        return CandidateDecision(
            status,
            "The aligned historical event has the same structured year."
            if status == AttributeValidationStatus.SUPPORTED else
            "The aligned historical event has a different structured year in the same calendar.",
            [f"structured_fields.{field_name}"])
    if attribute.type == AttributeType.QURAN_TEXT:
        verse_texts = candidate.raw_metadata.get("ayah_texts")
        if isinstance(verse_texts, list) and len(verse_texts) > 1:
            claimed = normalize(attribute.value)
            positions = [claimed.find(normalize(text)) for text in verse_texts]
            matches = sum(position >= 0 for position in positions)
            if matches == len(verse_texts) and positions == sorted(positions):
                return CandidateDecision(AttributeValidationStatus.SUPPORTED,
                                         "The quotation contains every requested ayah in canonical order.",
                                         ["raw_metadata.ayah_texts"])
            if matches:
                return CandidateDecision(AttributeValidationStatus.PARTIAL,
                                         "The quotation matches only part of the requested ayah range.",
                                         ["raw_metadata.ayah_texts"])
    values, fields = _values(candidate, attribute.type)
    usable = [value for value in values if value is not None and str(value).strip()]
    if not usable:
        if attribute.type == AttributeType.AUTHENTICITY:
            return CandidateDecision(AttributeValidationStatus.NOT_FOUND, "The evidence does not contain an explicit authenticity judgment.", fields)
        return None

    if attribute.type == AttributeType.AYAH_RANGE:
        wanted = attribute.ayah_numbers or []
        actual = next((value for value in values if isinstance(value, list)), None)
        if actual is None:
            return None
        status = (AttributeValidationStatus.SUPPORTED if wanted == actual
                  else AttributeValidationStatus.CONTRADICTED)
        return CandidateDecision(status,
            "Structured evidence explicitly matches the claimed ayah range."
            if status == AttributeValidationStatus.SUPPORTED else
            "Structured evidence explicitly gives a different ayah range.", fields)
    numeric = attribute.type in {AttributeType.AYAH_NUMBER, AttributeType.VERSE_COUNT}
    statuses = []
    for actual in usable:
        if numeric:
            claimed_number, actual_number = integer(attribute.value), integer(actual)
            if claimed_number is not None and actual_number is not None:
                statuses.append(AttributeValidationStatus.SUPPORTED if claimed_number == actual_number else AttributeValidationStatus.CONTRADICTED)
        else:
            status = (_compare_authenticity(attribute.value, str(actual))
                      if attribute.type == AttributeType.AUTHENTICITY
                      else _compare_text(attribute.value, str(actual), attribute.type))
            if status:
                statuses.append(status)
    if not statuses:
        return None

    # Attribution must be established separately from agreement with the value.
    if attribute.asserted_by and AttributeValidationStatus.SUPPORTED in statuses:
        provenance = [candidate.scholar, candidate.author, candidate.raw_metadata.get("scholar"), candidate.raw_metadata.get("author")]
        if not any(normalize(attribute.asserted_by) == normalize(item) for item in provenance if item):
            return CandidateDecision(AttributeValidationStatus.UNCERTAIN, "The value appears in the evidence, but the claimed attribution is not established.", fields + ["scholar", "author"])

    if AttributeValidationStatus.SUPPORTED in statuses:
        status = AttributeValidationStatus.SUPPORTED
        rationale = "Structured evidence explicitly matches the claimed attribute value."
    elif AttributeValidationStatus.PARTIAL in statuses:
        status = AttributeValidationStatus.PARTIAL
        rationale = "Structured evidence establishes only part of the compound claimed value."
    elif len(set(statuses)) > 1:
        status = AttributeValidationStatus.UNCERTAIN
        rationale = "Structured fields within this evidence are inconsistent."
    else:
        status = statuses[0]
        rationale = "Structured evidence explicitly gives an incompatible value."
    return CandidateDecision(status, rationale, fields)
