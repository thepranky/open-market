# CompMap — Project Pipeline Explainer

*For a lawyer-builder preparing for product discussions. Based on actual repository state as of May 2026.*

---

## 1. Project Overview

**CompMap** is a source-first competition law research pipeline. It takes real merger control decisions from the EU Commission, UK CMA, and US FTC/DOJ and converts them into structured, searchable data — where every legal proposition links back to a specific paragraph and quote in the underlying authority document.

**Practical use case:** A lawyer researching market definition precedent in a media/gaming merger can search CompMap and find: which product markets were considered, what definition status was reached (defined, discussed, left open), what theories of harm were raised, and exactly which passage of which decision supports each finding — with page and paragraph numbers.

**Current state:** This is a v0 first slice. There are 7 source-verified case records. A first ingestion CLI now orchestrates fetch/cache, extraction, draft validation, source integrity checks, LLM review triage, and review report generation. The first genuinely fresh case (`eu_sika_dry_mix_2019`) has been promoted to canonical. Frontend cleanup is deferred.

---

## 2. Tech Stack


| Layer                      | Technology                                                              | Role in this project                                                                    | Why it matters                                                                         |
| -------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Data store (canonical)** | YAML files (`data/cases/**/*.yaml`)                                     | Single source of truth for all case records                                             | Human-readable, git-diffable, easy to review and correct                               |
| **Schema / validation**    | Pydantic 2.9 (`apps/api/app/models/case.py`)                            | Enforces structure, enums, required fields on every YAML load                           | Prevents malformed records from reaching the API                                       |
| **Backend API**            | FastAPI + Python 3.12 (`apps/api/`)                                     | Serves cases, search, graph queries over HTTP                                           | Exposes structured data to the frontend; validates on load                             |
| **Graph database**         | Neo4j 5.22 Community (`graph/`)                                         | Stores cases as a graph of 13 node types, 15 relationship types                         | Enables cross-case traversal: "which cases in gaming considered distribution markets?" |
| **Frontend**               | Next.js 14, React 18, TypeScript, Tailwind (`apps/web/`)                | Search UI, case detail pages, source passage display                                    | Makes the data usable without direct API calls                                         |
| **PDF / text extraction**  | pypdf, pdfplumber (`apps/api/app/utils/pdf_extractor.py`)               | Extracts and caches text from authority PDFs                                            | Required before any quote can be validated or extracted                                |
| **LLM extraction**         | Anthropic SDK / Claude (`apps/api/scripts/extract_case_from_source.py`) | AI-assisted extraction of markets, theories, passages from source text                  | 3,790-line script; core of the semi-automated pipeline                                 |
| **Validation scripts**     | Python CLI scripts (`apps/api/scripts/`)                                | 9 scripts covering link checking, quote integrity, schema validation, eval benchmarking | These are the quality gates; they enforce the "source-first" principle                 |
| **Evaluation fixtures**    | YAML gold files + JSON eval reports (`data/evals/`)                     | Benchmark extraction quality against curated ground-truth records                       | Enables measurable precision/recall for extraction                                     |
| **Containerisation**       | Docker Compose (`docker-compose.yml`)                                   | Runs neo4j, api, web, and a one-off seed container together                             | Full local stack in one command; not yet production-deployed                           |
| **CI**                     | GitHub Actions (`.github/workflows/`)                                   | Runs schema validation + a CI-safe eval benchmark subset on every push                  | Catches regressions without requiring Neo4j or live PDFs                               |


---

## 3. Current Pipeline

The pipeline has two distinct parts: **manual authoring** (how the baseline cases were built) and a **semi-automated ingestion flow**. The semi-automated flow has now been proven on a genuinely fresh EC case (`eu_sika_dry_mix_2019`).

### Stage 0 — Case selection (manual)

- **What:** Decide which case to add; identify the authoritative source documents.
- **Inputs:** Authority websites (EC competition registry, CMA decisions page, US court PACER).
- **Outputs:** Case identifier (`case_id` convention: `{jurisdiction}_{parties}_{year}`) and a list of document URLs.
- **Status:** Fully manual. No automation exists for discovery or prioritisation.

---


- **What:** Fetch the PDF decision and extract its text for downstream use.
- **Script:** `apps/api/app/utils/pdf_extractor.py`
- **Inputs:** URL of authority PDF.
- **Outputs:** Cached JSON text file in `data/source_text/` (e.g., `eu_microsoft_activision_2023_decision.json`).
- **Competition law context:** The source text is the evidentiary foundation. If the wrong document is fetched, all downstream extractions will be wrong. This was confirmed during the data baseline pass: valid URLs were not enough; each source had to be checked against the actual authority document.
- **Status:** Semi-automated; cache is checked before re-fetching.

---


- **What:** Create the skeleton YAML file with case metadata.
- **Files written:** `data/cases/{jurisdiction}/{case_id}.yaml`
- **Schema:** Validated against `CaseRecord` Pydantic model (`apps/api/app/models/case.py`).
- **Key fields set at this stage:** `case_id`, `case_name`, `jurisdiction`, `authority`, `decision_date`, `procedure_stage`, `sector`, `parties`, `outcome`.
- **Status:** Manual. For the baseline cases, this was done by hand.

---

### Stage 3 — LLM-assisted extraction

- **What:** Claude reads the cached source text and proposes: product markets, geographic markets, theories of harm, source passages (with quotes and page numbers), remedies, case history.
- **Script:** `apps/api/scripts/extract_case_from_source.py` (3,790 lines)
- **Inputs:** Cached source text JSON from `data/source_text/`; existing case YAML (if any) for reconciliation.
- **Outputs:** Draft YAML in `data/drafts/{jurisdiction}/` (e.g., `eu_sika_mbcc_2023.market_definition.draft.yaml`) and a reconciliation report JSON.
- **Competition law context:** The script extracts structured legal propositions — what product market was considered, what definition status was reached, what evidence the authority relied on, with direct quotes.
- **Status:** Semi-automated. Script runs with a single command; output requires human review before promotion to `data/cases/`.

---

### Stage 4 — Quote validation gate

- **What:** Every quote snippet proposed by the LLM is checked against the actual extracted source text. If a quote cannot be found, it is rejected — it is not written to YAML.
- **Script:** `apps/api/scripts/check_source_integrity.py` (672 lines); key function: `quote_found_in_text(quote, text)` using fuzzy matching.
- **Inputs:** Draft YAML; cached source text.
- **Outputs:** Pass/fail report; passages that failed are excluded from the draft.
- **Why this matters:** LLMs hallucinate quotes. This gate is the primary technical safeguard against fabricated citations appearing in the record. The gate was built after a fabricated source URL was discovered in `us_microsoft_activision_2023` during manual authoring (see `docs/ingestion-design.md`).
- **Status:** Automated check; runs as part of script and in CI.

---

### Stage 5 — Source link validation

- **What:** HTTP GET on every source document URL to confirm it resolves to a real, correctly-typed document (not a broken link, redirect, or portal page).
- **Script:** `apps/api/scripts/check_source_links.py` (120 lines)
- **Inputs:** YAML `source_documents` section.
- **Outputs:** OK / broken / portal classification per URL.
- **Status:** Automated check; blocking — broken URLs must be resolved before a record can be committed.

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
- **Status:** Manual. This is the current reliability bottleneck.

---

### Stage 7a — Review learning log

- **What:** Capture the delta between the original draft, the LLM review, the human-reviewed draft, and the promoted canonical record.
- **Goal:** Turn repeated human corrections into reusable extraction rules, validator warnings, prompt updates, and eval fixtures.
- **Inputs:** `data/drafts/...draft.yaml`, `data/drafts/...llm_review.json`, promoted `data/cases/...yaml`.
- **Outputs:** Review learning logs under `data/review_learning/`, with categorised correction types such as `definition_status_mapping`, `source_role_correction`, `support_linkage_correction`, `outcome_passage_misuse`, and `missing_market_added`.
- **Status:** Next to build. This should be auditable and rule/eval-driven, not model fine-tuning.

---

### Stage 8 — API serving

- **What:** FastAPI loads all validated YAML from `data/cases/` into an in-memory LRU cache on startup. Routes: `GET /cases`, `GET /cases/{id}`, `GET /search?q=`, `GET /graph/case/{id}`.
- **Files:** `apps/api/app/services/case_service.py`, `apps/api/app/routers/`.
- **Status:** Fully implemented and working.

---


- **What:** Seeds the Neo4j graph database from the canonical YAML records. Creates 13 node types (Case, Authority, Jurisdiction, Party, Sector, ProductMarket, GeographicMarket, TheoryOfHarm, Outcome, SourceDocument, SourcePassage, Remedy, SimilarCase) and 15 relationship types.
- **Script:** `graph/seed_graph.py` (312 lines). Run via `docker compose --profile seed run seed`.
- **Inputs:** `data/cases/**/*.yaml`; Neo4j instance.
- **Outputs:** Populated Neo4j database with constraints and full-text indexes.
- **Status:** Implemented and verified after the data baseline pass. The current 7-case dataset seeds cleanly into Neo4j. Optional — the API falls back to YAML-based queries if Neo4j is unavailable.

---

### Stage 10 — Evaluation / benchmarking

- **What:** Measures extraction quality by comparing LLM-extracted drafts against manually-curated gold standard records. Computes precision, recall, and F1 per market type and checks that all quotes passed validation.
- **Scripts:** `evaluate_extraction.py`, `run_eval_benchmark.py`, `create_gold_draft.py`.
- **Benchmark config:** `data/evals/benchmark.market_definition.yaml`; CI-safe subset: `benchmark.market_definition.ci.yaml`.
- **Example result (eu_microsoft_activision_2023):** Product market F1 = 1.0 (2/2 true positives, 0 false positives, 4 unjudged candidates outside the gold subset). Quote validity: 9/9 passed.
- **Status:** Implemented for 2 cases. Gold standard is partial (not full-case coverage).

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
| **Remedies / outcome**            | `outcome` (enum) + `remedies[]`                                  | Decision result and any behavioural or structural conditions                                                 |
| **Procedural history**            | `case_history` object with timeline events                       | Phase transitions, referrals, appeals, annulments                                                            |
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
| **Automation**                  | 5/10      | Ingestion CLI + LLM triage exist; first fresh case promoted; corpus expansion still manual-heavy                  | Build out review-learning pipeline; increase automation coverage for corpus expansion       |
| **Scalability**                 | 3/10      | In-memory YAML search works for 7 cases; Neo4j graph seeds cleanly but the corpus is still too small              | Add proper database indexing and move search to Neo4j full-text; increase case count to 50+ |
| **Accuracy / source grounding** | 7/10      | Quote validation gate is real and enforced; eval results on 2 cases show F1 = 1.0 on partial gold                 | Expand gold standard coverage; add completeness checks for missed markets                   |
| **Legal reliability**           | 5/10      | Source passage links are genuine; but no formal legal weighting, definition status can be misclassified by LLM    | Add structured legal review checklist; separate allegation vs. finding at schema level      |
| **Maintainability**             | 7/10      | YAML is readable and git-diffable; Pydantic schema enforces structure; scripts are well-factored                  | Document the schema evolution policy; add migration tooling for schema changes              |
| **Deployment readiness**        | 3/10      | Docker Compose works locally; no production deployment, no auth, no rate limiting, no monitoring                  | Add authentication, environment config management, and a staging deploy                     |
| **User-facing usefulness**      | 5/10      | Frontend exists and shows markets, theories, sources; but 7 cases is too few for real research value; frontend cleanup still needed | Expand case count; add cross-case filtering by market name and theory type                  |
| **Evaluation / test coverage**  | 6/10      | Eval framework is real with precision/recall metrics; gold standard exists for 2 cases; CI runs benchmark subset  | Expand gold standard to all 7 canonical cases; add completeness recall (not just precision-on-gold)   |


---

## 7. Issues Faced During Pipeline Build


| Issue faced                                  | Why it mattered                                                                                    | What we did                                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Hallucinated or unsupported citations**    | An AI-generated legal record is unsafe if the quote or source does not actually exist              | Added quote validation against extracted source text; rejected passages that cannot be found   |
| **Wrong or unstable authority links**        | A valid URL can still point to the wrong document, portal page, appeal judgment, or updated source | Added source link checks and surfaced known data quality issues for manual correction          |
| **LLM extraction without legal judgment**    | The model can extract the right passage but misclassify its legal significance                     | Kept human review as a required promotion step before draft YAML becomes canonical data        |
| **Over-reliance on record-level confidence** | A single case-level quality score hides which exact propositions are reliable                      | Shifted reliability toward proposition-level source passages, review status, and quote support |
| **Completeness risk**                        | Passing quote validation proves a quote exists, not that all relevant markets were found           | Added evaluation fixtures and precision/recall benchmarking, but coverage remains limited      |
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
| **5**    | **Review learning logs** ← Next | Capture human-review deltas from draft → reviewed draft → canonical record, then convert repeated corrections into reusable rules, prompt updates, validator warnings, and eval fixtures | **Claude + human + ChatGPT** — Claude implements log capture and rule extraction; human validates categories; ChatGPT helps interpret patterns | This is how manual review scope shrinks over time without weakening source-first reliability                      |
| **6**    | **Evaluation expansion**        | Add gold fixtures for all current cases and track precision, recall, quote validity, and missed-market risk                                              | **Human + Claude + ChatGPT** — human creates gold judgments; Claude implements eval logic; ChatGPT helps interpret results | Scaling requires knowing when extraction quality regresses                                                        |
| **7**    | **Case coverage**               | Expand from 7 cases to a useful seed corpus, likely 50–100 high-value merger decisions across EU, UK, and US                                             | **Human + ChatGPT + Claude** — human selects/prioritises cases; ChatGPT assists research triage; Claude improves batch ingestion | The product only becomes useful once cross-case comparison works                                                  |
| **8**    | **Search and graph hardening**  | Improve cross-case filtering by market, sector, authority, theory of harm, outcome, and source passage                                                   | **Claude + human** — Claude implements backend/search/graph improvements; human validates usefulness for legal research | This is the core user value beyond reading one YAML record                                                        |
| **9**    | **Production API readiness**    | Add auth, environment config, rate limiting, logging, monitoring, and proper startup/restart behaviour                                                   | **Claude + human** — Claude implements technical hardening; human decides deployment constraints and reviews security posture | FastAPI production deployments need security, restart handling, replication/memory planning, and pre-start checks |
| **10**   | **Frontend productisation**     | Make the UI usable for real research: source cards, filters, case comparison, and clear citation trails                                                  | **ChatGPT + Claude + human** — ChatGPT helps product/spec design; Claude implements; human tests as target user | Lawyers need an interface, not just validated data                                                                |
| **11**   | **Database / graph operations** | Decide whether YAML remains canonical while Neo4j is derived, then add backup, monitoring, and seed/rebuild procedures                                   | **Claude + human** — Claude implements operations scripts; human chooses architecture and recovery expectations | Neo4j can support traversal, but production use needs monitoring and operational discipline                       |
| **12**   | **Staging deploy**              | Deploy a private staging version with separate dev/staging/prod env config and a small reviewed corpus                                                   | **Claude + human** — Claude prepares deploy config; human controls credentials, hosting choices, and acceptance testing | Next.js/FastAPI/Neo4j need environment separation before external users touch it                                  |


**Near-term deployment target:** a private research demo with reviewed data, source-backed case pages, reliable search, and no public write access.

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
> Today we have 7 source-verified case records across the EU, UK, and US, built with a combination of AI-assisted extraction using Claude and human legal review. The first fresh case has now completed the full loop — from source fetch through LLM extraction, LLM review triage, human review, and canonical promotion. The next step is review-learning logs: capturing the delta from each human correction so it becomes a reusable extraction rule, validator warning, or eval fixture — that is how the manual review workload shrinks over time without sacrificing source-first reliability.
>
> The system is not production-deployed yet. It runs locally with Docker, with a FastAPI backend, a Neo4j graph layer, and a Next.js frontend. The main gap between now and a deployable product is ingestion automation, broader case coverage, and access control.
>
> The near-term value is as a research accelerator: a lawyer gets a structured head start on precedent, with source citations already pulled, rather than starting from a blank search.

---

*File paths and scores reflect the repository as of May 2026. The ingestion pipeline design is in `docs/ingestion-design.md`. The completed data baseline and any future source-quality notes are tracked in `docs/data-quality-notes.md`.*