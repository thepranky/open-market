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
| 2.C–2.I | DDR deep-dives (C–I) | `docs/architecture/decisions/` | Defensible understanding | Ready — restructure complete |

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
| 4.1 | Split `jurisdictions.py` router | `app/screening/routers/` | God-router | Spec: screening vs chat vs CRUD |
| 4.2 | `data_jurisdictions_path` config | `app/shared/core/config.py` | Path derived from cases path | Explicit env var |
| 4.3 | Rename overloaded symbols | `Juris.tsx`, home stats | Naming collision | `CaseRegulatorBadge`, `case_regulator_count` |
| 4.4 | Neo4j deprecation decision | `graph/`, `neo4j_client.py` | Legacy noise | DDR-C then spec |
| ✅ 4.5 | Case YAML semantic lint | `semantic_lint.py`, `lint_case_semantics.py` | Lawyer rules not enforced by Pydantic | ✅ Done (#20) — [spec](docs/specs/completed/2026-06-25-case-semantic-lint.md): deterministic gate (complaint-only markets not `defined`; dangling `supports_*` refs). Outcome-passage rule dropped (prose judgement; `section` on 9/7566 passages) → Stage 5a critic + dual extraction 5.9 |
| 4.7 | Unify SourcePassage contracts | `case.py`, `jurisdiction.py`, integrity scripts | Two passage types, one grounding concept | Shared fields or aliases; one check module |
| 4.8 | Deprecate `SourceDocument.url` | `case.py`, `data/cases/` | Legacy fallback after `pdf_url` / `case_page_url` | Audit records; migrate; then remove field |
| 4.9 | Printed-folio detection in PDF cache | `pdf_extractor.py`, `source_text/` | EC folio vs PDF-index offset is manual | Optional folio parse when building page cache |
| ✅ 4.10 | Regroup `scripts/cases/` by stage | `apps/api/scripts/cases/` | Flat folder mixes discovery / extract / review / promote / integrity (ddr-b Q3a) | ✅ Done — [spec](docs/specs/completed/2026-06-25-regroup-cases-scripts.md): 7 buckets (`discovery/ extract/ review/ promote/ integrity/ evals/ embeddings/`); 4 discovery scripts renamed to `scrape_{eu,uk}_index` / `resolve_{eu,uk}_pdf_urls`; no behaviour change. Not path-only — fixed depth-anchored `__file__` arithmetic, cross-bucket flat imports, subprocess paths, and test imports |

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
| 5.2 | Indexed vs canonical decision | `case-research.md`, web UX | Two case layers confuse users (ddr-a Q7) | UX copy now; later merge or keep dual layer |
| 5.3 | Eval metrics in UI (admin) | new `/admin` or debug panel | Reliability story hidden | Read-only view of benchmark output |
| 5.5 | Embedding search eval | `data/evals/`, scripts | No quality gate on semantic search | Small gold query set + recall@k |
| 5.6 | Wire verification to integrity | `Evidence.tsx`, models | `PropositionVerification` vs passage status diverge | Single trust signal from integrity results |
| 5.7 | `case_type` enum expansion | `case.py` | JV / minority cases need typed `case_type`; US litigation also needs complaint-vs-decision typing (see 5.23) | When ingesting non-merger / litigation cases |
| 5.8 | Automated `similar_cases` | graph / search services | Curated manually in YAML today | Scoring pipeline with quality bar |

### Pipeline — full-depth, grounded, end-to-end

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 5.9 | Dual extraction for case ingestion | `ingest_case.py`, `compare_extractions.py`, `calibrate_dual_extraction.py`, `promote_case_pipeline.py` | Human reviews every promoted case; not scalable beyond hundreds | ✅ Done (#26) — [spec](docs/specs/completed/2026-06-25-case-dual-extraction.md), [DDR-J](docs/architecture/decisions/ddr-j-dual-extraction.md): two cold extractions → align + diff → human reviews conflicts only; calibration gate measures agreement precision / conflict recall on golds before scale use. Calibrated on **EU market-definition golds only** — see 5.18 |
| ✅ 5.10 | Multi-jurisdiction PDF resolution | `pdf_resolvers.py`, `resolve_case_index_pdf_urls.py`, `ingest_case.py --from-index` | Only EU Phase I auto-resolves; Phase II / UK / US need manual URLs (ddr-b gap) | ✅ Done (#30) — [spec](docs/specs/completed/2026-06-26-multi-jurisdiction-pdf-resolution.md): one resolver contract + EU Cellar / UK GOV.UK / US DOJ-FTC adapters; shared batch CLI; `ingest_case --from-index`. Follow-up ✅ (#32 code, #34 data) — [spec](docs/specs/completed/2026-06-27-eu-resolver-language-fallback.md): EU language-manifestation fallback; new optional `pdf_language` field; all 168 outstanding EU entries resolved (77 fra / 75 deu / 11 ita / 2 spa / 2 nld / 1 ces, 0 eng) |
| ✅ 5.13 | Case-index `extraction_status` | `case_index.py`, `classify_index_extraction_status.py` | Unpromoted index entries are ambiguous — simplified clearance vs substantive decision awaiting extraction | ✅ Done (#27) — [spec](docs/specs/completed/2026-06-26-case-index-extraction-status.md): `pending`/`not_applicable`/`extracted` field + page-count classifier |
| ✅ 5.16 | Backfill `extraction_status` across the index | `classify_index_extraction_status.py`, `run_bulk_extraction.py`, `data/case_index/`, indexed-case page | The bulk lane and frontend needed persisted status so simplified/abandoned cases remain discoverable without entering extraction | ✅ Done — [spec](docs/specs/completed/2026-06-27-backfill-case-index-extraction-status.md): EU 256 extracted / 1,966 not_applicable / 119 pending / 1 unknown; UK 0 extracted / 117 not_applicable / 370 pending / 0 unknown; US 0 extracted / 1 not_applicable / 1 pending / 9 unknown. Unknowns are the 10 no-`pdf_url` entries tracked in 5.14. #38 surfaces the status on the indexed-case page + `IndexedCaseDetail` API response |
| ✅ 5.14 | Resolve remaining unresolved case-index PDFs | `resolve_case_index_pdf_urls.py`, `ingest_case.py --from-index --pdf-url`, `data/case_index/` | The conservative resolver leaves entries with no `pdf_url` — EU Phase II / appeals not in Cellar, older UK CC pages, US litigation dockets with no single decision PDF | ✅ Done — [spec](docs/specs/completed/2026-06-27-case-index-pdf-gap-resolution.md): audited 25 remaining misses; added 9 official decision/report/opinion PDFs (4 UK, 5 US), plus Kemira's official OFT PDF. Remaining unresolved entries are now 1 EU / 0 UK / 9 US. Audit artifact: `data/batch_runs/case_index_pdf_resolution_20260627.yaml` |
| 5.11 | Full-depth hard-case orchestration | `plan_extraction_ranges.py`, `run_unit_assessment_batch.py`, `merge_drafts.py`, `run_controlled_case.py` | ~60 manual commands per case, and the bulk lane only ran `market_definition` — theories of harm + remedies are absent from 260/271 cases (ddr-b Q8) | One command: index entry → run **market_definition + theories_of_harm + remedies** focuses → merge into a single draft → auto-invoke `check_review_readiness`. The spine that makes any case extractable end-to-end |
| 5.17 | Grounding gates on the bulk promote lane | `bulk_promote_pass.py`, `check_source_integrity.py`, `lint_case_semantics.py` | Integrity + semantic-lint gates (4.5) run in CI and ad hoc, but not inside bulk promotion — nothing stops an ungrounded case promoting at volume | Wire `check_source_integrity` + `lint_case_semantics` into `bulk_promote_pass`; block promotion on failure; record per-case grounding outcome |
| 5.18 | Dual-extraction calibration for full depth & per jurisdiction | `calibrate_dual_extraction.py`, `compare_extractions.py`, `data/evals/` | 5.9 calibrated agreement-precision / conflict-recall on **EU market-definition golds only**; theories/remedies and the UK/US lanes have no calibration, so "review conflicts only" isn't yet trustworthy outside that slice | Add gold sets per focus (theories, remedies) and per jurisdiction (UK, US); recalibrate the conflict gate before each lane scales |
| 5.12 | Workflow engine evaluation (conditional) | pipeline orchestration | Only if extraction (not human review) throughput becomes the bottleneck near 1000 cases (ddr-b Q7) | Evaluate Temporal/Prefect for durable resume + parallel fan-out; defer until justified |

### EU lane — finish first

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| ✅ 5.15 | Non-English decision extraction | `extract_case_from_source.py`, `quote_snippet` schema, `case.py` | 168 EU entries resolve only to non-English decisions (`pdf_language` ≠ eng); the product is English-facing but `quote_snippet` must stay verbatim in the source language | ✅ Done — [spec](docs/specs/completed/2026-06-27-non-english-decision-extraction.md): threads `pdf_language` from the index scaffold through extraction prompts and emitted drafts; adds `source_language` + optional non-authoritative `quote_translation` to `SourcePassage`/`SourceDocument` (verbatim `quote_snippet` stays in the source language); bulk dry-run reports pending language buckets. Structured fields stay English; not a bulk-promotion drive |
| 5.19 | EU full-depth backlog promotion | `data/drafts/eu/`, promote lane | 2,537 EU drafts exist but only 266 are promoted; the substantive remainder needs promoting at full depth, not the old market-def-only path | Triage by `extraction_status` (5.16); run the full-depth orchestration (5.11) + dual extraction (5.18) + grounded promote (5.17) over the substantive backlog |
| 5.20 | EU theories/remedies backfill on promoted cases | `data/cases/eu/`, theories + remedies focuses | The 260 already-promoted EU cases are market-definition-only; they need theories of harm + remedies added without re-extracting market definition | Run theories + remedies focus passes; merge into existing canonical records; re-run integrity + semantic lint |

### UK lane

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 5.21 | UK full-depth promotion drive | `data/drafts/uk/`, `cma_report` pipeline profile, promote lane | 487 UK index entries, 578 drafts, only **2** promoted — the lane is built but never driven | Confirm the `cma_report` profile covers theories/remedies section paths; calibrate dual extraction on CMA golds (5.18); run full-depth orchestration + grounded promote across the UK backlog |

### US lane — build from scratch

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 5.22 | US index discovery | new `scrape_us_index.py`, `scripts/cases/discovery/` | No US scraper exists — the 11 US index entries are hand-added and 10 lack a `pdf_url`; discovery must be built before any US extraction | Scrape DOJ Antitrust Division + FTC competition case listings into `CaseIndexEntry`; resolve PDFs via the existing `UsDojFtcResolver` (5.10) |
| 5.23 | US extraction enablement (litigation-shaped) | `extract_case_from_source.py`, `case.py`, ties 5.7 | US merits documents are complaints / competitive-impact statements, not single decisions; complaint allegations must map to `definition_status: discussed`, not `defined`; needs a US gold set + calibration | Complaint-vs-decision handling in extraction; US golds for dual-extraction calibration (5.18); `case_type` typing for litigation (5.7) |

## Phase 6 — Product: Screening

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 4.6 | Jurisdiction quote integrity | `scripts/screening/` | `quoted_text` / `supports_conditions` unvalidated | Parity with `check_source_integrity.py` |
| 4.6a | Expand grounding to non-threshold fields | `jurisdiction.py`, `jurisdiction_passages.py`, `jurisdiction_verification.py`, `jurisdiction_baseline.py` | Review periods, fees, gun-jumping fines, regime flags ungrounded; errors found in Batch A/B sweep | [spec](docs/specs/2026-06-25-expand-field-grounding.md): add `supports_fields` to `SourcePassage`; field-path resolver; qualitative fields get passage-existence check; Tier 4 re-extraction handles interpretation cross-check |
| 5.4 | Threshold engine unit tests | `tests/test_threshold_engine.py` | Only gold-deal regression today | Direct tests per test type |

## Phase 7 — Deploy

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 7.1 | Production Docker / compose prod | `docker-compose.prod.yml`, Dockerfiles | Dev compose not production-ready | Multi-stage builds, non-root, healthchecks |
| 7.2 | Managed Postgres + pgvector | env docs, migrations | Local-only DB today | Neon/Supabase/RDS; connection pooling |
| 7.3 | API deploy (Fly/Railway/ECS) | `apps/api/`, CI | No hosted API | Container deploy + `DATABASE_URL` secrets |
| 7.4 | Web deploy (Vercel) | `apps/web/`, env | No hosted frontend | `NEXT_PUBLIC_API_URL` to prod API |
| 7.5 | Embed job + sync manifest | `index_embeddings.py`, CI or scheduler | Manual embed; stale vectors unknown | Post-deploy or nightly re-embed; content-hash manifest per case |

## Phase 8 — Auth

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 8.1 | Auth provider choice + spec | `docs/specs/auth.md` | Open API not production-safe | Clerk/Auth0; scope read vs write |
| 8.2 | API middleware | `apps/api/main.py`, deps | Protect write/LLM endpoints | JWT validation on POST routes |
| 8.3 | Web auth shell | `apps/web/` middleware | Gated routes | Sign-in, session, protected `/screen` |
| 8.4 | Rate limiting on LLM routes | `jurisdictions` chat/parse | Cost/abuse surface | Per-user or per-IP limits |

## Phase 9 — Ops

| Step | What | Files / areas | Why | How |
|------|------|---------------|-----|-----|
| 9.1 | Structured logging | `apps/api/app/` | No production debugging | JSON logs, request IDs |
| 9.2 | Error tracking | Sentry or similar | Silent failures in prod | SDK on API + web |
| 9.3 | Nightly drift checks + alerts | `jurisdiction-verification.yml`, integrity scripts | Jurisdiction + case source drift undetected | Nightly jurisdiction tier + `check_source_integrity` on canonical cases (with cache); Slack/email on failure |
| 9.4 | Secrets management | deploy platform | `.env` local only | Platform secrets, no keys in repo |

---

**After DDRs:** revisit rows marked "spec first" — add rows you discover, remove rows you decide against.
