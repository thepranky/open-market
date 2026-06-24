# Spec: repository layout restructure

**Status:** draft  
**Goal:** Mechanical package boundaries so case research and jurisdiction screening are obvious in the tree. Move-only — no logic changes.

**Out of scope:** router splits, symbol renames, Neo4j removal, auth, CI expansion (separate specs).

---

## Target tree (end state)

### API — `apps/api/app/`

```
app/
├── shared/
│   ├── core/           # config.py, pg_client.py, neo4j_client.py
│   ├── models/         # all Pydantic models (shared contracts)
│   └── utils/          # pdf_extractor.py
├── cases/
│   ├── routers/        # cases, indexed_cases, search, graph, graph_entities
│   ├── services/       # case_*, semantic_*, embedding_*, graph_*, source_fetcher
│   └── loader/         # yaml_loader, index_loader, concept_loader, validator
├── screening/
│   ├── routers/        # jurisdictions.py (unchanged file, new path)
│   └── services/       # threshold_engine, jurisdiction_*
└── routers/
    └── health.py       # stays at app level OR moves to shared/routers/
```

`main.py` imports from `app.cases.routers`, `app.screening.routers`, `app.shared` (or `app.routers.health`).

### Scripts — `apps/api/scripts/`

```
scripts/
├── cases/              # extract, ingest, promote, validate, check_source_*, eval, scrape, merge, review_learning
├── screening/          # verify_jurisdiction_*, run_jurisdiction_verification, monitor_*, fix_jurisdiction_*
└── shared/             # pipeline_profile.py (if used by both)
```

### Web — `apps/web/src/`

```
src/
├── features/
│   ├── cases/          # explore, graph, cases, indexed-cases pages + case components
│   └── screening/      # jurisdictions, screen pages + screening components
├── components/         # shared only: NavBar, ThemeToggle, Badge, layout chrome
└── lib/
    └── shared/         # utils.ts; types split or re-exported from features
```

`features/cases/api.ts` and `features/screening/api.ts` replace monolithic `lib/api.ts`.

### Data — no moves

```
data/cases/ | data/drafts/ | data/case_index/ | data/jurisdictions/
```

Already product-split. Do not restructure `data/`.

---

## Phased execution (one PR each)

### PR 1 — API packages (`3a`)

| From | To |
|------|-----|
| `app/routers/cases.py` | `app/cases/routers/cases.py` |
| `app/routers/indexed_cases.py` | `app/cases/routers/indexed_cases.py` |
| `app/routers/search.py` | `app/cases/routers/search.py` |
| `app/routers/graph.py` | `app/cases/routers/graph.py` |
| `app/routers/graph_entities.py` | `app/cases/routers/graph_entities.py` |
| `app/routers/jurisdictions.py` | `app/screening/routers/jurisdictions.py` |
| `app/routers/health.py` | `app/shared/routers/health.py` |
| `app/services/case_service.py` | `app/cases/services/case_service.py` |
| `app/services/index_case_service.py` | `app/cases/services/index_case_service.py` |
| `app/services/semantic_search_service.py` | `app/cases/services/semantic_search_service.py` |
| `app/services/embedding_service.py` | `app/cases/services/embedding_service.py` |
| `app/services/graph_service.py` | `app/cases/services/graph_service.py` |
| `app/services/graph_entity_service.py` | `app/cases/services/graph_entity_service.py` |
| `app/services/source_fetcher.py` | `app/cases/services/source_fetcher.py` |
| `app/services/threshold_engine.py` | `app/screening/services/threshold_engine.py` |
| `app/services/jurisdiction_*.py` | `app/screening/services/` |
| `app/loader/*` | `app/cases/loader/*` |
| `app/core/*` | `app/shared/core/*` |
| `app/models/*` | `app/shared/models/*` |
| `app/utils/*` | `app/shared/utils/*` |

Update all `from app.` imports in `app/`, `tests/`, `scripts/`, `main.py`.

**Verification:**
```bash
cd apps/api && .venv/bin/python -m pytest tests/ -v && .venv/bin/ruff check .
```

### PR 2 — Script subdirs (`3b`)

**`scripts/cases/`:**  
`extract_case_from_source`, `ingest_case`, `promote_*`, `validate_*`, `check_source_*`, `check_review_readiness`, `check_case_index_sources`, `review_draft`, `merge_drafts`, `run_bulk_extraction`, `run_controlled_case`, `run_unit_assessment_batch`, `plan_*`, `create_gold_draft`, `repair_*`, `evaluate_extraction`, `run_eval_benchmark`, `create_review_learning_log`, `apply_review_learning`, `bulk_promote_pass`, `index_embeddings`, `scrape_*`, `resolve_*`

**`scripts/screening/`:**  
`run_jurisdiction_verification`, `verify_jurisdiction_*`, `monitor_jurisdiction_staleness`, `fix_jurisdiction_redirects`, `insert_minority_thresholds`, `report_jurisdiction_verification_baseline`

**`scripts/shared/` (optional):** `pipeline_profile.py`

Update: `promote_case_pipeline.py` subprocess paths, CI workflows, docs command blocks, DDR/script references.

**Verification:** same pytest + run one script from each subdir with `--help`.

### PR 3 — Web feature folders (`3c`)

| From | To |
|------|-----|
| `app/explore/`, `app/graph/`, `app/cases/`, `app/indexed-cases/` | `features/cases/` (keep route groups under `app/` via re-exports or Next.js route folders — see note) |
| `app/jurisdictions/`, `app/screen/` | `features/screening/` |
| Case components (`CaseCard`, `Evidence`, …) | `features/cases/components/` |
| Screening components (`ChatIntake`, `VerificationBadges`, …) | `features/screening/components/` |
| `lib/api.ts` | split → `features/cases/api.ts`, `features/screening/api.ts` |

**Next.js note:** App Router pages must stay under `src/app/` for routing. Practical approach: keep `src/app/explore/page.tsx` etc. as thin wrappers that import from `features/cases/`. Move logic/components only; do not break URL paths.

**Verification:**
```bash
cd apps/web && npm run lint && npm run build
```

---

## Explicitly does NOT move yet

| Item | Why defer |
|------|-----------|
| Split `jurisdictions.py` into screening + chat routers | Needs DDR-F; behaviour change risk |
| Rename `Juris.tsx`, `jurisdiction_count` | Needs DDR-G; cosmetic + import churn |
| `data_jurisdictions_path` config key | Small spec after screening package exists |
| Neo4j / `graph/` removal | DDR-C decision |
| `data/` tree | Already correct |
| Two repos or npm packages | Overkill |
| CI workflow expansion | `ROADMAP` phase 2 spec |

---

## Docs and DDRs to update after restructure

Update paths in the same PR as each phase (or immediately after). Checklist:

### Always (any phase)

| File | What to update |
|------|----------------|
| `.cursor/rules/meridian.mdc` | Layout section → reflect target tree when done |
| `docs/architecture/overview.md` | Directory diagram, layer table paths |
| `docs/architecture/case-research.md` | Backend file paths |
| `docs/architecture/jurisdiction-screening.md` | Backend file paths |
| `README.md` | Repo structure block |
| `ROADMAP.md` | Mark 3.1–3.5 done; fix any file paths in rows |

### After PR 1 (API)

| File | What to update |
|------|----------------|
| `docs/architecture/decisions/ddr-a-data-contracts.md` | `Before you start` paths → `app/shared/models/`, `app/cases/loader/` |
| `ddr-b-extraction-pipeline.md` | services/loader references |
| `ddr-c-search-graph.md` | routers + services paths |
| `ddr-d-threshold-engine.md` | `app/screening/services/threshold_engine.py` |
| `ddr-e-jurisdiction-verification.md` | `app/screening/services/jurisdiction_*` |
| `ddr-f-deal-intake-llm.md` | `app/screening/routers/jurisdictions.py` |
| `ddr-h-ci-validation.md` | import paths in test discussion |
| `docs/operations/ingestion.md` | script paths if unchanged until PR 2 |
| `docs/operations/promotion-checklist.md` | command paths after PR 2 |
| `docs/operations/jurisdiction-verification.md` | service + script paths |
| `docs/architecture/decisions/README.md` | Add row for DDR-0 |
| `docs/architecture/decisions/ddr-0-repo-layout.md` | Set `Status: accepted` when PR 1 lands |

### After PR 2 (scripts)

| File | What to update |
|------|----------------|
| All DDR `Before you start` blocks listing scripts | `scripts/cases/` or `scripts/screening/` |
| `docs/operations/ingestion.md` | all command examples |
| `docs/operations/promotion-checklist.md` | all command examples |
| `docs/operations/jurisdiction-verification.md` | orchestrator path |
| `docs/operations/hard-cases.md` | merge/promote script paths |
| `CLAUDE.md` / `meridian.mdc` | command paths |
| `.github/workflows/api-ci.yml` | benchmark script path |
| `.github/workflows/jurisdiction-verification.yml` | verification script path |

### After PR 3 (web)

| File | What to update |
|------|----------------|
| `ddr-g-web-frontend.md` | `features/cases/`, `features/screening/` paths |
| `docs/architecture/case-research.md` | Frontend table |
| `docs/architecture/jurisdiction-screening.md` | Frontend table |
| `docs/architecture/overview.md` | Web subgraph if present |

### No path updates needed

| File | Reason |
|------|--------|
| `docs/data/source-integrity.md` | Data rules only |
| `docs/specs/_template.md` | Generic |
| `data/jurisdictions/_schema.md` | Data contract |

---

## Verification (full restructure done)

```bash
cd apps/api && .venv/bin/python -m pytest tests/ -v
cd apps/api && .venv/bin/ruff check .
cd apps/web && npm run lint && npm run build
docker compose up --build   # smoke: /health, /explore, /screen
```

---

## Rollback

Each PR is independently revertible via git revert. No schema or data migrations.
