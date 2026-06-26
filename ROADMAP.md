# ROADMAP

Phased plan from current state to production. Each row is one spec-sized change.
See [`.cursor/rules/meridian.mdc`](.cursor/rules/meridian.mdc) for spec-driven workflow.

| Phase | Step | What | Files / areas | Why | How |
|-------|------|------|---------------|-----|-----|
| **0 Docs** | ✅ 0.1 | Doc consolidation | `docs/`, `README.md`, `CLAUDE.md` | Single source of truth for onboarding | ✅ Done |
| | ✅ 0.2 | Layout spec + DDR-0 | `docs/specs/completed/2026-06-24-restructure-layout.md`, `ddr-0-repo-layout.md` | Clear boundaries before deep-dives | ✅ Done |
| **1 Restructure** | ✅ 1.1 | API packages (`cases/`, `screening/`, `shared/`) | `apps/api/app/` | Learnable module boundaries | ✅ Done (PR 1) |
| | ✅ 1.2 | Script subdirs | `apps/api/scripts/` | Pipeline discoverability | ✅ Done (PR 2) |
| | ✅ 1.3 | Web feature folders | `apps/web/src/features/` | Frontend boundaries | ✅ Done (PR 3) |
| **2 Understand** | ✅ 2.A | DDR-A data contracts + source integrity | `ddr-a-data-contracts.md` | Contract and grounding model understood | ✅ Done |
| | ✅ 2.B | DDR-B extraction pipeline | `ddr-b-extraction-pipeline.md` | Draft → promote pipeline, scripts, review loop | ✅ Done |
| | 2.C–2.I | DDR deep-dives (C–I) | `docs/architecture/decisions/` | Defensible understanding | Ready — restructure complete |
| **3 CI** | ✅ 3.1 | Canonical case schema gate on PR | `.github/workflows/data-contracts.yml`, `validate_cases.py` | Canonical YAML breaks silently today | ✅ Done (#19) |
| | ✅ 3.2 | Jurisdiction push tier on PR | `jurisdiction-verification.yml`, `run_jurisdiction_verification.py` | Screening regressions not gated on merge | ✅ Done (#19) |
| | ✅ 3.3 | Case index schema gate on PR | `validate_case_index.py` | Index YAML drifts from `CaseIndexEntry` | ✅ Done (#19) |
| | ✅ 3.4 | Link DDR-A from case-research doc | `docs/architecture/case-research.md` | Onboarding misses contract reference | ✅ Done (#19) |
| | ✅ 3.5 | Web lint + build in CI | new `web-ci.yml` | Frontend breaks undetected | ✅ Done — [spec](docs/specs/2026-06-25-ci-gaps.md): path-filtered Node-20 lint+build; baseline `.eslintrc.json` (`next/core-web-vitals` + `@typescript-eslint` plugin) + 2 entity escapes |
| | ✅ 3.6 | Ruff in CI | `api-ci.yml` | Style/errors only caught locally | ✅ Done — [spec](docs/specs/2026-06-25-ci-gaps.md): parallel `lint` job; `pyproject.toml` ruff config (E402 ignored in `scripts/`+`tests/`); 236 baseline errors cleared |
| | ✅ 3.7 | Benchmark artifacts | `api-ci.yml` | Eval trends discarded | ✅ Done — [spec](docs/specs/2026-06-25-ci-gaps.md): `upload-artifact` step (`if: always()`, 90-day) for benchmark JSON+MD. Concurrency-cancel (gap B) bundled into `web-ci.yml`+`api-ci.yml` |
| **4 Refine** | 4.1 | Split `jurisdictions.py` router | `app/screening/routers/` | God-router | Spec: screening vs chat vs CRUD |
| | 4.2 | `data_jurisdictions_path` config | `app/shared/core/config.py` | Path derived from cases path | Explicit env var |
| | 4.3 | Rename overloaded symbols | `Juris.tsx`, home stats | Naming collision | `CaseRegulatorBadge`, `case_regulator_count` |
| | 4.4 | Neo4j deprecation decision | `graph/`, `neo4j_client.py` | Legacy noise | DDR-C then spec |
| | ✅ 4.5 | Case YAML semantic lint | `semantic_lint.py`, `lint_case_semantics.py` | Lawyer rules not enforced by Pydantic | ✅ Done (#20) — [spec](docs/specs/completed/2026-06-25-case-semantic-lint.md): deterministic gate (complaint-only markets not `defined`; dangling `supports_*` refs). Outcome-passage rule dropped (prose judgement; `section` on 9/7566 passages) → Stage 5a critic + dual extraction 5.9 |
| | 4.6 | Jurisdiction quote integrity | `scripts/screening/` | `quoted_text` / `supports_conditions` unvalidated | Parity with `check_source_integrity.py` |
| | 4.6a | Expand grounding to non-threshold fields | `jurisdiction.py`, `jurisdiction_passages.py`, `jurisdiction_verification.py`, `jurisdiction_baseline.py` | Review periods, fees, gun-jumping fines, regime flags ungrounded; errors found in Batch A/B sweep | [spec](docs/specs/2026-06-25-expand-field-grounding.md): add `supports_fields` to `SourcePassage`; field-path resolver; qualitative fields get passage-existence check; Tier 4 re-extraction handles interpretation cross-check |
| | 4.7 | Unify SourcePassage contracts | `case.py`, `jurisdiction.py`, integrity scripts | Two passage types, one grounding concept | Shared fields or aliases; one check module |
| | 4.8 | Deprecate `SourceDocument.url` | `case.py`, `data/cases/` | Legacy fallback after `pdf_url` / `case_page_url` | Audit records; migrate; then remove field |
| | 4.9 | Printed-folio detection in PDF cache | `pdf_extractor.py`, `source_text/` | EC folio vs PDF-index offset is manual | Optional folio parse when building page cache |
| | 4.10 | Regroup `scripts/cases/` by stage | `apps/api/scripts/cases/` | Flat folder mixes discovery / extract / review / promote / integrity (ddr-b Q3a) | Spec first; subfolders `discovery/ extract/ review/ promote/`; path-only churn, no behaviour change |
| **5 Product** | ✅ 5.1 | Unify branding | `README`, web nav, API title | CompMap vs Meridian | ✅ Done |
| | 5.2 | Indexed vs canonical decision | `case-research.md`, web UX | Two case layers confuse users (ddr-a Q7) | UX copy now; later merge or keep dual layer |
| | 5.3 | Eval metrics in UI (admin) | new `/admin` or debug panel | Reliability story hidden | Read-only view of benchmark output |
| | 5.4 | Threshold engine unit tests | `tests/test_threshold_engine.py` | Only gold-deal regression today | Direct tests per test type |
| | 5.5 | Embedding search eval | `data/evals/`, scripts | No quality gate on semantic search | Small gold query set + recall@k |
| | 5.6 | Wire verification to integrity | `Evidence.tsx`, models | `PropositionVerification` vs passage status diverge | Single trust signal from integrity results |
| | 5.7 | `case_type` enum expansion | `case.py` | JV / minority cases need typed `case_type` | When ingesting non-merger cases |
| | 5.8 | Automated `similar_cases` | graph / search services | Curated manually in YAML today | Scoring pipeline with quality bar |
| | 5.9 | Dual extraction for case ingestion | `ingest_case.py`, new `compare_extractions.py`, `promote_case_pipeline.py` | Human reviews every promoted case; not scalable beyond hundreds | [spec](docs/specs/2026-06-25-case-dual-extraction.md): two cold extractions → LLM-assisted diff → human reviews conflicts only; ~2x extraction cost, eliminates per-case full review |
| | 5.10 | Multi-jurisdiction PDF resolution | `resolve_pdf_urls.py`, new per-authority resolvers, `ingest_case.py --from-index` | Only EU Phase I auto-resolves; Phase II / UK / US need manual URLs (ddr-b gap) | Shared resolver interface; per-authority adapters (EUR-Lex, CMA, FTC/DOJ); dedup with EU path |
| | 5.11 | Hard-case orchestration automation | `plan_extraction_ranges.py`, `run_unit_assessment_batch.py`, `merge_drafts.py`, `run_controlled_case.py` | ~60 manual commands per mega-merger (ddr-b Q8) | Emit runnable batch plan; all-focus batch runner; auto-invoke merge + `check_review_readiness` |
| | 5.12 | Workflow engine evaluation (conditional) | pipeline orchestration | Only if extraction (not human review) throughput becomes the bottleneck near 1000 cases (ddr-b Q7) | Evaluate Temporal/Prefect for durable resume + parallel fan-out; defer until justified |
| **6 Deploy** | 6.1 | Production Docker / compose prod | `docker-compose.prod.yml`, Dockerfiles | Dev compose not production-ready | Multi-stage builds, non-root, healthchecks |
| | 6.2 | Managed Postgres + pgvector | env docs, migrations | Local-only DB today | Neon/Supabase/RDS; connection pooling |
| | 6.3 | API deploy (Fly/Railway/ECS) | `apps/api/`, CI | No hosted API | Container deploy + `DATABASE_URL` secrets |
| | 6.4 | Web deploy (Vercel) | `apps/web/`, env | No hosted frontend | `NEXT_PUBLIC_API_URL` to prod API |
| | 6.5 | Embed job + sync manifest | `index_embeddings.py`, CI or scheduler | Manual embed; stale vectors unknown | Post-deploy or nightly re-embed; content-hash manifest per case |
| **7 Auth** | 7.1 | Auth provider choice + spec | `docs/specs/auth.md` | Open API not production-safe | Clerk/Auth0; scope read vs write |
| | 7.2 | API middleware | `apps/api/main.py`, deps | Protect write/LLM endpoints | JWT validation on POST routes |
| | 7.3 | Web auth shell | `apps/web/` middleware | Gated routes | Sign-in, session, protected `/screen` |
| | 7.4 | Rate limiting on LLM routes | `jurisdictions` chat/parse | Cost/abuse surface | Per-user or per-IP limits |
| **8 Ops** | 8.1 | Structured logging | `apps/api/app/` | No production debugging | JSON logs, request IDs |
| | 8.2 | Error tracking | Sentry or similar | Silent failures in prod | SDK on API + web |
| | 8.3 | Nightly drift checks + alerts | `jurisdiction-verification.yml`, integrity scripts | Jurisdiction + case source drift undetected | Nightly jurisdiction tier + `check_source_integrity` on canonical cases (with cache); Slack/email on failure |
| | 8.4 | Secrets management | deploy platform | `.env` local only | Platform secrets, no keys in repo |

**After DDRs:** revisit rows marked "spec first" — add rows you discover, remove rows you decide against.
