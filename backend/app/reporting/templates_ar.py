from app.decision.models import ClaimDecisionStatus, DecisionReasonCode
from app.models.validation import AttributeValidationStatus

STATUS_SUMMARIES = {
    ClaimDecisionStatus.SUPPORTED: "تم العثور على أدلة تدعم جميع عناصر الادعاء التي تتطلب التحقق.",
    ClaimDecisionStatus.PARTIALLY_SUPPORTED: "تدعم الأدلة جزءًا من الادعاء، لكن بعض التفاصيل لم تُثبت بشكل كامل.",
    ClaimDecisionStatus.CONFLICTING: "توجد أدلة موثقة لا تتوافق مع جزء من الادعاء أو توجد نتائج متعارضة تتطلب الانتباه.",
    ClaimDecisionStatus.INSUFFICIENT_EVIDENCE: "لم تتوفر أدلة كافية للتحقق من جميع عناصر الادعاء.",
    ClaimDecisionStatus.REQUIRES_SPECIALIST: "لا يمكن إصدار نتيجة آلية موثوقة لهذه الحالة، ويوصى بمراجعتها من مختص.",
}

REASON_EXPLANATIONS = {
    DecisionReasonCode.ALL_REQUIRED_ATTRIBUTES_SUPPORTED: "جميع العناصر المطلوبة مدعومة بالأدلة التي تم التحقق منها.",
    DecisionReasonCode.PARTIAL_EVIDENCE: "الأدلة تدعم بعض عناصر الادعاء بشكل جزئي.",
    DecisionReasonCode.REQUIRED_EVIDENCE_MISSING: "لم يتم العثور على دليل كافٍ لأحد العناصر المطلوبة.",
    DecisionReasonCode.AMBIGUOUS_EVIDENCE: "الأدلة المتاحة لا تسمح بحسم أحد عناصر الادعاء.",
    DecisionReasonCode.EVIDENCE_CONFLICT: "توجد نتائج تحقق مختلفة بين عناصر الادعاء، أو تعارض موثق داخل أحد العناصر.",
    DecisionReasonCode.CLAIM_CONTRADICTED_BY_EVIDENCE: "الأدلة المتاحة لا تتوافق مع الادعاء في العنصر الذي تم التحقق منه.",
    DecisionReasonCode.VALIDATION_EXECUTION_FAILURE: "تعذر إكمال إحدى عمليات التحقق المطلوبة.",
    DecisionReasonCode.SPECIALIST_REVIEW_REQUIRED: "الحالة تتطلب مراجعة مختص وفق قواعد النظام.",
}

ATTRIBUTE_MESSAGES = {
    AttributeValidationStatus.SUPPORTED: "تم العثور على دليل يدعم هذه المعلومة.",
    AttributeValidationStatus.PARTIAL: "الدليل يدعم جزءًا من هذه المعلومة، لكنه لا يثبتها بالكامل.",
    AttributeValidationStatus.CONTRADICTED: "الدليل المتاح لا يتوافق مع هذه المعلومة.",
    AttributeValidationStatus.NOT_FOUND: "لم يتم العثور على دليل كافٍ للتحقق من هذه المعلومة.",
    AttributeValidationStatus.UNCERTAIN: "الأدلة المتاحة لا تسمح بحسم هذه المعلومة.",
}

STATUS_PRESENTATION = {
    ClaimDecisionStatus.SUPPORTED: ("مدعوم بالأدلة", "check"),
    ClaimDecisionStatus.PARTIALLY_SUPPORTED: ("مدعوم جزئيًا", "partial"),
    ClaimDecisionStatus.CONFLICTING: ("توجد نتائج متعارضة", "conflict"),
    ClaimDecisionStatus.INSUFFICIENT_EVIDENCE: ("الأدلة غير كافية", "question"),
    ClaimDecisionStatus.REQUIRES_SPECIALIST: ("يتطلب مراجعة مختص", "specialist"),
}

AUTHENTICITY_MISSING_NOTE = "عدم العثور على دليل كافٍ لإثبات حكم صحة الحديث لا يعني أن الحديث ضعيف أو غير صحيح."
SPECIALIST_NOTE = "تتطلب هذه الحالة مراجعة مختص قبل إصدار نتيجة نهائية."
EXECUTION_FAILURE_NOTE = "تعذر إكمال جزء من عملية التحقق آليًا."
