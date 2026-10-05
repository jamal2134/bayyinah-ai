from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceProvider(str, Enum):
    QURANPEDIA = "QURANPEDIA"
    HADEETHENC = "HADEETHENC"
    DORAR = "DORAR"
    DORAR_HADITH = "DORAR_HADITH"
    DORAR_HADITH_EXPLANATION = "DORAR_HADITH_EXPLANATION"
    DORAR_TAFSEER = "DORAR_TAFSEER"
    DORAR_FEQHIA = "DORAR_FEQHIA"
    DORAR_AQEEDA = "DORAR_AQEEDA"
    DORAR_HISTORY = "DORAR_HISTORY"
    BAYAN = "BAYAN"


class EvidenceType(str, Enum):
    QURAN_AYAH = "QURAN_AYAH"
    QURAN_SURAH = "QURAN_SURAH"
    QURAN_TAFSIR = "QURAN_TAFSIR"
    HADITH = "HADITH"
    HADITH_JUDGMENT = "HADITH_JUDGMENT"
    ATHAR = "ATHAR"
    LIBRARY_CONTENT = "LIBRARY_CONTENT"
    HADITH_EXPLANATION = "HADITH_EXPLANATION"
    TAFSEER_SECTION = "TAFSEER_SECTION"
    FIQH_CONTENT = "FIQH_CONTENT"
    AQEEDA_CONTENT = "AQEEDA_CONTENT"
    HISTORY_EVENT = "HISTORY_EVENT"


class EvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    claim_id: str
    target_attribute_ids: list[str] = Field(default_factory=list)
    provider: EvidenceProvider
    evidence_type: EvidenceType
    query_used: str | None = None
    title: str | None = None
    text: str = Field(min_length=1)
    source_name: str | None = None
    author: str | None = None
    reference: str | None = None
    page: str | None = None
    narrator: str | None = None
    scholar: str | None = None
    judgment: str | None = None
    language: str | None = None
    provider_record_id: str | None = None
    source_url: str | None = None
    provider_score: float | None = None
    provider_score_type: str | None = None
    result_rank: int | None = Field(default=None, ge=1)
    retrieved_at: datetime
    parent_evidence_id: str | None = None
    fragment_id: str | None = None
    fragment_label: str | None = None
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

