# Bayyinah AI — Final Demo Acceptance

Generated: 2026-10-04T17:31:05.070503+00:00

## Scenarios

| Scenario | Mode | Claims | Decisions | Failures | Result |
|---|---|---:|---|---:|---|
| قرآن فقط | offline_controlled | 1 | SUPPORTED | 0 | PASS |
| حديث بنسبة راوٍ خاطئة | offline_controlled | 1 | CONFLICTING | 0 | PASS |
| قرآن وتفسير | offline_controlled | 2 | SUPPORTED, SUPPORTED | 0 | PASS |
| حديث وشرح غير صحيح | offline_controlled | 2 | CONFLICTING, CONFLICTING | 0 | PASS |
| فقه مع تعذر المصدر | offline_controlled | 1 | REQUIRES_SPECIALIST | 1 | PASS |
| عقيدة | offline_controlled | 1 | SUPPORTED | 0 | PASS |
| تاريخ بسنة خاطئة | offline_controlled | 1 | CONFLICTING | 0 | PASS |
| فقرة متعددة المجالات | offline_controlled | 7 | SUPPORTED, SUPPORTED, SUPPORTED, SUPPORTED, SUPPORTED, SUPPORTED, SUPPORTED | 0 | PASS |

## Safety metrics

- unsupported_inference_count: 0
- total_support_or_contradiction_decisions: 30
- unsupported_inference_rate: 0.0
- validated_decisions_with_evidence_ids: 30
- total_evidence_based_decisions: 30
- evidence_traceability: 1.0
- routing_precision: 1.0
- unauthorized_explanation_calls: 0
- cross_domain_evidence_leaks: 0
- visible_uncited_evidence: 0

## Demo cases

### DEMO_GOLDEN_CASE

قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الإخلاص. وقال النبي ﷺ: «إنما الأعمال بالنيات»، رواه البخاري عن عمر بن الخطاب.

### DEMO_ADVERSARIAL_CASE

قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الفلق. وقال النبي ﷺ: «إنما الأعمال بالنيات»، ورواه أبو هريرة.

## Live golden result

- Status: COMPLETED
- Claims: 2
- Duration: 19248.937 ms
- LLM calls: 4
- Provider calls: 7
- Cost USD: 0.107124
- Cost SAR: 0.40171500
- Extraction stable: True

## Acceptance environment

- Live adversarial case: not run; offline adversarial coverage passed.
- Browser automation: unavailable; RTL/static/API contract checks passed.
