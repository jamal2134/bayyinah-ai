# Bayyinah AI | بيّنة

Bayyinah is a traceable, AI-assisted verification system for Islamic content. It decomposes a text into independently verifiable claims, routes each claim to specialized knowledge sources, aligns retrieved candidates to the correct underlying record, validates individual attributes, preserves conflicts, and applies deterministic rules to produce an evidence-linked report.

> From information that appears correct to a result that can be evidenced and traced.

**Similarity ≠ evidence. Retrieval ≠ verification. AI proposes; code enforces.**

Bayyinah is an evidence-assisted research tool. It does not replace qualified scholars or authoritative religious institutions.

## Overview

A single paragraph can mix Quran quotations, Hadith text and grading, Tafsir, Fiqh, Aqeedah, Seerah, and Islamic-history assertions. Bayyinah treats these as separate claims because they may require different sources and may reach different outcomes.

```text
Input text
  → claim extraction and classification
  → source routing
  → evidence-candidate retrieval
  → record alignment
  → attribute validation
  → conflict detection
  → deterministic decision
  → traceable report
```

The Anthropic model is used for structured claim extraction and, when structured comparison is insufficient, closed-evidence semantic validation. Retrieval, alignment checks, deterministic comparisons, decision aggregation, and report assembly are implemented in code. Retrieved candidates are never promoted to proof merely because they are similar or highly ranked.

## The Problem

- One passage may contain several independent factual claims.
- Quran, Hadith, Tafsir, Fiqh, Aqeedah, Seerah, and history require different specialist sources.
- A similar result may refer to a different verse, narration, scholar, or record.
- One attribute may be supported while another—such as narrator, verse number, date, or grading—is wrong.
- No result, unavailable providers, or ambiguous evidence do not establish contradiction.

## The Solution

Bayyinah extracts atomic claims with explicit attributes, classifies their domains and types, and creates bounded source-specific searches. Provider responses become `EvidenceCandidate` objects that preserve their source text and provenance. The validator first checks that a candidate belongs to the relevant record, then evaluates only the attributes it can address. Supporting, contradicting, and unresolved relationships remain separate. A pure deterministic engine aggregates those validation results into the final status, and a deterministic report builder exposes the trace.

## Key Innovation

```text
Simple RAG: Search → similar result → LLM answer

Bayyinah:   Retrieve → record alignment → attribute validation
                    → conflict detection → deterministic decision
```

Provider rank, similarity, and successful retrieval describe discovery—not truth. The LLM can propose structured claims and classify a relationship to supplied evidence, but only code applies the final rule priority and selects the evidence shown in the report.

## How It Works

1. **Claim extraction.** The model splits submitted Arabic, English, or mixed text into self-contained claims, preserves original wording, normalizes each proposition, identifies attributes, and marks non-verifiable content. Long input is processed in bounded chunks and validated with strict Pydantic schemas.
2. **Classification and routing.** Each claim receives a controlled domain and claim type. Deterministic routing selects Quranpedia, HadeethEnc, a relevant Dorar collection, or Bayan according to that metadata.
3. **Evidence retrieval.** Provider adapters execute bounded queries and normalize results into `EvidenceCandidate` records. Candidates retain provider, text, query, rank, record ID, URL, retrieval time, structured fields, and available provenance metadata.
4. **Record alignment.** Candidate-to-claim checks prevent a semantically similar but different Quran or Hadith record from being used as evidence. Hadith explanations are fetched only after an eligible parent Hadith record aligns and exposes an explanation ID.
5. **Attribute validation.** Structured attributes such as surah, ayah number, narrator, source, scholar, and explicit judgment are compared deterministically where possible. Meaning, interpretation, context, and other semantic relationships can use Anthropic in closed-evidence mode; it may use only supplied candidate material.
6. **Conflict handling.** Supporting and contradicting evidence IDs are retained together. Missing evidence remains distinct from contradiction, and validation failures remain visible.
7. **Deterministic decision.** The decision engine reads structured validation output only—no provider calls, free-text interpretation, or model call. Its priority is specialist/execution conditions, explicit conflict, contradiction, missing or ambiguous evidence, partial support, then complete support.
8. **Traceable presentation.** Fixed Arabic templates build the report from the claim, decision, validation records, and only the evidence IDs referenced by validation. The frontend displays progress, results, sources, technical trace, and cost metadata without deriving its own verdict.

## Verification Statuses

Attribute validation and final claim decisions are deliberately separate.

| Layer | Status | Meaning |
|---|---|---|
| Attribute | `SUPPORTED` | Aligned evidence supports the asserted attribute. |
| Attribute | `PARTIAL` | Evidence establishes only part of the asserted attribute. |
| Attribute | `CONTRADICTED` | Aligned evidence explicitly contradicts the attribute. |
| Attribute | `NOT_FOUND` | No usable evidence was found for the attribute. |
| Attribute | `UNCERTAIN` | Available evidence does not resolve the relationship safely. |
| Final | `SUPPORTED` | Every required attribute is supported. |
| Final | `PARTIALLY_SUPPORTED` | A required attribute is only partially supported, with no higher-priority issue. |
| Final | `CONFLICTING` | Validated evidence conflicts internally or contradicts a required attribute. |
| Final | `INSUFFICIENT_EVIDENCE` | Required evidence is missing or ambiguous. |
| Final | `REQUIRES_SPECIALIST` | An upstream specialist marker is present or a required validation failed to execute safely. |

`REQUIRES_SPECIALIST` is an explicit abstention path: the system does not convert an execution failure or a case requiring expert judgment into a factual verdict.

Retrieval has operational statuses (`COMPLETED`, `PARTIAL`, `NO_RESULTS`, `MISSING_CONTEXT`, `NO_SUPPORTED_SOURCE`, `SOURCE_ERROR`, and `SKIPPED`). They report retrieval state only.

## Knowledge Sources

| Domain | Provider | Purpose | Official website |
|---|---|---|---|
| Quran | Quranpedia | Structured ayah, surah, and applicable Tafsir retrieval | [quranpedia.net](http://quranpedia.net/) |
| Hadith | HadeethEnc | Structured Hadith search and record details | [hadeethenc.com](https://hadeethenc.com/) |
| Hadith | Dorar Hadith | Hadith records, attribution, and explicit scholarly judgments | [dorar.net](https://dorar.net/) |
| Hadith explanation | Dorar Hadith Explanation | Explanation fetched through an aligned parent Hadith record | [dorar.net](https://dorar.net/) |
| Tafsir | Dorar Tafseer; Quranpedia where applicable | Tafsir sections linked to Quran records | [dorar.net](https://dorar.net/), [quranpedia.net](http://quranpedia.net/) |
| Fiqh | Dorar Feqhia | Fiqh material relevant to a ruling claim | [dorar.net](https://dorar.net/) |
| Aqeedah | Dorar Aqeedah | Aqeedah material relevant to the claim | [dorar.net](https://dorar.net/) |
| Seerah / history | Dorar History | Historical events and Seerah material | [dorar.net](https://dorar.net/) |
| General Islamic content | Bayan (`byenah.com`) | General Islamic library content | [byenah.com](https://www.byenah.com/) |

These are external services and websites. Availability, response format, rate limits, access controls, and network conditions can affect retrieval. Bayyinah is an independent project and is not presented as affiliated with or endorsed by these providers.

## Evidence and Traceability

Every normalized candidate can preserve the exact returned text, provider identity, source name and URL, provider record ID, reference, retrieval timestamp, query attempt, and raw/structured metadata. Validation links individual claim attributes to supporting and contradicting evidence IDs. The report includes only evidence that validation actually referenced, so unrelated search candidates are not displayed as proof. Conflicts are retained rather than averaged away or hidden.

Provider scores and ranks are not truth probabilities. Validator confidence—when present—describes confidence in the evidence-relationship classification, not the probability that a religious assertion is true.

## Trust and Safety Principles

- **Absence of evidence ≠ falsehood.** Missing or unavailable evidence produces an unresolved outcome, not contradiction.
- **Similarity ≠ evidence.** A related text must still align to the claimed record.
- **Retrieval ≠ verification.** Candidates pass alignment and attribute validation before influencing a decision.
- **Conflicting evidence is preserved.** Supporting and contradicting source links remain visible.
- **The system can abstain.** Ambiguous cases become `INSUFFICIENT_EVIDENCE`; execution failures or explicit expert-review cases become `REQUIRES_SPECIALIST`.
- **Bayyinah assists verification.** It does not replace qualified scholars or authoritative religious institutions.

## Architecture

```text
Browser (Arabic RTL HTML/CSS/JavaScript)
                 |
                 v
         FastAPI application
                 |
      VerificationOrchestrator
                 |
   +-------------+------------------------------+
   | Claim extraction (Anthropic + Pydantic)    |
   | Structured classification; deterministic   |
   |   source routing                            |
   | Async providers → EvidenceCandidate records|
   | Record alignment and attribute validation  |
   | Deterministic decision engine              |
   | Deterministic traceable report builder     |
   +-------------+------------------------------+
                 |
        In-memory request store
```

FastAPI serves the frontend and API from the same process and origin. Request progress and completed results are stored in a process-local dictionary.

## Technology Stack

- Python 3.10+
- FastAPI and Uvicorn
- Pydantic and pydantic-settings
- Anthropic Python SDK / Claude
- HTTPX, Requests, and Beautiful Soup
- Plain HTML, CSS, and JavaScript frontend
- pytest

## Repository Structure

```text
bayyinah-ai/
├── backend/
│   ├── app/
│   │   ├── agents/          # structured claim extraction
│   │   ├── api/             # FastAPI routes
│   │   ├── application/     # orchestration, progress, and cost tracking
│   │   ├── decision/        # deterministic final decision rules
│   │   ├── retrieval/       # routing, adapters, caching, and provider parsing
│   │   ├── reporting/       # deterministic traceable reports
│   │   ├── validation/      # alignment and attribute validation
│   │   └── main.py          # application entry point
│   └── tests/               # unit, contract, regression, and opt-in live tests
├── frontend/                # Arabic RTL single-page interface
├── evaluation/              # offline/live evaluation scripts and saved artifacts
├── .env.example             # safe configuration template
├── requirements.txt
└── pytest.ini
```

## Local Installation

```bash
git clone https://github.com/jamal2134/bayyinah-ai.git
cd bayyinah-ai
python -m venv .venv
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

```bash
# Linux/macOS
source .venv/bin/activate
cp .env.example .env
```

```bash
pip install -r requirements.txt
```

Set at least:

```dotenv
ANTHROPIC_API_KEY=your_key_here
```

`ANTHROPIC_WORKSPACE_ID` is optional and is sent as the `anthropic-workspace-id` header only when the configured key/workspace requires it.

## Running Locally

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

- Application: <http://localhost:8000>
- Health check: <http://localhost:8000/health>
- OpenAPI documentation: <http://localhost:8000/docs>

## API and Application Flow

The UI starts a job with `POST /api/v1/verify` using `{"text":"..."}`, receives HTTP 202 and a `verify_...` ID, then polls `GET /api/v1/verify/{request_id}` until the result is completed or failed.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Root health check |
| `GET` | `/api/v1/health` | API health check |
| `POST` | `/api/v1/verify` | Start the complete verification pipeline |
| `GET` | `/api/v1/verify/{request_id}` | Poll progress and retrieve the result |
| `POST` | `/api/v1/claims/extract` | Extract and classify claims |
| `POST` | `/api/v1/retrieval` | Retrieve candidates for a structured claim |
| `POST` | `/api/v1/verify/retrieve` | Extract and retrieve, stopping before validation |
| `POST` | `/api/v1/validation` | Align candidates and validate attributes |
| `POST` | `/api/v1/decisions` | Decide from a validation response |
| `POST` | `/api/v1/decisions/with-claim` | Decide while filtering non-evidentiary attributes |
| `POST` | `/api/v1/reports` | Build a report from structured phase outputs |

Detailed schemas are available from `/docs` while the server is running.

## Testing and Evaluation

```bash
python -m pytest backend/tests -q
```

Latest verified local regression run (October 6, 2026):

```text
338 collected
337 passed
1 skipped (opt-in live-provider test)
0 failed
```

These are software, contract, and acceptance tests—not a factual-accuracy percentage or scholarly benchmark. Unit/provider tests use mocks or controlled fixtures unless explicitly marked live.

```powershell
# Optional live provider test — Windows PowerShell
$env:RUN_LIVE_RETRIEVAL_TESTS = "1"
python -m pytest -m live backend/tests/test_live_retrieval.py -q
```

```bash
# Optional live provider test — Linux/macOS
RUN_LIVE_RETRIEVAL_TESTS=1 python -m pytest -m live backend/tests/test_live_retrieval.py -q
```

The repository also contains phase-specific and end-to-end scripts under `evaluation/`. The saved final controlled acceptance artifact records zero unsupported inferences, complete evidence-ID traceability, no cross-domain evidence leaks, and no visible uncited evidence across its fixture-backed scenarios. Those checks validate pipeline invariants under controlled inputs; they are not claims of universal factual accuracy. Live evaluations depend on model credentials, network access, and external providers.

## Deployment

The validated Railway production start command is:

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
```

Configure the health check path as `/health` and provide secrets through service environment variables. Use **one process/replica** for the current architecture: verification state is held in memory, so restarts clear requests and replicas do not share polling state. A durable shared store is required before horizontal scaling.

External provider availability can affect retrieval. No public demo URL is currently declared in this repository.

## Environment Variables

Pydantic reads variables case-insensitively from the environment or `.env`. Only the API key is required for the full live pipeline; other values have code defaults.

| Variable(s) | Required | Purpose | Secret? |
|---|---:|---|---:|
| `ANTHROPIC_API_KEY` | Yes for live use | Claim extraction and semantic validation | Yes |
| `ANTHROPIC_WORKSPACE_ID` | Conditional | Workspace header for keys that require it | Treat as sensitive |
| `ANTHROPIC_MODEL` | No | Anthropic model ID | No |
| `ANTHROPIC_TIMEOUT_SECONDS`, `ANTHROPIC_MAX_RETRIES` | No | Model request controls | No |
| `LOG_LEVEL` | No | Backend logging level | No |
| `HTTP_CONNECT_TIMEOUT`, `HTTP_READ_TIMEOUT` | No | Provider HTTP timeouts | No |
| `MAX_PROVIDER_QUERY_ATTEMPTS` | No | Default provider-query attempt bound | No |
| `QURANPEDIA_BASE_URL`, `HADEETHENC_BASE_URL`, `DORAR_BASE_URL`, `BAYAN_BASE_URL` | No | Provider base URLs | No |
| `DORAR_ENABLED` | No | Legacy generic Dorar adapter; off by default | No |
| `DORAR_HADITH_ENABLED`, `DORAR_HADITH_EXPLANATION_ENABLED`, `DORAR_TAFSEER_ENABLED` | No | Enable domain-specific Dorar adapters | No |
| `DORAR_FEQHIA_ENABLED`, `DORAR_AQEEDA_ENABLED`, `DORAR_HISTORY_ENABLED` | No | Enable domain-specific Dorar adapters | No |
| `DORAR_HADITH_MAX_QUERIES`, `DORAR_TAFSEER_MAX_QUERIES` | No | Per-provider query limits | No |
| `DORAR_FEQHIA_MAX_QUERIES`, `DORAR_AQEEDA_MAX_QUERIES`, `DORAR_HISTORY_MAX_QUERIES` | No | Per-provider query limits | No |
| `DORAR_HADITH_MAX_RESULTS`, `DORAR_FEQHIA_MAX_RESULTS`, `DORAR_AQEEDA_MAX_RESULTS` | No | Per-provider result limits | No |
| `QURANPEDIA_MAX_CONCURRENCY`, `HADEETHENC_MAX_CONCURRENCY` | No | Provider concurrency limits | No |
| `DORAR_MAX_CONCURRENCY`, `BAYAN_MAX_CONCURRENCY` | No | Provider concurrency limits | No |

The supplied `.env.example` contains safe defaults and blank credential fields. Do not commit `.env`.

## Limitations

- Retrieval depends on external sites, provider behavior, HTTP access, rate limits, and network availability.
- Evidence quality is bounded by what sources return and what can be aligned to a record.
- Semantic validation requires Anthropic access; ambiguous or failed validations may require specialist review.
- Request state and provider cache are process-local and in memory.
- Provider parsers may require maintenance when upstream HTML or API contracts change.
- Controlled evaluation artifacts do not establish universal factual or scholarly accuracy.
- Bayyinah is not a substitute for qualified scholarly judgment.

## Security

- Credentials are loaded server-side through environment variables; the frontend does not receive them.
- `.env` is excluded by `.gitignore`, and no real API key is tracked in the repository.
- Logged claim-extraction metadata excludes full submitted text and credentials.
- Submitted content is treated as untrusted data in model prompts, and semantic validation is constrained to supplied evidence.

## License

No open-source license has been declared yet. Until a license file is added, the repository should not be assumed to grant reuse, modification, or redistribution rights.

## Acknowledgements and Data Sources

Bayyinah retrieves or processes material from [Quranpedia](http://quranpedia.net/), [Dorar](https://dorar.net/), [HadeethEnc](https://hadeethenc.com/), and [Bayan](https://www.byenah.com/). All source content remains attributable to its respective provider and authors. Use of these sources does not imply affiliation with or endorsement of Bayyinah.

## Disclaimer

Bayyinah is an AI-assisted verification and research tool. It does not replace qualified scholars or authoritative religious institutions. Results should be reviewed in context, especially for legal, theological, or pastoral decisions.
