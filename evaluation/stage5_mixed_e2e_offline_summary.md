# Stage 5 Mixed E2E Evaluation

INPUT → CLAIMS → ROUTES → EVIDENCE → VALIDATION → FINAL DECISIONS

## mixed_valid

| Claim | Providers | Evidence used | Attribute results | Final status |
|---|---|---|---|---|
| الله لا إله إلا هو الحي القيوم من البقرة 255 | QURANPEDIA | quran:2:255 | SUPPORTED, SUPPORTED, SUPPORTED | SUPPORTED |
| تفسير آية الكرسي أن الله كامل الحياة والقيومية | DORAR_TAFSEER, QURANPEDIA | tafseer:2:255:1 | SUPPORTED | SUPPORTED |
| حديث إنما الأعمال بالنيات رواه عمر بن الخطاب | HADEETHENC, DORAR_HADITH | dorar-hadith:1, hadeethenc:1 | SUPPORTED, SUPPORTED | SUPPORTED |
| شرح حديث إنما الأعمال بالنيات أن صلاح العمل مرتبط بالنية | DORAR_HADITH | hadith-explanation:exp-1 | SUPPORTED | SUPPORTED |
| صلاة الوتر سنة مؤكدة | DORAR_FEQHIA | fiqh:1 | SUPPORTED | SUPPORTED |
| الله متصف بالعلم | DORAR_AQEEDA | aqeeda:1 | SUPPORTED | SUPPORTED |
| صلح الحديبية سنة 6 هـ | DORAR_HISTORY | history:1 | SUPPORTED | SUPPORTED |

## mixed_adversarial

| Claim | Providers | Evidence used | Attribute results | Final status |
|---|---|---|---|---|
| آية الكرسي من آل عمران 7 | QURANPEDIA | quran:2:255 | CONTRADICTED, CONTRADICTED, CONTRADICTED | CONFLICTING |
| تفسير آية الكرسي ينفي القيومية | DORAR_TAFSEER, QURANPEDIA | — | NOT_FOUND | INSUFFICIENT_EVIDENCE |
| حديث إنما الأعمال بالنيات رواه أبو هريرة | HADEETHENC, DORAR_HADITH | dorar-hadith:1, hadeethenc:1 | SUPPORTED, CONTRADICTED | CONFLICTING |
| شرح حديث إنما الأعمال بالنيات أن النية لا أثر لها | DORAR_HADITH | hadith-explanation:exp-1 | CONTRADICTED | CONFLICTING |
| الشافعية يقولون الوتر فرض | DORAR_FEQHIA | — | UNCERTAIN | INSUFFICIENT_EVIDENCE |
| أهل السنة ينفون علم الله | DORAR_AQEEDA | aqeeda:1 | CONTRADICTED | CONFLICTING |
| صلح الحديبية سنة 9 هـ | DORAR_HISTORY | history:1 | CONTRADICTED | CONFLICTING |

## partial_insufficient

| Claim | Providers | Evidence used | Attribute results | Final status |
|---|---|---|---|---|
| تفسير آية غير محددة | DORAR_TAFSEER, QURANPEDIA | — | NOT_FOUND | INSUFFICIENT_EVIDENCE |
| قول الوتر منسوب إلى عالم غير مذكور | DORAR_FEQHIA | — | UNCERTAIN | INSUFFICIENT_EVIDENCE |
| مكان صلح الحديبية داخل مكة | DORAR_HISTORY | — | NOT_FOUND | INSUFFICIENT_EVIDENCE |

## provider_failure_isolation

| Claim | Providers | Evidence used | Attribute results | Final status |
|---|---|---|---|---|
| الله لا إله إلا هو الحي القيوم من البقرة 255 | QURANPEDIA | quran:2:255 | SUPPORTED, SUPPORTED, SUPPORTED | SUPPORTED |
| تفسير آية الكرسي أن الله كامل الحياة والقيومية | DORAR_TAFSEER, QURANPEDIA | tafseer:2:255:1 | SUPPORTED | SUPPORTED |
| حديث إنما الأعمال بالنيات رواه عمر بن الخطاب | HADEETHENC, DORAR_HADITH | dorar-hadith:1, hadeethenc:1 | SUPPORTED, SUPPORTED | SUPPORTED |
| شرح حديث إنما الأعمال بالنيات أن صلاح العمل مرتبط بالنية | DORAR_HADITH | hadith-explanation:exp-1 | SUPPORTED | SUPPORTED |
| صلاة الوتر سنة مؤكدة | DORAR_FEQHIA | — |  | REQUIRES_SPECIALIST |
| الله متصف بالعلم | DORAR_AQEEDA | aqeeda:1 | SUPPORTED | SUPPORTED |
| صلح الحديبية سنة 6 هـ | DORAR_HISTORY | history:1 | SUPPORTED | SUPPORTED |

## Metrics

- unsupported_inference_count: 0
- total_support_or_contradiction_decisions: 33
- unsupported_inference_rate: 0.0
- validated_decisions_with_evidence_ids: 33
- total_evidence_based_decisions: 33
- evidence_traceability: 1.0
- routing_precision: 1.0
- unauthorized_explanation_calls: 0
