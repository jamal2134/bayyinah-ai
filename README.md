# Bayyinah AI — Phase 2

Bayyinah AI (بيّنة) is an Islamic-content verification pipeline for Team Burhan. This repository implements **only Phase 2**: it extracts atomic claims, preserves the user's meaning, classifies each claim, and prepares search queries. It does not retrieve evidence or decide whether anything is true, false, supported, authentic, or weak.

## Architecture

Phase 3 extends the working claim extractor with:

`Claim -> Source Router -> Retrieval Plan -> async provider adapters -> normalized EvidenceCandidate`

Deterministic routing:

| Claim metadata | Sources |
|---|---|
| Quran | Quranpedia |
| Hadith text/record | HadeethEnc, then Dorar |
| Hadith authenticity | Dorar, then HadeethEnc |
| Athar | Dorar |
| General Islamic library content | Bayan Al Islam |
| Non-verifiable | No external provider |

Quranpedia handles structured ayah and tafsir retrieval. HadeethEnc supplies structured hadith details. Dorar supplies Arabic search and separately preserved scholarly judgments; its embedded HTML is parsed before leaving the adapter. Bayan uses only its small Swagger-confirmed route set and returns structured errors for unavailable legacy routes.

Independent providers run concurrently. Query selection prefers structured Quran identifiers and distinctive `TEXT` attributes, then bounded Phase 2 query fallbacks. `MAX_PROVIDER_QUERY_ATTEMPTS` defaults to 3. In-memory caching is process-local and has a Redis-compatible boundary.

Evidence preserves provider, source, record ID or URL, rank, retrieval time, and available author, narrator, scholar, judgment, reference, page, and raw metadata. Provider similarity or relevance is preserved only when returned. Rank is never converted into confidence.

**Retrieval relevance is not evidence validation. Provider confidence or similarity does not automatically imply claim support.** Retrieval statuses describe retrieval only, not truth.

`POST /api/v1/claims/extract` → `ClaimService` (logging/timing) → `ClaimExtractor` (Anthropic) → strict Pydantic validation. Long articles and sermons are split at paragraph or sentence boundaries, processed in bounded chunks, merged in source order, deduplicated, and assigned stable sequential IDs. The model response is retried a bounded number of times when invalid or when the API fails. The prompt treats submitted content as untrusted data. Future evidence fields belong in later-phase models rather than this extraction contract.

Evidence policy: the extractor considers the full text as meaningful units. Externally checkable propositions are returned with `requires_evidence=true`, an Islamic/non-Islamic domain, a controlled claim type, and 1–3 future retrieval queries. Meaningful opinions, feelings, commands, prayers, rhetoric, and pure questions are retained as `NON_VERIFIABLE`, with `requires_evidence=false` and no queries. Empty fragments and connective phrases are ignored. Questions with factual presuppositions extract the presupposed proposition. Reports from Companions, Successors, and early Muslims can use the dedicated `ATHAR` domain and `ATHAR_TEXT`/`ATHAR_ATTRIBUTION` types.

## Install and run

Python 3.11+ is required.

```bash
cd bayyinah-ai
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --app-dir backend --reload
```

Set `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_WORKSPACE_ID`, `ANTHROPIC_MODEL`, `ANTHROPIC_TIMEOUT_SECONDS`, `ANTHROPIC_MAX_RETRIES`, and `LOG_LEVEL`. Keys that are not scoped to a workspace require `ANTHROPIC_WORKSPACE_ID`; the client sends it as the `anthropic-workspace-id` header. Credentials and workspace IDs are never logged. Requests are logged as structured JSON with request ID, input length, language, claim count, elapsed time, model, and outcome; full input content is excluded.

Health check: `GET /health`.

Phase 3 endpoints:

- `POST /api/v1/retrieval` accepts a Phase 2 claim object.
- `POST /api/v1/verify/retrieve` accepts `{"text":"..."}`, runs extraction and retrieval, and stops before evidence validation.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/claims/extract -H "Content-Type: application/json" -d "{\"text\":\"Ayat al-Kursi is verse 255 of al-Baqarah.\"}"
```

Example response (the exact model wording may vary):

```json
{"input_language":"en","claim_count":1,"claims":[{"id":"claim_001","original_text":"Ayat al-Kursi is verse 255 of al-Baqarah.","normalized_claim":"Ayat al-Kursi is verse 255 of Surah al-Baqarah.","claim_type":"QURAN_REFERENCE","domain":"QURAN","search_queries":["Ayat al-Kursi verse 255 al-Baqarah"],"entities":[{"name":"Ayat al-Kursi","type":"Quran passage"}],"requires_evidence":true,"reason":"This is an externally verifiable Quran reference."}]}
```

## Tests and evaluation

Unit tests mock Anthropic and do not incur API charges:

```bash
python -m pytest backend/tests -q
```

Provider unit tests also use mocked HTTP transports. Optional live tests are opt-in:

```bash
set RUN_LIVE_RETRIEVAL_TESTS=1
python -m pytest -m live backend/tests/test_live_retrieval.py -q
```

Run the complete real-provider verification (kept separate from fixture evaluation):

```bash
python evaluation/evaluate_live_retrieval.py
```

It writes `evaluation/phase3_live_results.json`, records endpoint/status/parameters/duration/parser
telemetry, and fails if a returned live evidence candidate contains fixture or mock markers.

Run the 25-case Phase 3 offline evaluation:

```bash
python evaluation/evaluate_retrieval.py
```

It writes `evaluation/results/retrieval_results.json` with routing, retrieval, metadata, failure handling, deduplication, and structured-output metrics. The report explicitly labels its fixture-provider evaluation mode. Each provider result includes query-attempt traces with query, attempt, duration, result count, and outcome.

The evaluation dataset has 30 hand-authored Arabic, English, mixed-language, injection, incorrect-claim, and multi-claim cases. A live run uses the configured Anthropic model:

```bash
python evaluation/evaluate_claim_extraction.py
```

It writes JSON metrics and a text summary under `evaluation/results/`. Without an API key it records a truthful `skipped` result and no metrics. Metrics use expected count ranges, required domain/type set recall, key-proposition substring recall, claims beyond the maximum as over-splitting, and successful Pydantic validation as structured-output success.

## Known limitations and next phase

HadeethEnc's official REST documentation confirms list and detail routes but not keyword search; keyword filtering is isolated as experimental. Bayan's documented surface is small and legacy endpoints may return 404. In-memory caching is not shared between processes.

Phase 3 deliberately excludes semantic entailment, claim/evidence comparison, attribute validation, conflict decisions, religious rulings, and supported/unsupported verdicts.

Atomicity and proposition matching remain model/evaluator judgments; substring-based key matching does not recognize every paraphrase. The API call is synchronous. Model JSON is constrained using Anthropic structured outputs and then independently validated with Pydantic. Phase 3 should attach retrieval results, source API, similarity and API confidence, and evidence in separate downstream models. No retrieval, evidence validation, conflict detection, or final decision logic is included here.

## Phase 4 — Evidence Validation

`POST /api/v1/validation` accepts a Phase 2 `Claim` and Phase 3 `EvidenceCandidate[]` and returns
one `AttributeValidationResult` per evidence-requiring attribute. It never returns a final claim
verdict; Phase 5 remains intentionally unimplemented.

The request may also include the original Phase 3 `retrieval_result`. If its status is
`MISSING_CONTEXT`, Phase 4 preserves that retrieval status, the missing fields, and the original
reason, marks validation execution as `SKIPPED`, and does not invoke semantic validation. This keeps
an unidentified Quran verse or hadith reference distinct from contradictory evidence or validator
failure.

`Claim → Attributes → Evidence Matcher → Deterministic/Semantic Validator → AttributeValidationResult[]`

Phase 3 `target_attribute_ids` are authoritative when present. Older untargeted evidence is matched
conservatively by evidence type. Structured fields are checked first. Quran identifiers and counts,
narrators, sources, scholars, references, and explicit judgments use deterministic comparison where
possible. Tafsir, meaning, context, rulings, and educational material fall back to the configured
Anthropic model in closed-evidence mode. Claim and evidence content are untrusted data, and the model
is forbidden to fill gaps from remembered religious knowledge.

The attribute statuses are `SUPPORTED`, `PARTIAL`, `CONTRADICTED`, `NOT_FOUND`, and `UNCERTAIN`.
Absence is not contradiction. Similarity is not evidence, and provider scores are never treated as
truth confidence. `asserted_by` must be established by source provenance. Conflicting candidates
retain both supporting and contradicting evidence IDs. `validator_confidence`, when present, means
confidence in the evidence-relationship classification—not the probability that a religious claim
is true.

Dorar is disabled by default (`DORAR_ENABLED=false`) because real requests return HTTP 403. Phase 4
does not depend on Dorar. A HadeethEnc record without an explicit grade does not establish hadith
authenticity. Only an explicit judgment field may establish `AUTHENTICITY`; when `asserted_by` is
present, the grading scholar or authority must also be explicitly identified.

Run the 30-case deterministic/offline evaluation and the optional live semantic evaluation separately:

```bash
python evaluation/evaluate_phase4.py
python evaluation/evaluate_phase4_live.py
```

The offline report is written to `evaluation/results/phase4_results.json`. Semantic accuracy remains
unset in offline mode instead of being fabricated from answer-key logic. Known limitations include a
small explicit source/surah alias table, dependence on provider metadata quality, and conservative
abstention when attribution or semantic relationships are ambiguous.

## Phase 5 — Deterministic Decision Engine

Phase 5 consumes Phase 4 output only. It performs no retrieval, model call, or evidence-text
interpretation. `POST /api/v1/decisions` accepts an `EvidenceValidationResponse` directly;
`POST /api/v1/decisions/with-claim` additionally accepts its upstream claim so attributes marked
`requires_evidence=false` can be excluded explicitly.

The fixed decision priority is: execution/specialist conditions, evidence conflict, contradiction,
missing or ambiguous evidence, partial evidence, then complete support. Validator confidence is not
used as truth probability. Only evidence IDs already classified by Phase 4 are propagated.

Run the deterministic and saved-live-input evaluations without making any provider calls:

```bash
python evaluation/evaluate_phase5.py
python evaluation/evaluate_phase5_e2e.py
```

## Phase 6 — Traceable Verification Reports

Phase 6 deterministically renders the Phase 5 decision, Phase 4 attribute results, and only the
Phase 3 evidence actually referenced by those results. It does not retrieve evidence, reinterpret
evidence, call an LLM, or recompute a decision. Arabic summaries, reason explanations, attribute
messages, safety notes, and presentation metadata come from fixed templates.

`POST /api/v1/reports` accepts the original claim, Phase 3 candidates, Phase 4 response, and Phase 5
decision. Its response includes a simple Arabic presentation and machine-readable trace data. Source
roles are scoped per attribute, so one source may support one attribute and contradict another.

Run the 22-case deterministic evaluation and six saved E2E cases offline:

```bash
python evaluation/evaluate_phase6.py
```

This writes `evaluation/phase6_results.json` and `evaluation/phase6_e2e_results.json` without calling
providers or generative AI.

## Full application

The application entry point now runs the existing phases in order without duplicating their domain
logic:

```text
Arabic RTL web UI
  -> POST /api/v1/verify
  -> claim extraction
  -> provider routing and retrieval
  -> candidate alignment and attribute validation
  -> deterministic Phase 5 decision
  -> deterministic Phase 6 report
  -> GET /api/v1/verify/{request_id}
```

Request state is held in process memory for this hackathon version. Restarting the server clears
requests, and multiple server workers do not share state. A durable request store can replace the
in-memory dictionary without changing the pipeline contract.

### Run

From `bayyinah-ai`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000`. FastAPI serves the frontend and API from the same origin. The UI uses
reliable polling for live progress, supports multiple claims, and provides collapsible trace,
technical, source, and cost details on desktop and mobile.

### Environment variables

- `ANTHROPIC_API_KEY`: required for live claim extraction and semantic validation; never returned to
  the browser or logged.
- `ANTHROPIC_WORKSPACE_ID`: optional workspace header for keys that require it.
- `ANTHROPIC_MODEL`: model ID; defaults to `claude-sonnet-4-5`.
- `ANTHROPIC_TIMEOUT_SECONDS`, `ANTHROPIC_MAX_RETRIES`: model-call controls.
- `HTTP_CONNECT_TIMEOUT`, `HTTP_READ_TIMEOUT`, `MAX_PROVIDER_QUERY_ATTEMPTS`: retrieval controls.
- `DORAR_ENABLED`: enables the optional Dorar adapter.
- Provider base URLs and concurrency settings are defined in `app.config.settings.Settings`.

### Verification and API status

Phase 5 is the only authority for `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONFLICTING`,
`INSUFFICIENT_EVIDENCE`, and `REQUIRES_SPECIALIST`. Phase 6 supplies all user-facing Arabic report
wording. The frontend renders those structures and never derives a decision. A missing result is
kept distinct from contradiction, and missing authenticity evidence never becomes an authenticity
judgment.

Application endpoints:

- `POST /api/v1/verify` starts a request and returns its `verify_...` ID.
- `GET /api/v1/verify/{request_id}` returns progress or the completed result.
- `GET /api/v1/health` returns application health.
- Existing phase-specific `/api/v1` endpoints remain available.

### Usage and cost tracking

Every successful Anthropic response contributes its SDK-provided `usage` fields: input, output,
cache-write, and cache-read tokens. No character-count token approximation is used. Prices live only
in `backend/app/application/pricing.py`, are expressed per million tokens, and support separate cache
rates. An unknown model returns `PRICING_UNAVAILABLE` and no fabricated monetary amount.

Request cost is the sum of recorded model-call costs. Provider request counts are shown separately
and are not treated as financial cost. USD is converted using the configured fixed display rate
`1 USD = 3.75 SAR`, retaining Decimal precision in the backend and rounding only in the UI. Cost
tracking is observational and is never passed to retrieval, validation, decision, or report logic.

Run all tests:

```bash
python -m pytest backend/tests -q
```

