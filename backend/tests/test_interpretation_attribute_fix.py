import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.decision.engine import decide_claim
from app.decision.models import ClaimDecisionRequest
from app.models.claim import Claim
from app.models.evidence import EvidenceCandidate
from app.reporting.builder import build_verification_report
from app.retrieval.service import RetrievalService
from app.validation.service import EvidenceValidationService


def interpretation(kind):
    quran = kind == "QURAN"
    return Claim.model_validate({
        "id": "claim_002",
        "original_text": "وتدل الآية على توحيد الله" if quran else "ومن معاني الحديث أن العمل يرتبط بالنية",
        "normalized_claim": "تدل الآية على توحيد الله" if quran else "قيمة العمل ترتبط بالنية",
        "claim_type": "QURAN_INTERPRETATION" if quran else "HADITH_INTERPRETATION",
        "domain": kind,
        "search_queries": ["تفسير سورة البقرة الآية 255"] if quran else ["شرح حديث إنما الأعمال بالنيات"],
        "entities": [],
        "attributes": [],
        "parent_claim_id": "claim_001",
        "relationship": "INTERPRETS",
        "subject_context": ({"type": "QURAN", "surah": "البقرة", "ayah_number": "255",
                             "text": "الله لا إله إلا هو الحي القيوم"} if quran else
                            {"type": "HADITH", "text": "إنما الأعمال بالنيات"}),
        "requires_evidence": True,
        "reason": "Interpretive assertion.",
    })


@pytest.mark.parametrize("kind", ["QURAN", "HADITH"])
def test_schema_guarantees_required_interpretation_attribute(kind):
    claim = interpretation(kind)
    assert len(claim.attributes) == 1
    assert claim.attributes[0].type.value == "INTERPRETATION"
    assert claim.attributes[0].requires_evidence is True
    assert claim.attributes[0].value == claim.normalized_claim


@pytest.mark.parametrize("kind,warning", [
    ("QURAN", "مصادر مناسبة للتحقق من هذا النوع من التفسير"),
    ("HADITH", "مصادر مناسبة للتحقق من هذا النوع من الشرح"),
])
def test_no_provider_produces_not_found_insufficient_evidence_and_user_warning(kind, warning):
    claim = interpretation(kind)
    retrieval = asyncio.run(RetrievalService({}).retrieve(
        claim, parent_quran_alignment="ALIGNED" if kind == "QURAN" else None))
    validation = EvidenceValidationService().validate(claim, [], retrieval)
    decision = decide_claim(ClaimDecisionRequest(claim=claim, validation=validation))
    report = build_verification_report(claim, [], validation, decision)
    assert retrieval.reason == "NO_SUITABLE_INTERPRETATION_PROVIDER"
    assert [item.status.value for item in validation.validations] == ["NOT_FOUND"]
    assert decision.decision.value == "INSUFFICIENT_EVIDENCE"
    assert report.attributes[0].attribute_type.value == "INTERPRETATION"
    assert warning in report.warnings[0]
    assert "Claim has no evidence-requiring attributes." not in str(report.model_dump())


def test_frontend_has_arabic_interpretation_and_relationship_labels_without_raw_reason():
    script = (Path(__file__).parents[2] / "frontend" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "INTERPRETATION:'المعنى'" in script
    assert "تفسير مرتبط بالآية السابقة" in script
    assert "شرح مرتبط بالحديث السابق" in script
    assert "NO_SUITABLE_INTERPRETATION_PROVIDER" not in script
    assert "Claim has no evidence-requiring attributes." not in script


@pytest.mark.parametrize("kind,evidence_type,provider", [
    ("QURAN", "QURAN_AYAH", "QURANPEDIA"),
    ("HADITH", "HADITH", "HADEETHENC"),
])
def test_parent_record_evidence_cannot_support_child_interpretation(kind, evidence_type, provider):
    claim = interpretation(kind)
    parent_record = EvidenceCandidate(
        evidence_id=f"parent:{kind.lower()}", claim_id=claim.id, provider=provider,
        evidence_type=evidence_type, text=claim.subject_context.text,
        retrieved_at=datetime.now(timezone.utc),
    )
    validation = EvidenceValidationService().validate(claim, [parent_record])
    result = validation.validations[0]
    assert result.status.value == "NOT_FOUND"
    assert result.supporting_evidence_ids == []
