# Spec: repository layout restructure

Mechanical package boundaries so case research and jurisdiction screening are obvious in the tree. Move-only — no logic changes.

**Decision rationale:** [ddr-0-repo-layout.md](../architecture/decisions/ddr-0-repo-layout.md)

**Out of scope:** router splits, symbol renames, Neo4j removal, auth, CI expansion (separate specs).

---

## Target tree

### API — `apps/api/app/`

```
app/
├── shared/                 # infrastructure only — not domain models
│   ├── core/               # config.py, pg_client.py, neo4j_client.py
│   ├── routers/            # health.py
│   └── utils/              # pdf_extractor.py (used by cases pipeline + screening fetcher)
├── cases/
│   ├── models/             # case.py, case_index.py, concept.py, api_responses.py
│   ├── routers/            # cases, indexed_cases, search, graph, graph_entities
│   ├── services/           # case_*, semantic_*, embedding_*, graph_*
│   └── loader/             # yaml_loader, index_loader, concept_loader, validator
└── screening/
    ├── models/             # jurisdiction.py, jurisdiction_verification.py
    ├── routers/            # jurisdictions.py
    └── services/           # threshold_engine, jurisdiction_*, source_fetcher
```

`main.py` imports from `app.cases.routers`, `app.screening.routers`, `app.shared.routers`.

**No `shared/models/`.** `CaseRecord` and `JurisdictionRule` are product-owned. Note: `SourcePassage` exists in both model files as **different schemas** (same name) — splitting models makes that explicit.

### Scripts — `apps/api/scripts/`

```
scripts/
├── cases/              # extract, ingest, promote, validate, pipeline_profile, …
└── screening/          # verify_jurisdiction_*, run_jurisdiction_verification, …
```

No `scripts/shared/`. `pipeline_profile.py` lives in `scripts/cases/` (extraction profiles only).

### Web — `apps/web/src/`

```
src/
├── app/                # Next.js routes only (thin page wrappers; URLs unchanged)
├── features/
│   ├── cases/          # explore/, graph/, components/, api.ts
│   └── screening/      # components/, api.ts
├── components/         # shared chrome: NavBar, ThemeToggle, Badge, …
└── lib/
    ├── api-client.ts   # shared fetch helpers (server vs browser base URL)
    ├── types.ts        # all TS types (split by feature is a separate change)
    └── utils.ts
```

`features/cases/api.ts` and `features/screening/api.ts` replace monolithic `lib/api.ts`.

### Data — no moves (documented grouping)

Top-level folders stay as-is. See [architecture/overview.md](../architecture/overview.md#data-layout) for case vs screening groupings.

```
data/
  # Case research blob
  cases/ | drafts/ | case_index/ | source_text/ | concepts/
  evals/ | pipeline_profiles/ | review_learning/ | batch_runs/
  # Screening blob
  jurisdictions/
```

Do not nest everything under `data/cases/` — high churn, and `drafts/` vs `cases/` sibling boundary is intentional.

---

## Phased execution

Three independent PRs (API packages → script subdirs → web features).

### PR 1 — API packages

Move flat `app/routers/`, `services/`, `models/`, `loader/`, `core/`, `utils/` into product packages. Update all `from app.` imports in `app/`, `tests/`, `scripts/`, `main.py`.

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
| `app/services/source_fetcher.py` | `app/screening/services/source_fetcher.py` |
| `app/services/threshold_engine.py` | `app/screening/services/threshold_engine.py` |
| `app/services/jurisdiction_*.py` | `app/screening/services/` |
| `app/loader/*` | `app/cases/loader/*` |
| `app/core/*` | `app/shared/core/*` |
| `app/models/case.py` | `app/cases/models/case.py` |
| `app/models/case_index.py` | `app/cases/models/case_index.py` |
| `app/models/concept.py` | `app/cases/models/concept.py` |
| `app/models/api_responses.py` | `app/cases/models/api_responses.py` |
| `app/models/jurisdiction.py` | `app/screening/models/jurisdiction.py` |
| `app/models/jurisdiction_verification.py` | `app/screening/models/jurisdiction_verification.py` |
| `app/utils/*` | `app/shared/utils/*` |

### PR 2 — Script subdirs

**`scripts/cases/`:**  
`extract_case_from_source`, `ingest_case`, `promote_*`, `validate_*`, `check_source_*`, `check_review_readiness`, `check_case_index_sources`, `review_draft`, `merge_drafts`, `run_bulk_extraction`, `run_controlled_case`, `run_unit_assessment_batch`, `plan_*`, `create_gold_draft`, `repair_*`, `evaluate_extraction`, `run_eval_benchmark`, `create_review_learning_log`, `apply_review_learning`, `bulk_promote_pass`, `index_embeddings`, `scrape_*`, `resolve_*`, **`pipeline_profile.py`**

**`scripts/screening/`:**  
`run_jurisdiction_verification`, `verify_jurisdiction_*`, `monitor_jurisdiction_staleness`, `fix_jurisdiction_redirects`, `insert_minority_thresholds`, `report_jurisdiction_verification_baseline`

Also update: `promote_case_pipeline.py` subprocess paths, CI workflows, and path references in docs that cite script locations.

### PR 3 — Web feature folders

| From | To |
|------|-----|
| `app/explore/`, `app/graph/` logic | `features/cases/explore/`, `features/cases/graph/` |
| Case components (`CaseCard`, `Evidence`, …) | `features/cases/components/` |
| `app/screen/`, jurisdiction UI components | `features/screening/components/` |
| `lib/api.ts` | `features/cases/api.ts` + `features/screening/api.ts` + `lib/api-client.ts` |

**Next.js:** `src/app/*/page.tsx` remain as thin wrappers importing from `features/`. URL paths unchanged.

---

## Explicitly out of scope for this spec

| Item | Why defer |
|------|-----------|
| Split `jurisdictions.py` into screening + chat routers | Behaviour change; see DDR-F |
| Rename `Juris.tsx`, `jurisdiction_count` | Cosmetic; see DDR-G |
| Split `lib/types.ts` by feature | Separate change |
| `data_jurisdictions_path` config key | Small follow-up spec |
| Neo4j / `graph/` removal | DDR-C decision |
| `data/` tree moves | Paths stable; grouping in overview |
| Flatten `apps/` to root `api/` + `web/` | Unrelated churn |
| Two repos or npm packages | Overkill |
| CI workflow expansion | Separate spec |

---

## Verification

```bash
cd apps/api && .venv/bin/python -m pytest tests/ -v
cd apps/api && .venv/bin/ruff check .
cd apps/web && npm run lint && npm run build
docker compose up --build   # smoke: /health, /explore, /screen
```

After PR 2: run one script from each subdir with `--help`.

---

## Rollback

Each PR is independently revertible via git revert. No schema or data migrations.
