# ROADMAP

Phased plan from current state to production. Each row is one spec-sized change (one PR).
See [`.cursor/rules/meridian.mdc`](.cursor/rules/meridian.mdc) for spec-driven workflow.

Legend: ✅ done · (no mark) open. Item numbers are stable IDs — completed rows keep their
number even when regrouped, so existing spec / PR / DDR cross-references stay valid.

---

## Phase 0 — Docs ✅

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 0.1 | Doc consolidation | `docs/`, `README.md`, `CLAUDE.md` | Single source of truth for onboarding | ✅ Done |
| ✅ 0.2 | Layout spec + DDR-0 | `docs/specs/completed/2026-06-24-restructure-layout.md`, `ddr-0-repo-layout.md` | Clear boundaries before deep-dives | ✅ Done |

## Phase 1 — Restructure ✅

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 1.1 | API packages (`cases/`, `screening/`, `shared/`) | `apps/api/app/` | Learnable module boundaries | ✅ Done (PR 1) |
| ✅ 1.2 | Script subdirs | `apps/api/scripts/` | Pipeline discoverability | ✅ Done (PR 2) |
| ✅ 1.3 | Web feature folders | `apps/web/src/features/` | Frontend boundaries | ✅ Done (PR 3) |

## Phase 2 — Understand

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 2.A | DDR-A data contracts + source integrity | `ddr-a-data-contracts.md` | Contract and grounding model understood | ✅ Done |
| ✅ 2.B | DDR-B extraction pipeline | `ddr-b-extraction-pipeline.md` | Draft → promote pipeline, scripts, review loop | ✅ Done |
| 2.C–2.I | DDR study set: original deep-dives | `ddr-c-search-graph.md` through `ddr-i-infrastructure.md` | Defensible understanding of search, screening, frontend, CI, and infra | Review/study; keep open until reviewed |
| 2.J–2.P | DDR study set: pipeline + architecture decisions | `ddr-j-dual-extraction.md` through `ddr-p-gemini-screening-tools.md` | Understand recent extraction, promotion, grounding, graph, catalog, screening, and LLM tool decisions | Review/study; keep open until reviewed |

## Phase 3 — CI ✅

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 3.1 | Canonical case schema gate on PR | `.github/workflows/data-contracts.yml`, `validate_cases.py` | Canonical YAML breaks silently today | ✅ Done (#19) |
| ✅ 3.2 | Jurisdiction push tier on PR | `jurisdiction-verification.yml`, `run_jurisdiction_verification.py` | Screening regressions not gated on merge | ✅ Done (#19) |
| ✅ 3.3 | Case index schema gate on PR | `validate_case_index.py` | Index YAML drifts from `CaseIndexEntry` | ✅ Done (#19) |
| ✅ 3.4 | Link DDR-A from case-research doc | `docs/architecture/case-research.md` | Onboarding misses contract reference | ✅ Done (#19) |
| ✅ 3.5 | Web lint + build in CI | new `web-ci.yml` | Frontend breaks undetected | ✅ Done — [spec](docs/specs/completed/2026-06-25-ci-gaps.md): path-filtered Node-20 lint+build; baseline `.eslintrc.json` (`next/core-web-vitals` + `@typescript-eslint` plugin) + 2 entity escapes |
| ✅ 3.6 | Ruff in CI | `api-ci.yml` | Style/errors only caught locally | ✅ Done — [spec](docs/specs/completed/2026-06-25-ci-gaps.md): parallel `lint` job; `pyproject.toml` ruff config (E402 ignored in `scripts/`+`tests/`); 236 baseline errors cleared |
| ✅ 3.7 | Benchmark artifacts | `api-ci.yml` | Eval trends discarded | ✅ Done — [spec](docs/specs/completed/2026-06-25-ci-gaps.md): `upload-artifact` step (`if: always()`, 90-day) for benchmark JSON+MD. Concurrency-cancel (gap B) bundled into `web-ci.yml`+`api-ci.yml` |
| ✅ 3.8 | CI robustness follow-ups (deferred by #21) | `api-ci.yml`, `data-contracts.yml`, `jurisdiction-verification.yml` | #21 closed 3.5–3.7 but flagged robustness gaps as explicit non-goals ([ci-gaps spec](docs/specs/completed/2026-06-25-ci-gaps.md) §"Is CI complete?") | ✅ Done (folded into the 4.10 PR): **A** path-filter `api-ci.yml` (`apps/api/**`,`data/**`,workflow); **B** `concurrency: cancel-in-progress` added to the two data workflows; **C** pip caching (`setup-python cache: pip`) on all API jobs. **F** (`ruff format --check`) **not adopted** — would reformat 109 files; the project gates lint only (spec non-goal). **D** frontend tests / **E** benchmark F1-trend assertion remain larger intentional non-goals (E ties 5.3/5.5) |

## Phase 4 — Refine (infrastructure & shared)

Cross-cutting refactors and contract clean-ups that aren't tied to one product surface.

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 4.2 | `data_jurisdictions_path` config | `app/shared/core/config.py` | Path derived from cases path | Explicit env var |
| 4.3 | Rename overloaded symbols | `Juris.tsx`, home stats | Naming collision | `CaseRegulatorBadge`, `case_regulator_count` |
| ✅ 4.5 | Case YAML semantic lint | `semantic_lint.py`, `lint_case_semantics.py` | Lawyer rules not enforced by Pydantic | ✅ Done (#20) — [spec](docs/specs/completed/2026-06-25-case-semantic-lint.md): deterministic gate (complaint-only markets not `defined`; dangling `supports_*` refs). Outcome-passage rule dropped (prose judgement; `section` on 9/7566 passages) → Stage 5a critic + dual extraction 5.9 |
| 4.8a | Audit `SourceDocument.url` usage | `case.py`, loaders, integrity scripts, web evidence UI, `data/cases/` | Need to know which records and callers still depend on generic URL fallback before migration | Add audit command/report only; no schema or data removal |
| 4.8b | Migrate source-document writers/data off generic `url` | extraction/promote writers, `data/cases/`, tests | New records should use `pdf_url` / `case_page_url` explicitly so fallback stops growing | Backfill existing canonical records where source role is clear; preserve read compatibility |
| 4.8c | Remove `SourceDocument.url` fallback | `case.py`, web types/UI, integrity scripts | Legacy field can go only after callers and data no longer rely on it | Remove field and fallback branches; keep validation proving no canonical record uses `url` |
| 4.9 | Printed-folio detection in PDF cache | `pdf_extractor.py`, `source_text/` | EC folio vs PDF-index offset is manual | Optional folio parse when building page cache |
| ✅ 4.10 | Regroup `scripts/cases/` by stage | `apps/api/scripts/cases/` | Flat folder mixes discovery / extract / review / promote / integrity (ddr-b Q3a) | ✅ Done — [spec](docs/specs/completed/2026-06-25-regroup-cases-scripts.md): 7 buckets (`discovery/ extract/ review/ promote/ integrity/ evals/ embeddings/`); 4 discovery scripts renamed to `scrape_{eu,uk}_index` / `resolve_{eu,uk}_pdf_urls`; no behaviour change. Not path-only — fixed depth-anchored `__file__` arithmetic, cross-bucket flat imports, subprocess paths, and test imports |

## Architecture

Deep-module changes from the 2026-06-29 architecture review. Rows reuse existing IDs where they replace older open roadmap rows, so the work stays DRY and traceable.

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 4.1 | Jurisdiction screening application module | `app/screening/services/screening_application.py`, `app/screening/routers/jurisdictions.py`, `threshold_engine.py` | `jurisdictions.py` mixes HTTP routing, catalog loading, deal adaptation, screening orchestration, verification joins, and response projection; `threshold_engine.py` should remain focused on threshold evaluation | [spec](docs/specs/2026-06-29-jurisdiction-screening-application.md), [DDR-O](docs/architecture/decisions/ddr-o-jurisdiction-screening-application.md) |
| 4.4 | Graph neighborhood projection module | `app/cases/services/graph_projection.py`, `app/cases/routers/graph.py`, `graph/seed_graph.py`, `neo4j_client.py` | Node IDs, edge types, quality labels, hrefs, and Neo4j/YAML fallback shape are duplicated; Neo4j should be an adapter, not the public graph contract | [spec](docs/specs/2026-06-29-graph-neighborhood-projection.md), [DDR-N](docs/architecture/decisions/ddr-n-graph-neighborhood-projection.md) |
| 4.7 | Source grounding module | `app/shared/source_grounding/`, `check_source_integrity.py`, `check_source_links.py`, `jurisdiction_passages.py`, `source_fetcher.py` | Case and jurisdiction grounding duplicate fetch/text/quote mechanics, but their `SourcePassage` contracts are product-owned and should not be merged | [spec](docs/specs/2026-06-29-source-grounding-module.md), [DDR-L](docs/architecture/decisions/ddr-l-source-grounding-module.md). Consolidates old 4.6 quote-integrity work; 4.6a remains the non-threshold field-support extension |
| 4.11 | Gemini-backed screening tools | `app/screening/llm/`, `app/screening/tools/`, `jurisdictions.py`, `ChatIntake.tsx`, `JurisdictionChat.tsx` | Knowledge chat, intake chat, parse-financials prompts, model fallback, JSON recovery, and file parsing live inside the router and lack fake-adapter tests | [spec](docs/specs/2026-06-29-gemini-screening-tools.md), [DDR-P](docs/architecture/decisions/ddr-p-gemini-screening-tools.md). Rate limiting remains 8.4 |
| ✅ 5.2 | Case research catalog module | `app/cases/services/case_catalog.py`, `case_service.py`, `index_case_service.py`, `cases.py`, `indexed_cases.py`, `search.py`, `features/cases/api.ts` | Canonical-vs-indexed policy, filters, search-hit projection, route targets, and trust labels are scattered across routes, services, and frontend assumptions | ✅ Done (#44) — CaseCatalog module owns list/search/filter policy, record-status labels, href routing, and hit projection; endpoint shapes preserved; 6 catalog tests + 55 API tests green |
| 5.17 | Promotion gate module | `promotion_gate.py`, `run_case_promotion.py`, `run_bulk_promotion.py`, `check_source_integrity.py`, `lint_case_semantics.py` | Single-case and bulk promotion know different fragments of draft-to-canonical safety policy; bulk promotion must not bypass grounding, semantic, or conflict gates at volume | [spec](docs/specs/2026-06-29-grounding-gates-bulk-promote-lane.md), [DDR-K](docs/architecture/decisions/ddr-k-promotion-gate-module.md) |

## Phase 5 — Product: Case research

**Goal:** full-depth extraction — market definition **+** theories of harm **+** remedies, grounded
with verbatim source passages — for *any* EU / UK / US case via one end-to-end command (index entry →
review-ready draft → promote). **Sequence:** finish EU (non-English + backlog) → stand up UK → build US.
Today the canonical corpus is ~96% market-definition-only (11 of 271 cases carry theories of harm), and
the bulk lane only ran the `market_definition` focus — so depth, orchestration, and the UK/US lanes are
the gating work.

**Snapshot (2026-06-27):** canonical EU 266 / UK 2 / US 3 · index EU 2,342 / UK 487 / US 11 ·
unpromoted drafts EU 2,537 / UK 578 / US 9.

### Product UX & quality (existing)

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 5.1 | Unify branding | `README`, web nav, API title | CompMap vs Meridian | ✅ Done |
| 5.3 | Eval metrics admin view | `/admin/evals`, benchmark summary API/file reader | Reliability story hidden | Read-only page for latest `data/evals/results` benchmark summaries; no auth or benchmark recomputation in this PR |
| 5.5 | Embedding search eval | `data/evals/`, semantic search eval script | No quality gate on semantic search | Small gold query set + recall@k runner; record baseline first, do not fail CI until threshold is agreed |
| 5.6a | Case integrity trust-signal contract | `check_source_integrity.py`, API response models/tests | `PropositionVerification` and source-integrity output diverge | Add stable per-document/per-passage trust output from integrity checks; no UI change |
| 5.6b | Evidence UI consumes trust signal | `Evidence.tsx`, `lib/types.ts`, case API | Users need one visible source-trust signal | Display optional integrity-derived status with fallback to existing `PropositionVerification` semantics |
| 5.7a | `case_type` enum compatibility | `case.py`, API/web types, validation tests | JV / minority / litigation cases need typed values without breaking existing YAML | Introduce enum/aliases with backward-compatible default; no data backfill |
| 5.7b | Backfill missing `case_type` values | `data/cases/`, `data/drafts/`, validation scripts | Many older canonical/draft records omit `case_type`; typed model should not rely on implicit defaults forever | Add explicit `case_type: merger` where known; validate canonical and representative drafts |
| 5.8a | Similar-case scoring evaluation | graph/search services, `data/evals/` | Automated links need a quality bar before writing YAML | Define candidate scoring + small judged set; report precision/recall-style metrics only |
| 5.8b | Offline `similar_cases` generator | graph/search services, scripts | Curated manually in YAML today | Generate candidate artifact from scoring pipeline; no canonical YAML writes by default |
| 5.8c | Controlled `similar_cases` write path | generator, `data/cases/`, case UI/API | Good candidates should become reviewed canonical data | Write bounded reviewed batch to YAML and preserve existing display contract |

### Pipeline — full-depth, grounded, end-to-end

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 5.9 | Dual extraction for case ingestion | `ingest_case.py`, `compare_extractions.py`, `calibrate_dual_extraction.py`, `promote_case_pipeline.py` | Human reviews every promoted case; not scalable beyond hundreds | ✅ Done (#26) — [spec](docs/specs/completed/2026-06-25-case-dual-extraction.md), [DDR-J](docs/architecture/decisions/ddr-j-dual-extraction.md): two cold extractions → align + diff → human reviews conflicts only; calibration gate measures agreement precision / conflict recall on golds before scale use. Calibrated on **EU market-definition golds only** — see 5.18 |
| ✅ 5.10 | Multi-jurisdiction PDF resolution | `pdf_resolvers.py`, `resolve_case_index_pdf_urls.py`, `ingest_case.py --from-index` | Only EU Phase I auto-resolves; Phase II / UK / US need manual URLs (ddr-b gap) | ✅ Done (#30) — [spec](docs/specs/completed/2026-06-26-multi-jurisdiction-pdf-resolution.md): one resolver contract + EU Cellar / UK GOV.UK / US DOJ-FTC adapters; shared batch CLI; `ingest_case --from-index`. Follow-up ✅ (#32 code, #34 data) — [spec](docs/specs/completed/2026-06-27-eu-resolver-language-fallback.md): EU language-manifestation fallback; new optional `pdf_language` field; all 168 outstanding EU entries resolved (77 fra / 75 deu / 11 ita / 2 spa / 2 nld / 1 ces, 0 eng) |
| ✅ 5.13 | Case-index `extraction_status` | `case_index.py`, `classify_index_extraction_status.py` | Unpromoted index entries are ambiguous — simplified clearance vs substantive decision awaiting extraction | ✅ Done (#27) — [spec](docs/specs/completed/2026-06-26-case-index-extraction-status.md): `pending`/`not_applicable`/`extracted` field + page-count classifier |
| ✅ 5.16 | Backfill `extraction_status` across the index | `classify_index_extraction_status.py`, `run_bulk_extraction.py`, `data/case_index/`, indexed-case page | The bulk lane and frontend needed persisted status so simplified/abandoned cases remain discoverable without entering extraction | ✅ Done — [spec](docs/specs/completed/2026-06-27-backfill-case-index-extraction-status.md): EU 256 extracted / 1,966 not_applicable / 119 pending / 1 unknown; UK 0 extracted / 117 not_applicable / 370 pending / 0 unknown; US 0 extracted / 1 not_applicable / 1 pending / 9 unknown. Unknowns are the 10 no-`pdf_url` entries tracked in 5.14. #38 surfaces the status on the indexed-case page + `IndexedCaseDetail` API response |
| ✅ 5.14 | Resolve remaining unresolved case-index PDFs | `resolve_case_index_pdf_urls.py`, `ingest_case.py --from-index --pdf-url`, `data/case_index/` | The conservative resolver leaves entries with no `pdf_url` — EU Phase II / appeals not in Cellar, older UK CC pages, US litigation dockets with no single decision PDF | ✅ Done — [spec](docs/specs/completed/2026-06-27-case-index-pdf-gap-resolution.md): audited 25 remaining misses; added 9 official decision/report/opinion PDFs (4 UK, 5 US), plus Kemira's official OFT PDF. Remaining unresolved entries are now 1 EU / 0 UK / 9 US. Audit artifact: `data/batch_runs/case_index_pdf_resolution_20260627.yaml` |
| ✅ 5.24 | Deprecate LLM review stage (Stage 5a) | `scripts/cases/review/review_draft.py`, `apply_review_learning.py`, `create_review_learning_log.py`, pipeline docs | Dual extraction (5.9) supersedes the extract-then-LLM-critic loop; Stage 5a was already skipped in bulk runs and added latency + cost without replacing human review on conflicts | ✅ Done — [spec](docs/specs/completed/2026-06-27-deprecate-llm-review-stage.md): removed Stage 5a scripts, review-learning call sites/artifacts, `ingest_case --llm-review`, promotion Stage 8/9 calls, and active pipeline docs; `ddr-b` records the retirement decision |
| ✅ 5.11 | Full-depth end-to-end orchestration | `run_e2e_extraction.py`, `ingest_case.py`, `compare_extractions.py`, `merge_drafts.py`, `check_review_readiness.py` | ~60 manual commands per case, and the bulk lane only ran `market_definition` — theories of harm + remedies are absent from 260/271 cases (ddr-b Q8) | ✅ Done — [spec](docs/specs/completed/2026-06-27-e2e-extraction-orchestrator.md): one CLI runs profile-selected extraction focuses, records resumable state, merges completed dual Draft A outputs plus single-pass metadata drafts, writes deterministic readiness packet + summary, and keeps human conflict resolution/promotion explicit after Stage 5a retirement |
| ✅ 5.18 | Dual-extraction calibration for full depth & per jurisdiction | `calibrate_dual_extraction.py`, `compare_extractions.py`, `data/evals/` | 5.9 calibrated agreement-precision / conflict-recall on **EU market-definition golds only**; theories/remedies and the UK/US lanes have no calibration, so "review conflicts only" isn't yet trustworthy outside that slice | ✅ Done (#42) — [spec](docs/specs/completed/2026-06-28-dual-extraction-calibration-expansion.md): commitments now participate in reconciliation/comparison/calibration, and reviewed UK/US market-definition plus EU/UK/US theories golds are wired into benchmark configs. Remedies calibration is scaffolded pending reviewed remedies golds from future remedy-focused extractions. |
| 5.12 | Workflow engine evaluation (conditional) | pipeline orchestration | Only if extraction (not human review) throughput becomes the bottleneck near 1000 cases (ddr-b Q7) | Do not run via default agent-flow. When throughput evidence exists, evaluate Temporal/Prefect for durable resume + parallel fan-out |

### EU lane — finish first

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 5.15 | Non-English decision extraction | `extract_case_from_source.py`, `quote_snippet` schema, `case.py` | 168 EU entries resolve only to non-English decisions (`pdf_language` ≠ eng); the product is English-facing but `quote_snippet` must stay verbatim in the source language | ✅ Done — [spec](docs/specs/completed/2026-06-27-non-english-decision-extraction.md): threads `pdf_language` from the index scaffold through extraction prompts and emitted drafts; adds `source_language` + optional non-authoritative `quote_translation` to `SourcePassage`/`SourceDocument` (verbatim `quote_snippet` stays in the source language); bulk dry-run reports pending language buckets. Structured fields stay English; not a bulk-promotion drive |
| 5.19a | EU backlog triage manifest | `data/drafts/eu/`, `data/case_index/eu/`, promote lane | The EU backlog is too large to promote safely without a batch plan | Produce a reviewed manifest grouped by `extraction_status`, draft kind, review status, language, and blocking reason; no canonical writes |
| 5.19b | EU full-depth pilot promotion | `data/drafts/eu/`, `data/cases/eu/`, promote lane | Prove full-depth promotion on real EU cases before batch writes | Promote a tiny reviewed pilot set (target <=5 cases) through 5.17 gates; record blockers separately |
| 5.19c | EU full-depth batch 1 | `data/drafts/eu/`, `data/cases/eu/`, batch artifact | Substantive EU backlog needs bounded promotion PRs, not one corpus-wide PR | Promote first manifest-selected batch (target <=25 cases); create follow-up rows for later batches |
| 5.20a | EU promoted-case depth gap manifest | `data/cases/eu/`, pipeline profiles | 260 promoted EU cases are market-definition-only; choose batches before re-extraction | Identify canonical cases missing theories/remedies and rank by source availability/complexity; no data writes |
| 5.20b | EU theories/remedies pilot backfill | `data/cases/eu/`, theories + remedies focuses | Backfilling existing canonical records has merge risk | Add theories/remedies to a tiny reviewed pilot set (target <=5 cases); preserve market definitions |
| 5.20c | EU theories/remedies batch 1 | `data/cases/eu/`, batch artifact | Full corpus depth should move in auditable chunks | Backfill first manifest-selected batch (target <=25 cases); create follow-up rows for later batches |

### UK lane

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 5.21a | UK full-depth readiness check | `cma_report` profile, UK golds/tests, promote lane | UK lane is built but not proven across CMA reports | Confirm profile coverage for theories/remedies and gate behavior; no backlog writes |
| 5.21b | UK full-depth pilot promotion | `data/drafts/uk/`, `data/cases/uk/`, promote lane | UK has only 2 promoted cases; start with a tiny reviewed set | Promote target <=5 CMA cases through full-depth extraction + 5.17 gates |
| 5.21c | UK full-depth batch 1 | `data/drafts/uk/`, `data/cases/uk/`, batch artifact | UK backlog promotion needs bounded auditable chunks | Promote first manifest-selected batch (target <=25 cases); create follow-up rows for later batches |

### US lane — build from scratch

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 5.22a | US discovery scraper contract | `scripts/cases/discovery/`, tests/fixtures | No US scraper exists; DOJ and FTC pages differ enough to need a shared contract first | Define normalized source records, fixture tests, and resolver handoff; no live scrape/data writes |
| 5.22b | DOJ case-index scraper | new `scrape_us_doj_index.py`, `pdf_resolvers.py`, fixtures | DOJ litigation/decree listings need repeatable discovery | Scrape DOJ entries into `CaseIndexEntry` fixture/output shape; no FTC work |
| 5.22c | FTC case-index scraper | new `scrape_us_ftc_index.py`, `pdf_resolvers.py`, fixtures | FTC administrative/federal-court listings differ from DOJ | Scrape FTC entries into the same contract; no DOJ refactor beyond shared helpers |
| 5.22d | US index backfill + PDF resolution | `data/case_index/us/`, US discovery scripts | Hand-added US index is too small and has missing PDFs | Add a bounded reviewed US index batch from DOJ/FTC output and resolve official PDFs; record unresolved cases explicitly |
| 5.23a | US litigation extraction profile | `extract_case_from_source.py`, `pipeline_profiles/us_court_opinion.yaml`, tests | Complaints and competitive-impact statements are not authority decisions | Teach extraction to map allegations to `definition_status: discussed`; depends on 5.7a |
| 5.23b | US litigation gold set | `data/evals/gold/`, `data/evals/fixtures/` | US calibration needs reviewed complaint/opinion examples | Add small reviewed gold set for US litigation-shaped documents; source quotes must be official and exact |
| 5.23c | US litigation calibration | `calibrate_dual_extraction.py`, benchmark configs | Dual extraction is not yet trustworthy for US litigation documents | Wire US litigation golds into calibration and record pass/fail thresholds |
| 5.23d | US pilot extraction | `data/drafts/us/`, `data/cases/us/`, promote lane | US extraction should prove the full path before scaling | Run a tiny reviewed pilot (target <=3 cases) through extraction, calibration-informed review, and 5.17 gates |

## Phase 6 — Product: Screening

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 4.6a | Expand grounding to non-threshold fields | `jurisdiction.py`, `jurisdiction_passages.py`, `jurisdiction_verification.py`, `jurisdiction_baseline.py` | Review periods, fees, gun-jumping fines, regime flags ungrounded; errors found in Batch A/B sweep | [spec](docs/specs/2026-06-25-expand-field-grounding.md): add `supports_fields` to `SourcePassage`; field-path resolver; qualitative fields get passage-existence check; Tier 4 re-extraction handles interpretation cross-check |
| 5.4 | Threshold engine unit tests | `tests/test_threshold_engine.py` | Only gold-deal regression today | Direct tests per test type |

## Phase 7 — Deploy

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 7.1 | Production Docker / compose prod | `docker-compose.prod.yml`, Dockerfiles | Dev compose not production-ready | Multi-stage builds, non-root, healthchecks |
| 7.2a | Managed Postgres provider decision | env docs, migrations | Local-only DB today | Decision/spec only: compare Neon/Supabase/RDS for pgvector, connection pooling, backups, and secrets; no deploy |
| 7.2b | Managed Postgres config | env docs, migrations, smoke script | App needs a selected managed Postgres target | Add selected-provider env/runbook and migration smoke; depends on 7.2a |
| 7.3a | API deploy target decision | `apps/api/`, CI docs | Fly/Railway/ECS have different operational contracts | Decision/spec only: choose API platform and required secrets/health checks; no deploy config |
| 7.3b | API deploy config | `apps/api/`, selected platform config, CI | No hosted API | Add selected-platform config using `DATABASE_URL`, health check, and non-root production image; depends on 7.1 and 7.3a |
| 7.4 | Web deploy (Vercel) | `apps/web/`, env | No hosted frontend | Configure Vercel with `NEXT_PUBLIC_API_URL` pointing at deployed API; depends on 7.3b |
| 7.5a | Embedding sync manifest | `index_embeddings.py`, data hash manifest | Manual embed; stale vectors unknown | Track content hashes per case/market/theory and skip unchanged embeddings; no scheduler |
| 7.5b | Scheduled embed job | `index_embeddings.py`, CI/deploy scheduler | Vectors need routine refresh after data changes | Add post-deploy or nightly re-embed using the sync manifest; depends on 7.5a |

## Phase 8 — Auth

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 8.1 | Auth provider choice + spec | `docs/specs/auth.md` | Open API not production-safe | Decision/spec only: choose Clerk vs Auth0 and define read/write route policy |
| 8.2 | API middleware | `apps/api/main.py`, deps | Protect write/LLM endpoints | JWT validation on POST routes; depends on 8.1 |
| 8.3 | Web auth shell | `apps/web/` middleware | Gated routes | Sign-in, session, protected `/screen`; depends on 8.1 |
| 8.4 | Rate limiting on LLM routes | `jurisdictions` chat/parse | Cost/abuse surface | Start with per-IP limits for unauthenticated LLM endpoints; switch key to authenticated user after 8.2/8.3 |

## Phase 9 — Ops

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 9.1 | Structured logging | `apps/api/app/` | No production debugging | JSON logs, request IDs |
| 9.2a | API error tracking | Sentry SDK, `apps/api/` | Silent API failures in prod | Add no-op-without-DSN SDK wiring and request context; no web changes |
| 9.2b | Web error tracking | Sentry SDK, `apps/web/` | Silent frontend failures in prod | Add no-op-without-DSN SDK wiring and source-map/env docs; depends on 9.2a |
| 9.3a | Case source-integrity nightly | integrity scripts, new workflow | Case source drift undetected | Add nightly canonical-case `check_source_integrity` job with cache and artifact output; no alerting yet |
| 9.3b | Drift alerting channel | verification workflows, deploy/ops docs | Nightly failures need human attention | Add Slack/email alerting for jurisdiction and case drift jobs; depends on 9.3a and chosen secrets platform |
| 9.4 | Secrets management | deploy platform | `.env` local only | After deploy platform is selected, document required secrets and move runtime config into platform secrets; no keys in repo |

---

**After DDRs:** revisit rows marked "spec first" — add rows you discover, remove rows you decide against.
