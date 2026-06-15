# CompMap — Project Pipeline Explainer

*For a lawyer-builder preparing for product discussions. Based on actual repository state as of June 2026.*

---

## 1. Project Overview

**CompMap** is a source-first competition law research pipeline. It takes real merger control decisions from the EU Commission, UK CMA, and US FTC/DOJ and converts them into structured, searchable data — where every legal proposition links back to a specific paragraph and quote in the underlying authority document.

**Practical use case:** A lawyer researching market definition precedent in a media/gaming merger can search CompMap and find: which product markets were considered, what definition status was reached (defined, discussed, left open), what theories of harm were raised, and exactly which passage of which decision supports each finding — with page and paragraph numbers.

**Current state:** This is a v0 first slice. There are 18 source-verified canonical case records plus an initial broad indexed corpus of 8 metadata-only case records. The ingestion pipeline now covers source caching, multi-focus LLM extraction, deterministic validation, LLM review triage, safe draft-to-canonical promotion, review-learning logs, eval fixtures, long-decision assembly, and profile-driven controlled-case running. The pipeline started with market-definition extraction and has now been extended to outcome metadata, theories of harm, remedies/commitments, repeated-unit assessment for long Phase II decisions, and a separate broad-index layer for cheaper discovery. The long-decision pipeline has been proven on a promoted Phase II conditional-clearance hard case (`eu_bayer_monsanto_2018`), controlled corpus expansion has produced a clean EC Phase I case (`eu_cochlear_oticon_medical_2023`), the first same-transaction EC/CMA Phase II pair (`eu_viasat_inmarsat_2023` and `uk_viasat_inmarsat_2023`), the profile-driven US court-opinion path has been proven on `us_tapestry_capri_2024`, and the one-command controlled-case runner has promoted `eu_booking_etraveli_2023` from merged draft to canonical data. Broad case-index graph support and read-only API exposure are now implemented; frontend cleanup and product surfacing are next.

---

## 2. Tech Stack


| Layer                      | Technology                                                              | Role in this project                                                                    | Why it matters                                                                         |
| -------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Data stores** | YAML files (`data/cases/**/*.yaml`, `data/case_index/**/*.yaml`, `data/concepts/**/*.yaml`) | Canonical reviewed records, broad metadata-only indexed records, and reusable concept taxonomy | Keeps reviewed legal propositions separate from cheaper discovery/index data while remaining human-readable and git-diffable |
| **Schema / validation**    | Pydantic 2.9 (`apps/api/app/models/case.py`)                            | Enforces structure, enums, required fields on every YAML load                           | Prevents malformed records from reaching the API                                       |
| **Backend API**            | FastAPI + Python 3.12 (`apps/api/`)                                     | Serves canonical cases, indexed cases, keyword search, semantic search, and graph entity queries over HTTP | Exposes structured data to the frontend; canonical and indexed response models kept separate |
| **Vector database**        | Postgres 16 + pgvector (`docker-compose.yml`, `apps/api/migrations/`) | Stores 768-dim embeddings for cases, product markets, and theories; serves cosine similarity search | Replaced Neo4j (June 2026); handles relational + vector queries in one service; port 5433 locally, 5432 in Docker |
| **Embeddings**             | Google `gemini-embedding-001` via `google-genai` SDK (`apps/api/app/services/embedding_service.py`) | Generates 768-dim document embeddings (indexing) and query embeddings (search) with asymmetric task types | Enables semantic search across markets, theories, and case summaries without keyword matching |
| **Frontend**               | Next.js 14, React 18, TypeScript, Tailwind (`apps/web/`)                | Search UI (keyword + semantic toggle), case detail pages, source passage display, entity-centric graph (Market Map + Theory Map) | Makes the data usable without direct API calls                                         |
| **PDF / text extraction**  | pypdf, pdfplumber (`apps/api/app/utils/pdf_extractor.py`)               | Extracts and caches text from authority PDFs                                            | Required before any quote can be validated or extracted                                |
| **LLM extraction**         | Anthropic SDK / Claude + Google Gemini (`apps/api/scripts/extract_case_from_source.py`) | Multi-focus extraction of markets, geographic scope, outcome metadata, theories of harm, remedies/commitments, source passages, and repeated-unit findings; `--provider gemini` for bulk/free-tier extraction | Core semi-automated legal structuring layer; each pass remains source-backed and reviewable |
| **Validation / pipeline scripts** | Python CLI scripts (`apps/api/scripts/`)                                | Orchestrates ingestion, page-range planning, draft merging, quote integrity, schema validation, source-link checks, eval benchmarks, and bulk extraction runs | These are the quality gates; they enforce the source-first principle and keep generated drafts reviewable |
| **Evaluation fixtures**    | YAML gold files + JSON eval reports (`data/evals/`)                     | Benchmark extraction quality against curated ground-truth records                       | Enables measurable precision/recall for extraction                                     |
| **Containerisation**       | Docker Compose (`docker-compose.yml`)                                   | Runs postgres, api, web, and a one-off embed container together                         | Full local stack in one command; not yet production-deployed                           |
| **CI**                     | GitHub Actions (`.github/workflows/`)                                   | Runs schema validation + a CI-safe eval benchmark subset on every push                  | Catches regressions without requiring a running database or live PDFs                  |


---

## 3. Current Pipeline

The pipeline has two distinct parts: **manual legal judgment** and a **semi-automated, source-first ingestion flow**. The ingestion flow is no longer a single market-definition pass. It now supports multiple focused passes — market definition, outcome metadata, theories of harm, remedies/commitments, and repeated-unit assessment — which can be assembled into one reviewable draft before human promotion.

### Stage 0 — Case selection (manual)

- **What:** Decide which case to add; identify the authoritative source documents.
- **Inputs:** Authority websites (EC competition registry, CMA decisions page, US court PACER).
- **Outputs:** Case identifier (`case_id` convention: `{jurisdiction}_{parties}_{year}`) and a list of document URLs.
- **Status:** Fully manual. No automation exists for discovery or prioritisation.

---

### Stage 1 — Source fetch and text cache

- **What:** Fetch the PDF decision and extract its text for downstream use.
- **Script:** `apps/api/app/utils/pdf_extractor.py`
- **Inputs:** URL of authority PDF.
- **Outputs:** Cached JSON text file in `data/source_text/` (e.g., `eu_microsoft_activision_2023_decision.json`).
- **Competition law context:** The source text is the evidentiary foundation. If the wrong document is fetched, all downstream extractions will be wrong. This was confirmed during the data baseline pass: valid URLs were not enough; each source had to be checked against the actual authority document.
- **Status:** Semi-automated; cache is checked before re-fetching.

---

### Stage 2 — Seed / skeleton case record

- **What:** Create the skeleton YAML file with case metadata.
- **Files written:** `data/cases/{jurisdiction}/{case_id}.yaml`
- **Schema:** Validated against `CaseRecord` Pydantic model (`apps/api/app/models/case.py`).
- **Key fields set at this stage:** `case_id`, `case_name`, `jurisdiction`, `authority`, `decision_date`, `procedure_stage`, `sector`, `parties`, `outcome`.
- **Status:** Manual. For the baseline cases, this was done by hand.

---

### Stage 3 — LLM-assisted extraction

- **What:** Claude reads cached source text and proposes structured legal records from the authority document.
- **Script:** `apps/api/scripts/extract_case_from_source.py`
- **Inputs:** Cached source text JSON from `data/source_text/`; existing case YAML (if any) for reconciliation; optional focus mode and page range.
- **Outputs:** Draft YAML in `data/drafts/{jurisdiction}/` and a review report.
- **Focus modes:**
  - `market_definition` — product/geographic markets and source passages.
  - `outcome_metadata` — outcome, procedure stage, decision date, authority reference, and operative support.
  - `theories` — horizontal, vertical, conglomerate, innovation, and other theories of harm.
  - `remedies` — commitments, divestitures, access/licensing obligations, and related source passages.
  - `unit_assessment` — repeated unit-level findings where a long decision analyses many similar units, such as crops, routes, countries, indications, customer segments, or asset sites.
- **Competition law context:** A merger decision is not just a list of market definitions. A useful research record also needs to know what the authority decided, which harms were identified, what remedies were accepted, and where repeated factual assessments sit in the source.
- **Status:** Semi-automated. Each draft remains generated work product and requires human review before promotion to `data/cases/`.

---

### Stage 3a — Long-decision planning and page-range extraction

- **What:** For large Phase II decisions, the pipeline plans smaller extraction windows instead of sending hundreds of pages into one prompt.
- **Scripts:** `apps/api/scripts/plan_extraction_ranges.py`; `ingest_case.py --page-range START:END --output-suffix SUFFIX`.
- **Inputs:** Cached source text with page/section metadata.
- **Outputs:** Suggested page ranges and commands for targeted focus-specific drafts.
- **Why this matters:** Long decisions often contain distinct sections for market definition, competitive assessment, remedies, and operative outcome language. Page-range extraction keeps each pass narrow enough to be accurate and reviewable.
- **Status:** Implemented for diagnostic and controlled long-case extraction.

---

### Stage 3b — Multi-focus draft assembly

- **What:** Merge multiple focus-specific drafts for the same case into one reviewable draft.
- **Script:** `apps/api/scripts/merge_drafts.py`
- **Inputs:** Draft YAMLs from market-definition, outcome, theories, remedies, and unit-assessment passes.
- **Outputs:** A merged draft under `data/drafts/`, with global IDs and rewritten cross-references.
- **What it handles:** Metadata precedence, theory/commitment/unit deduplication, source-passage deduplication, ID rewriting, and back-reference synthesis.
- **Status:** Implemented as a review-draft assembly tool. It does not promote to canonical data.

---

### Stage 4 — Quote validation gate

- **What:** Every quote snippet proposed by the LLM is checked against the actual extracted source text. If a quote cannot be found, it is rejected — it is not written to YAML.
- **Script:** `apps/api/scripts/check_source_integrity.py`; key function: `quote_found_in_text(quote, text)` using fuzzy matching.
- **Inputs:** Draft YAML; cached source text.
- **Outputs:** Pass/fail report; passages that failed are excluded from the draft.
- **Why this matters:** LLMs hallucinate quotes. This gate is the primary technical safeguard against fabricated citations appearing in the record. The gate was built after a fabricated source URL was discovered in `us_microsoft_activision_2023` during manual authoring (see `docs/ingestion-design.md`).
- **Status:** Automated check; runs as part of script and in CI. The `--no-cache` extraction path was updated to prefer `pdfplumber` over `pypdf` (consistent with the cache builder), and the fragment search was fixed to scan forward monotonically — both changes surfaced during Bayer/Monsanto source-integrity cleanup.

---

### Stage 5 — Source link validation

- **What:** HTTP GET on every source document URL to confirm it resolves to a real, correctly-typed document (not a broken link, redirect, or portal page).
- **Script:** `apps/api/scripts/check_source_links.py` (120 lines)
- **Inputs:** YAML `source_documents` section.
- **Outputs:** OK / broken / portal classification per URL.
- **Status:** Automated check; blocking — broken URLs must be resolved before a record can be committed.

---

### Stage 5b — Broad index source audit

- **What:** Validates `source_url` fields in `data/case_index/**/*.yaml` entries. Catches wrong EC case numbers (e.g. M.10939 vs M.10806), dead CMA slugs, malformed FTC matter IDs, and non-official domains — the class of errors that caused the June 2026 URL audit.
- **Script:** `apps/api/scripts/check_case_index_sources.py`
- **Inputs:** `data/case_index/**/*.yaml`
- **Checks per entry (in order):**
  1. `source_url` present — WARN if null (null is a documented status, not a silent gap)
  2. Domain on the official allowlist for the entry's jurisdiction (EU: `ec.europa.eu`/`eur-lex.europa.eu`/EC portal; UK: `gov.uk`; US: `ftc.gov`/`justice.gov`/`.uscourts.gov`)
  3. EC competition-cases portal path must match `/cases/M.<digits>`
  4. FTC matter-URL slug must start with a recognisable matter ID (`2210077-` or `201-0144-`)
  5. HTTP liveness — HEAD with GET fallback; skipped with `--no-http`
- **Outputs:** Pass / fail / warn report by `case_id`; exit 0 if no FAIL, exit 1 if any FAIL.
- **Run before committing any new or updated index entry:**
  ```bash
  # domain + format checks only (no network, fast):
  apps/api/.venv/bin/python apps/api/scripts/check_case_index_sources.py --no-http

  # full check including HTTP liveness (run at least once before first commit):
  apps/api/.venv/bin/python apps/api/scripts/check_case_index_sources.py
  ```
- **Status:** **Mandatory** before committing new or updated `data/case_index/` entries. Does not gate canonical promotion.

---

### Stage 6 — Schema validation

- **What:** Run Pydantic validation across all YAML files to confirm type correctness, enum values, required fields, and referential consistency between passages and source documents.
- **Script:** `apps/api/scripts/validate_cases.py`
- **Inputs:** All YAML files in `data/cases/` or `data/drafts/`.
- **Outputs:** Pass/fail per file, with Pydantic error messages.
- **Status:** Automated; also runs in GitHub Actions CI on every push.

---

### Stage 7 — Human review and promotion

- **What:** A human reviewer reads the draft YAML against the actual source document. They verify quote accuracy, check that `definition_status` is correct (e.g., not marking `defined` for something the authority only `discussed`), and update `review_status` fields from `unreviewed` to `spot_checked` or `lawyer_reviewed`.
- **Files edited:** `data/drafts/.../` → promoted to `data/cases/` after review.
- **Hard-case review:** For merged drafts from long decisions, use `docs/hard-case-review-checklist.md` as the promotion gate. It covers cross-reference integrity, orphaned nodes, dangling refs, conclusion labels, duplicate passage detection, and outcome metadata verification.
- **Status:** Manual legal sign-off, but promotion is now automated through `apps/api/scripts/promote_case_pipeline.py`. The wrapper runs target-draft source integrity first and aborts before promotion if the target draft has any source-integrity errors or warnings.

Preferred promotion command:

```bash
apps/api/.venv/bin/python apps/api/scripts/promote_case_pipeline.py \
  --case-id <case_id> \
  --focus market_definition \
  --procedure-stage phase1 \
  --overwrite
```

---

### Stage 7a — Review learning log

- **What:** Capture the delta between the original draft, the LLM review, the human-reviewed draft, and the promoted canonical record.
- **Goal:** Turn repeated human corrections into reusable extraction rules, validator warnings, prompt updates, and eval fixtures.
- **Inputs:** `data/drafts/...draft.yaml`, `data/drafts/...llm_review.json`, promoted `data/cases/...yaml`.
- **Outputs:** Review learning logs under `data/review_learning/`, with categorised correction types such as `definition_status_mapping`, `source_role_correction`, `support_linkage_correction`, `outcome_passage_misuse`, and `missing_market_added`.
- **Status:** v1 implemented. The first review-learning log was generated for `eu_sika_dry_mix_2019`. Learning logs are structured memory; they improve the next extraction only when converted into prompt rules, validator warnings, or eval fixtures.

---

### Stage 7b — Apply review learning and central rules

- **What:** Read review-learning logs and convert recurring corrections into concrete pipeline changes.
- **Outputs:** Proposed extraction prompt updates, LLM review prompt updates, deterministic validator rules, eval fixtures, and documentation updates.
- **Central rule registry:** Implemented. General legal-extraction rules now live in `data/pipeline_rules/market_definition_rules.yaml` and are reflected in extraction/review prompt guidance and tests.
- **Why:** The registry avoids rule drift. The LLM should not receive scattered conflicting rules; prompts should be generated from or checked against the same canonical rule text.
- **Status:** v1 proposal tooling exists via `apply_review_learning.py`; central market-definition rules are v1 implemented. Future work is to load/generate prompt blocks directly from the registry rather than mirroring them manually.

---

### Stage 8 — API serving

- **What:** FastAPI loads validated canonical YAML from `data/cases/` and metadata-only index YAML from `data/case_index/` through separate services. Routes include `GET /cases`, `GET /cases/{id}`, `GET /indexed-cases`, `GET /indexed-cases/{id}`, `GET /search?q=`, `GET /search/all?q=&scope=`, and `GET /graph/case/{id}`.
- **Files:** `apps/api/app/services/case_service.py`, `apps/api/app/routers/`.
- **Index separation:** Indexed responses use lightweight response models with `data_layer="indexed"` and `record_status="indexed_metadata"`; they do not expose canonical legal-proposition fields such as product markets, theories of harm, commitments, source passages, or metadata.
- **Status:** Fully implemented and working.

---

### Stage 9 — Embedding index

- **What:** Embeds all canonical YAML records and upserts into Postgres pgvector tables (`case_embeddings`, `market_embeddings`, `theory_embeddings`). Enables semantic similarity search across the corpus.
- **Script:** `apps/api/scripts/index_embeddings.py`. Run locally: `python apps/api/scripts/index_embeddings.py` with `GOOGLE_API_KEY` and `DATABASE_URL` set in `.env`.
- **Run via Docker Compose:** `docker compose --profile embed up embed`
- **Inputs:** `data/cases/**/*.yaml` (canonical only); running Postgres instance.
- **Embed text per case:** AI summary + product market names/notes + theory names/descriptions + sector. Indexed separately at market and theory granularity too.
- **Outputs:** Postgres tables populated with 768-dim vectors (Google `gemini-embedding-001`, Matryoshka-truncated to 768 dims via `output_dimensionality=768`).
- **Idempotent:** Uses `ON CONFLICT DO UPDATE` — safe to re-run after new promotions.
- **Status:** Implemented and verified. 26 canonical cases + 216 market embeddings + 37 theory embeddings loaded as of June 2026. Semantic search confirmed working ("online advertising" → EU Google/Meta cases at 0.6+ similarity). Note: `neo4j_client.py`, `graph_service.py`, and `graph/seed_graph.py` remain as dead code and can be deleted.

---

### Stage 10 — Evaluation / benchmarking

- **What:** Measures extraction quality by comparing LLM-extracted drafts against manually-curated gold standard records. Computes precision, recall, and F1 per market type and checks that all quotes passed validation.
- **Scripts:** `evaluate_extraction.py`, `run_eval_benchmark.py`, `create_gold_draft.py`.
- **Benchmark config:** `data/evals/benchmark.market_definition.yaml`; CI-safe subset: `benchmark.market_definition.ci.yaml`.
- **Example result (eu_microsoft_activision_2023):** Product market F1 = 1.0 (2/2 true positives, 0 false positives, 4 unjudged candidates outside the gold subset). Quote validity: 9/9 passed.
- **Status:** Implemented for 6 market-definition eval fixtures. The benchmark runs 6/6 PASS at F1=1.000 and now serves as a regression suite for known-good promoted cases. Generated `data/evals/results/*` outputs should remain workflow artifacts, not committed product data.

---

### Broad index entry acceptance rules

These rules apply to every `data/case_index/**/*.yaml` entry. They are the index equivalent of the promotion gate for canonical records.

**Before committing a new or updated index entry, all of the following must be true:**

1. **Source URL is official or explicitly null.**  
   `source_url` must point to a domain on the official allowlist for the jurisdiction (EC competition portal, EUR-Lex, or `ec.europa.eu` for EU; `gov.uk` for UK; `ftc.gov`, `justice.gov`, or a `.uscourts.gov` subdomain for US).  
   If no official public source exists, set `source_url: null` — do not leave a guessed or commentary URL in place.

2. **Jurisdiction and authority match the source.**  
   An entry filed under `jurisdiction: UK` with `authority: Competition and Markets Authority` must link to a CMA case page, not the EC portal or a press article. If the authority that actually reviewed the deal is different from what you assumed, fix the `jurisdiction` and `authority` fields — do not paper over the mismatch with a redirecting URL.

3. **The deterministic checker passes (exit 0).**  
   Run `check_case_index_sources.py --no-http` (domain + format checks) before staging, and `check_case_index_sources.py` (full HTTP liveness) at least once before the first commit of a new entry.

4. **Concept refs are conservative, quality-labelled, and provenance-labelled.**  
   Use `quality_level: indexed` (not `canonical`) and set `provenance` to `manually_tagged` or `ai_extracted` as appropriate. Only include concepts clearly supported by the public record; do not infer from company names alone.

5. **No canonical proposition fields.**  
   Index entries must not contain `product_markets_considered`, `geographic_markets_considered`, `theories_of_harm`, `commitments`, `source_passages`, `source_documents`, `metadata`, or any other field that belongs to `CaseRecord`. The schema (`extra="forbid"`) enforces this at load time, but the rule applies to intent as well.

**Contrast with canonical gates:** Canonical records run Stages 3–7 (LLM extraction, quote validation, source integrity, schema validation, human review, and promotion pipeline). Index entries skip all of those and run only the Stage 5b source check. The index is intentionally lightweight — but source-first still applies.

---

### Jurisdiction / document-type profiles

The pipeline is a single shared engine with **jurisdiction/document-type profiles**. Profiles prevent the system from becoming a lowest-common-denominator generic extractor by supplying document-specific vocabularies and policies at each stage.

**Why profiles exist:** The pipeline was originally tuned for EU Commission merger decisions, whose sections are labelled "COMPETITIVE ASSESSMENT", "THEORY OF HARM", "COMMITMENTS", etc. When a US federal court opinion was ingested (`us_tapestry_capri_2024`), section-path matching found zero theory sections because US opinions use headings like "Market Share and Concentration", "HHI Analysis", "Final Analysis", and "Likelihood of Success". Profiles fix this without building a separate US pipeline.

**Profile files:** `data/pipeline_profiles/*.yaml`

| Profile ID         | Jurisdiction | Document types                                      |
|--------------------|--------------|-----------------------------------------------------|
| `ec_decision`      | EU           | EC Phase I/II merger decisions                      |
| `cma_report`       | UK           | CMA Phase 1/2 merger reports, provisional findings  |
| `us_court_opinion` | US           | Federal district court opinions, preliminary injunctions |

**What each profile controls:**
- **Coverage keywords** — per-category section-heading terms used by `plan_coverage.py` to detect market-definition, geographic-market, theories, and remedies sections.
- **Source-role mapping** — jurisdiction-adapted descriptions injected into extraction prompts (e.g. "court analysis and findings → commission_assessment").
- **Orphan-passage policy** — roles that are allowed to be unlinked without a warning (e.g., US court `conclusion` and `background` passages that express an injunction outcome).
- **Focus defaults** — which extraction passes apply to this document type.

**How profiles are selected:**
1. `--profile <id>` CLI override (highest priority).
2. Inference from case YAML metadata (`jurisdiction` field).
3. Inference from `case_id` prefix (`eu_` → `ec_decision`, `uk_` → `cma_report`, `us_` → `us_court_opinion`).

**Where profiles are wired in:**
- `plan_coverage.py --profile us_court_opinion` — uses US-specific theory keywords for coverage planning.
- `check_review_readiness.py --profile us_court_opinion` — applies US-specific orphan policy (conclusion/background unlinked passages are not flagged).
- `extract_case_from_source.py --profile us_court_opinion` — injects US-adapted source-role mapping into extraction prompts; triggers page-text fallback for theories focus when section-path matching finds nothing.

**First profile-driven regression target:** `us_tapestry_capri_2024` — SDNY preliminary injunction opinion (169 pages). This case has now been promoted after the `us_court_opinion` profile detected US-style competitive-effects coverage, source roles were persisted correctly, readiness checks passed, and human review confirmed the source-grounded market/theory structure.

---

## 4. Competition Law Framework Mapping

The data model maps onto the standard competition law analysis framework as follows:


| Legal concept                     | Where it lives in CompMap                                        | What it captures                                                                                             |
| --------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **Product market definition**     | `product_markets_considered[]`                                   | Market name, `definition_status` (defined / discussed / segmented / left_open), notes on authority reasoning |
| **Geographic market definition**  | `geographic_markets_considered[]`                                | Market name and scope (EEA, national, global), `definition_status`                                           |
| **Market segments / sub-markets** | `definition_status: segmented` within product/geo market entries | Where authority identified sub-segments without fully resolving the boundary                                 |
| **Parties and transaction**       | `parties[]` with `role` (acquirer / target / third_party)        | Structural context for the transaction                                                                       |
| **Theories of harm**              | `theories_of_harm[]`                                             | Name + description; linked to source passages via `supports_theories` cross-references                       |
| **Evidence relied on**            | `source_passages[]` with `quote_snippet`, `page`, `paragraph`    | Direct quotes from the decision; each passage explicitly links to the markets or theories it supports        |
| **Outcome / procedural posture**  | `outcome`, `procedure_stage`, `decision_date`, `authority_reference` | Whether the transaction was cleared, conditionally cleared, prohibited, or otherwise resolved; anchored in operative decision language |
| **Remedies / commitments**        | `commitments[]` / remedies-related passages                         | Structural divestitures, behavioural/access obligations, purchaser requirements, and source support                              |
| **Procedural history**            | `case_history` object with timeline events                       | Phase transitions, referrals, appeals, annulments                                                            |
| **Repeated factual assessments**  | `unit_assessments[]`                                                 | Unit-level findings where a decision analyses many repeated units, such as crops, routes, countries, indications, or asset sites |
| **Source citation support**       | `source_documents[]` + `source_passages[]`                       | Every finding is traceable to a specific document, page, and paragraph                                       |


**On legal weighting and confidence:** The schema includes `confidence_score` (0.0–1.0) on source passages and `overall_confidence` on the case record's metadata. These are currently set by the extraction script and are not based on a formal legal weighting methodology. There is no structured scoring of legal hierarchy (e.g., Commission decision vs. GC judgment vs. complaint allegation). The current system relies on `definition_status` enums and `review_status` fields to distinguish what was formally decided vs. merely discussed, and on human review to catch misclassification. Formal legal weighting does not yet exist.

---

## 5. Human Review

Human review is the primary reliability layer in the current system.

**What the reviewer checks:**

- Is each `definition_status` correct? A market left open by the authority should not be marked `defined`.
- Does each `quote_snippet` appear verbatim (or near-verbatim) in the source document at the stated page/paragraph?
- Are complaint allegations distinguished from adjudicated findings? (The pipeline design requires `definition_status: discussed` and a clear note for unresolved claims.)
- Are cross-references between passages and markets/theories (`supports_markets`, `supports_theories`) accurate?
- Are there important markets or theories missed by the extraction?

**What "source-first" means in practice:**
Every proposition in the YAML must be backed by a `source_passage` entry. A finding with no passage is a red flag. The extraction script will not write a quote it cannot locate in the source text — but it can still misclassify a passage's legal significance. The human reviewer catches this.

**Files the reviewer edits:**

- Draft: `data/drafts/{jurisdiction}/{case_id}.yaml`
- Promoted to canonical: `data/cases/{jurisdiction}/{case_id}.yaml`
- Reviewer sets `review_status` fields from `unreviewed` → `spot_checked` or `lawyer_reviewed` on each passage.
- Reviewer sets `overall_confidence` on `CaseMetadata` to reflect actual confidence after review.

**What remains risky / manual:**

- Source document selection: the system cannot currently verify that a URL points to the right version of a document (the `eu_illumina_grail_2022` wrong-PDF issue is an example).
- Quote boundary judgment: the fuzzy matching can pass quotes that are close but not legally precise.
- Completeness: the extraction may miss markets the authority discussed briefly. There is no structured check for exhaustiveness.
- Legal interpretation: `definition_status` and `definition_status: discussed` vs. `left_open` requires legal judgment; the LLM gets this wrong.

---



| Dimension                       | Score /10 | Reason                                                                                                            | Practical improvement                                                                       |
| ------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Automation**                  | 5/10      | Ingestion, LLM triage, promotion wrapper, review learning, and central rules exist; bulk run (459 Phase I drafts) proved Gemini pipeline at scale; corpus expansion still needs human legal sign-off | Triage and promote bulk drafts; review-learning pipeline reduces manual scope over time |
| **Scalability**                 | 5/10      | Postgres+pgvector semantic search works; 26 cases embedded; 459 Phase I drafts ready to promote; entity-centric graph aggregates from YAML | Promote bulk drafts to canonical; re-run indexer; corpus needs 200+ canonical for search to return rich results |
| **Accuracy / source grounding** | 7/10      | Quote validation gate is real and enforced; eval results on 6 cases show F1 = 1.0 on partial gold; Gemini bulk extraction quality not yet spot-checked | Spot-check bulk drafts before mass-promotion; expand gold fixtures |
| **Legal reliability**           | 5/10      | Source passage links are genuine; but no formal legal weighting, definition status can be misclassified by LLM    | Add structured legal review checklist; separate allegation vs. finding at schema level      |
| **Maintainability**             | 7/10      | YAML is readable and git-diffable; Pydantic schema enforces structure; scripts are well-factored; Neo4j removed (simpler stack) | Delete dead Neo4j code; document schema evolution policy |
| **Deployment readiness**        | 4/10      | Docker Compose works locally; Postgres replaces Neo4j (simpler managed hosting); no production deployment, no auth, no rate limiting | Add Railway deploy config, CORS, single-key auth; Vercel for frontend |
| **User-facing usefulness**      | 6/10      | Semantic search + entity-centric graph (Market Map, Theory Map) now available locally; 26 cases makes graph sparse; needs corpus scale | Promote bulk drafts; simplified-procedure display; redeploy indexer |
| **Evaluation / test coverage**  | 6/10      | Eval framework is real with precision/recall metrics; gold standard covers 6 market-definition fixtures (benchmark 6/6 PASS at F1=1.000); CI-safe benchmark subset exists | Keep expanding gold fixtures for promoted cases; add completeness recall and keep generated eval results out of git status |


---

## 7. Issues Faced During Pipeline Build


| Issue faced                                  | Why it mattered                                                                                    | What we did                                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Hallucinated or unsupported citations**    | An AI-generated legal record is unsafe if the quote or source does not actually exist              | Added quote validation against extracted source text; rejected passages that cannot be found   |
| **Wrong or unstable authority links**        | A valid URL can still point to the wrong document, portal page, appeal judgment, or updated source | Added source link checks and surfaced known data quality issues for manual correction          |
| **LLM extraction without legal judgment**    | The model can extract the right passage but misclassify its legal significance                     | Kept human review as a required promotion step before draft YAML becomes canonical data        |
| **Over-reliance on record-level confidence** | A single case-level quality score hides which exact propositions are reliable                      | Shifted reliability toward proposition-level source passages, review status, and quote support |
| **Completeness risk**                        | Passing quote validation proves a quote exists, not that all relevant markets were found           | Added evaluation fixtures and precision/recall benchmarking, but coverage remains limited      |
| **Long Phase II decision coverage** | Large decisions split legal analysis across hundreds of pages, so a single extraction pass can miss theories, remedies, or repeated unit-level findings | Added page-range extraction, range planning, multi-focus extraction, unit assessment, and draft merging before human review |
| **Schema drift risk**                        | As the legal model evolves, old YAML records can silently become inconsistent                      | Centralised validation through Pydantic schemas and CI checks                                  |
| **Prototype-to-product gap**                 | Local scripts can work without being a usable deployed system                                      | Containerised the local stack with Docker Compose and identified deployment-readiness gaps     |


The main lesson: the hard part is not only extracting text from decisions. The hard part is turning authority documents into structured legal propositions without losing source traceability, legal nuance, or reviewability.

---

## 8. Plan to Deployment

This is not a rigid roadmap. It is the sensible order of priority based on the current gaps.


| Priority | Workstream                      | What to do                                                                                                                                               | Implementer / role                                                                 | Why it comes now                                                                                                  |
| -------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| **1**    | **Data quality baseline** ✅ Done | Completed source-verification pass: removed Illumina/Grail, corrected bad locators/quotes, verified 6 canonical records, seeded Neo4j, tagged `data-baseline-v1` | **Human + ChatGPT + Claude** — human made legal calls; ChatGPT guided the sequence; Claude made targeted repo fixes | Completed first because scaling bad data would undermine the product |
| **2**    | **Ingestion CLI** ✅ v1 Done | Added `apps/api/scripts/ingest_case.py` to orchestrate source caching, extraction, draft validation, source integrity checks, and review report generation; supports `--batch-by-section` | **Claude + human** — Claude implemented the CLI/tests; human tested and reviewed workflow fit | v1 works on existing case data; next proof point is running it on a genuinely fresh case |
| **3**    | **Fresh-case ingestion proof** ✅ Done | Ran the CLI on `eu_sika_dry_mix_2019` (M.9276) from source URL to draft YAML, review report, and LLM triage; identified and fixed outcome-passage misuse and missing geographic markets; promoted to canonical | **Human + Claude** — human made legal calls on promotion items; Claude ran the pipeline and made targeted fixes | Proved the ingestion CLI works on a genuinely fresh case; revealed outcome-passage and geographic-market gaps that shaped the promotion checklist |
| **3a**   | **LLM review / triage** ✅ v1 Done | Added `apps/api/scripts/review_draft.py`; integrated as optional `--llm-review` flag in `ingest_case.py`; 38 tests; correctly identified outcome-passage misuse and missing geographic markets on first real run | **Claude + human** — Claude implemented; human validated findings against source PDF | Reduces manual review burden by flagging semantic issues before human promotion review |
| **4**    | **Human review workflow** ✅ Done | Created `docs/human-promotion-checklist.md` with promotion prerequisites, review steps, definition_status mapping, source_role guidance, outcome-passage rules, and pre/post-promotion commands | **Human + Claude** — human set policy decisions; Claude drafted the checklist | Formalises the review loop so cases can be promoted consistently and auditably |
| **5**    | **Review learning logs** ✅ v1 Done | Captured human-review deltas from draft → reviewed draft → canonical record; categorised correction types; proposals aggregated and output to `data/review_learning/proposals/` | **Claude + human + ChatGPT** — Claude implemented log capture and proposal aggregation; human validated categories | This is how manual review scope shrinks over time without weakening source-first reliability                      |
| **6**    | **Evaluation expansion** ✅ v1 started | Benchmark now covers 6 cases and 6/6 PASS. | **Human + Claude** — human created gold judgments for Sika/Dry Mix; Claude wired up eval fixtures and benchmark config | Scaling requires knowing when extraction quality regresses                                                        |
| **7**    | **Small-batch case coverage** ✅ Done | Promoted additional EC cases through the full loop; fresh-case runs exposed recurring gaps around geographic markets, outcome metadata, and source-role classification | **Human + ChatGPT + Claude** — human makes legal promotion decisions; ChatGPT helps triage; Claude runs cleanup and promotion tooling | Proved the loop can scale beyond one fresh case while converting each review into reusable pipeline learning |
| **8**    | **Central market-definition rule registry** ✅ v1 Done | Registry exists at `data/pipeline_rules/market_definition_rules.yaml`. | **Claude + human + ChatGPT** — Claude implements registry/checks; human approves legal policy; ChatGPT helps structure rules | Prevents rule drift as the pipeline accumulates legal-meaning rules from review learning logs |
| **8a**   | **Case promotion pipeline** ✅ v1 Done | Added `promote_case_pipeline.py` to run target-draft integrity, safe promotion, canonical gates, graph seed, review learning log, and apply-learning proposals in one fail-fast workflow | **Claude + human + ChatGPT** — Claude implemented/tests; human validated workflow; ChatGPT shaped safety requirements | Prevents repeated raw-copy promotion mistakes and makes final promotion repeatable |
| **8b**   | **Multi-focus extraction** ✅ v1 Done | Added focused extraction for outcome metadata, theories of harm, remedies/commitments, and repeated-unit assessments, alongside market definition | **Claude + human + ChatGPT** — Claude implemented; human validated legal usefulness; ChatGPT shaped the abstraction | Prevents the pipeline from tunnelling into market definition and makes long Phase II decisions structurally representable |
| **8c**   | **Long-decision assembly** ✅ v1 Done | Added page-range extraction, extraction-range planning, and draft merging so multiple focus-specific passes can become one reviewable draft | **Claude + human + ChatGPT** — Claude implemented scripts/tests; human reviewed outputs; ChatGPT guided sequencing | Long decisions need controlled windows and assembly before legal review; this is the bridge from extraction experiments to reviewable drafts |
| **8d**   | **Hard-case promotion** ✅ v1 proven | Promoted `eu_bayer_monsanto_2018` as the first long Phase II hard case ; `docs/hard-case-review-checklist.md` added as a durable pre-promotion gate | **Human + Claude** — human made legal promotion decisions; Claude ran pipeline, diagnostics, and source-integrity cleanup | Proves the generalized pipeline can handle a full-complexity Phase II decision end-to-end, not just Phase I cases |
| **8e**   | **Controlled corpus expansion** ✅ started | Promoted the first controlled-expansion cases after the hard-case milestone: `eu_cochlear_oticon_medical_2023` as a clean EC Phase I smoke test and `uk_viasat_inmarsat_2023` as the first CMA Phase II case with market definitions and dismissed theories of harm | **Human + ChatGPT + Claude** — human made legal promotion decisions; ChatGPT helped prioritise/review; Claude ran pipeline/tooling | Proves the generalized pipeline can now add non-hard-case corpus coverage across jurisdictions without new infrastructure |
| **8f**   | **EC/CMA paired-case expansion** ✅ Done | Promoted `eu_viasat_inmarsat_2023` as the EC counterpart to the promoted CMA Viasat/Inmarsat case, creating the first same-transaction EC/CMA Phase II pair | **Human + ChatGPT + Claude** — human made promotion calls; ChatGPT reviewed legal structure and failure modes; Claude ran extraction, cleanup, and promotion tooling | Gives useful cross-jurisdiction coverage without building comparison infrastructure yet; also exposed the need for stronger one-shot review-readiness checks |
| **8g**   | **Review-readiness architecture** ✅ v1 proven | Added profile-driven coverage/readiness checks and proved them on `us_tapestry_capri_2024`: the first run failed safely, the US court profile exposed missing theory/source-role issues, the corrected run passed readiness, and the case promoted cleanly | **Claude + human + ChatGPT** — Claude implemented scripts/tests; human validated legal policy and promotion; ChatGPT helped define failure modes and profile design | Reduces the previous 3–4 prompt repair loop per case and proves the pipeline can handle a new document type without a separate US pipeline |
| **8h**   | **One-command controlled-case runner** ✅ proven | `apps/api/scripts/run_controlled_case.py` wraps seed creation, source fetch/cache, profile selection, coverage planning, focused extraction, draft merging, and readiness packet generation; `eu_booking_etraveli_2023` proved the runner can produce READY_FOR_HUMAN_REVIEW and promote a merged draft through the updated promotion workflow | **Claude + human + ChatGPT** — Claude implemented orchestrator/tests and merged-draft promotion support; human validated workflow and promotion; ChatGPT guided scope and failure handling | Turns the multi-script chain into a repeatable operator workflow; next step is scaling strategy and cost-controlled corpus ingestion |
| **8i**   | **Broad case index** ✅ v1 started | Added a lightweight `data/case_index/` layer, `data/concepts/` taxonomy seed, graph seed support for indexed cases/concept refs, and read-only API exposure through `/indexed-cases` and `/search/all`; first 8 metadata-only indexed cases and 7 concept nodes load cleanly | **Claude + human + ChatGPT** — Claude implemented schema/API/graph support; human validates source policy and priority corpus; ChatGPT keeps the indexing strategy product-focused | Gives the platform broad discoverability quickly and cheaply without pretending every case is a fully reviewed canonical record |
| **✅ Done** | **Semantic search + entity-centric graph** | Postgres+pgvector replacing Neo4j; `GET /search/semantic`, `GET /graph/markets`, `GET /graph/theories`; Market Map + Theory Map in frontend; 26 cases embedded and confirmed | **Claude + human** — Claude implemented all backend + frontend; human validated working end-to-end | Turns static YAML records into a research surface that scales beyond keyword matching |
| **In progress** | **Bulk Phase I EU corpus expansion** | 459 Phase I drafts generated from Gemini 2.5 Flash bulk run; 496 simplified-procedure skips; 35 failures; ~1,171 cases not yet processed | **Claude + human** — Claude built pipeline/runner; human triages and promotes | First bulk proof that the pipeline can process the EC corpus at scale |
| **Next** | **Bulk draft triage + promotion** ← Current | Spot-check 5–10 random drafts; batch-promote clean Phase I extractions; investigate 35 failures; resume run on remaining ~1,171 cases; re-run embedding indexer after each promotion batch | **Human + Claude** — human spot-checks legal quality; Claude automates promotion and indexing | Turns 459 raw drafts into canonical data that improves search quality |
| **Next+1** | **Simplified procedure display** | Add graceful case-page variant for index-only entries (parties, date, sector, outcome, "Cleared under simplified procedure — no public market analysis"); ~496 identified from bulk run | **Claude + human** | Prevents empty-looking pages for the majority of EC Phase I decisions |
| **Next+2** | **Production deploy** | Railway (FastAPI + Postgres with pgvector) + Vercel (Next.js); single `API_KEY` auth; CORS origin whitelist; `ENVIRONMENT` config; delete dead Neo4j code | **Claude + human** — Claude prepares deploy config; human controls credentials and hosting | The platform is locally functional but not publicly accessible |
| **Parallel** | **Eval workflow hygiene** | Ensure generated `data/evals/results/*` outputs do not pollute git status; keep eval results as workflow artifacts only | **Claude + human** | Keeps repo clean and avoids accidental commit of eval artifacts |
| **9**    | **Frontend productisation**     | Make the UI usable for real research: cross-case filters (market name, theory type), source cards, simplified procedure pages, case comparison | **Claude + human** — Claude implements; human tests as target user | With 200+ canonical cases and semantic search, the UI becomes the bottleneck |
| **10**   | **CMA + US corpus expansion**   | Run bulk extraction for CMA Phase 1/2 reports and US court opinions; use `cma_report` and `us_court_opinion` profiles already implemented | **Human + Claude** — human selects priority corpus; Claude runs bulk tooling | EC-first corpus is now proved; CMA and US add cross-jurisdiction coverage |


**Near-term deployment target:** a private research demo with semantic search, entity-centric graph, 200+ canonical records (promoted from Gemini bulk extraction), graceful simplified-procedure pages, and no public write access. Hosted on Railway + Vercel.

**Not yet needed:** heavy permissions, collaboration features, automated document discovery, or advanced legal weighting. Those only matter after the source-first ingestion and review loop is stable.

---

## 9. Interview Explanation

### How to explain this in a 60–90 second pitch

> CompMap is a research tool for competition lawyers. It takes the actual written decisions from merger control authorities — EU Commission, UK CMA, US courts — and converts them into structured, searchable data.
>
> The problem it solves: today, if you're a lawyer trying to find how the Commission defined the product market in a gaming case five years ago, you read PDFs manually. CompMap lets you search for that, and when you find it, you can see the exact paragraph from the decision that supports it.
>
> The core design principle is source-first. Every proposition — every market definition, theory of harm, or evidentiary finding — has to trace back to a real quote in a real document. We validate every quote against the actual extracted text before it enters the database. If the quote isn't there, it doesn't go in.
>
> Today we have 26 source-verified canonical case records, 459 Gemini-extracted Phase I drafts ready for promotion, and a broad metadata index covering several thousand EC cases. The canonical layer includes the first promoted long Phase II conditional-clearance hard case, the first same-transaction EC/CMA Phase II pair, the first promoted US federal court opinion, and the first case promoted through the one-command controlled-case runner. The pipeline began with market-definition extraction, but it now supports a more complete merger-control record: outcome metadata, theories of harm, remedies and commitments, source passages, and repeated unit-level findings for long decisions.
>
> We recently added semantic search using Postgres with pgvector and Google Gemini embeddings — so you can search "online advertising" and find cases that used "digital display advertising" or "programmatic ad serving". We also built an entity-centric graph: instead of seeing one case's neighborhood, you can open the Market Map, see all 200+ product markets across the corpus as nodes sized by frequency, click one, and instantly get every case that considered it with the relevant source passages.
>
> The system is not production-deployed yet. It runs locally with Docker, with a FastAPI backend, a Postgres+pgvector vector store, and a Next.js frontend. The main gap between now and a deployable product is promoting the bulk drafts to get to 200+ canonical cases, and deploying to Railway and Vercel.
>
> The near-term value is as a research accelerator: a lawyer gets a structured head start on precedent, with source citations already pulled, rather than starting from a blank search.

---

---

## 10. Maintenance Note

This document should be updated after any of the following:

- **Schema changes** — new fields, enum values, or model restructuring that affect what the pipeline can represent.
- **New focus modes or extraction scripts** — any addition to the extraction or assembly stages.
- **Promoted flagship cases** — especially first-of-type cases (new jurisdiction, new procedure stage, new decision length).
- **Deployment changes** — any move from local to staging or production.
- **Roadmap shifts** — when a "Next" item completes or a new priority displaces the current one.
- **Detailed diagnostics** - detailed diagnostics should live in docs/hard-case-diagnostics.md

Keep updates concise. This document is for product discussions, not for raw logs or case-specific extraction statistics.

---

*File paths and scores reflect the repository as of June 2026. The ingestion pipeline design is in `docs/ingestion-design.md`. Long-case and hard-case diagnostics are tracked in `docs/hard-case-diagnostics.md`. The hard-case pre-promotion checklist is in `docs/hard-case-review-checklist.md`. The completed data baseline and any future source-quality notes are tracked in `docs/data-quality-notes.md`. Broad index records live in `data/case_index/`, reusable concept taxonomy lives in `data/concepts/`. Canonical case data is served via `/cases` and `/search`; semantic search via `/search/semantic`; entity-centric graph via `/graph/markets` and `/graph/theories`. Postgres+pgvector replaced Neo4j in June 2026; `neo4j_client.py`, `graph_service.py`, and `graph/seed_graph.py` remain as dead code pending deletion.*