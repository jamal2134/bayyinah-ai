# Bayyinah AI — Hackathon Demo Guide

## Start the demo

From the `bayyinah-ai` directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The frontend is served by the backend; no separate frontend process is needed.

## Environment variables

Required for a live demo:

- `ANTHROPIC_API_KEY`

Depending on the account/environment:

- `ANTHROPIC_WORKSPACE_ID`
- `ANTHROPIC_MODEL`
- `ANTHROPIC_TIMEOUT_SECONDS`
- `ANTHROPIC_MAX_RETRIES`
- `HTTP_CONNECT_TIMEOUT`
- `HTTP_READ_TIMEOUT`
- `MAX_PROVIDER_QUERY_ATTEMPTS`
- `DORAR_HADITH_ENABLED`
- `DORAR_HADITH_EXPLANATION_ENABLED`
- `DORAR_TAFSEER_ENABLED`
- `DORAR_FEQHIA_ENABLED`
- `DORAR_AQEEDA_ENABLED`
- `DORAR_HISTORY_ENABLED`

Never display or paste secret values during the demo.

## DEMO_GOLDEN_CASE

> قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الإخلاص. وقال النبي ﷺ: «إنما الأعمال بالنيات»، رواه البخاري عن عمر بن الخطاب.

Audience cues:

1. The input is separated into Quran and Hadith claims.
2. Each claim is routed only to the appropriate specialist provider family.
3. Attribute results remain separate: text, reference, narrator, and source need not share one verdict.
4. Only cited evidence is visible, with its original text and stored source URL.
5. The final status comes from deterministic Phase 5 rules.

Allow roughly 45–90 seconds depending on model and provider latency.

## DEMO_ADVERSARIAL_CASE

> قال الله تعالى: ﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾، وهي الآية الأولى من سورة الفلق. وقال النبي ﷺ: «إنما الأعمال بالنيات»، ورواه أبو هريرة.

Expected conceptual behavior: the quoted text may be found while the claimed Quran reference or Hadith attribution can be contradicted independently. Do not promise an exact live label; provider availability and extraction wording may vary.

## Provider/network fallback

Use these modes honestly and label the active mode:

### A. LIVE DEMO

Use the running application with real AI and providers. If Dorar returns HTTP 403, point out the technical failure banner: it does not say the claim is false.

### B. SAVED VERIFIED DEMO

Open the previously generated real result:

- `evaluation/stage51_mixed_live_results.json`

Describe it as a saved result from a real run, with its recorded duration, providers, evidence, failures, and cost. Never call it a current live verification.

### C. OFFLINE CONTROLLED DEMO

Run:

```powershell
python evaluation/final_demo_acceptance.py
```

Open `evaluation/final_demo_acceptance.md`. Explain that providers/model responses are controlled fixtures while routing, conditional retrieval, alignment, Phase 4, Phase 5, and reporting are real application components.

If the external network is blocked, switch from A to B or C instead of fabricating a live result.

## Judge talking points

Bayyinah AI does not ask an LLM, “Is this Islamic statement true?”

1. AI extracts factual claims.
2. Deterministic routing selects specialist sources.
3. Evidence is retrieved.
4. Code checks evidence identity, attribution, and context alignment.
5. Attributes are validated against supplied evidence.
6. Deterministic Phase 5 rules produce the final status.
7. Every displayed support or contradiction links back to cited evidence.

Key principles:

- Similarity ≠ evidence.
- Retrieval ≠ verification.
- Absence ≠ contradiction.
- Provider failure ≠ a false claim.
- AI proposes; code enforces.

## Before presenting

```powershell
python -m pytest backend\tests -q -rs
node --check frontend\assets\app.js
```

Check `/health`, keep the saved verified result available, and confirm no terminal or browser panel displays secrets.
