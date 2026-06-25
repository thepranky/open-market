# Case research architecture

Source-linked merger decision records with keyword search, semantic search (pgvector),
and graph views.

## Data layout

| Path | Role |
|------|------|
| `data/cases/{eu,uk,us}/` | Canonical `CaseRecord` YAML |
| `data/drafts/{eu,uk,us}/` | AI extraction output (never auto-promoted) |
| `data/case_index/{eu,uk,us}/` | Lighter `CaseIndexEntry` for discovery |
| `data/source_text/` | Cached PDF text for integrity checks |
| `data/concepts/` | Shared concept nodes for graph |
| `data/evals/` | Gold fixtures and benchmark configs |
| `data/pipeline_profiles/` | Per-jurisdiction extraction config |
| `data/review_learning/` | Human correction deltas |

The shape and grounding rules for these records are the data contracts described in
[DDR-A: Data contracts and source integrity](decisions/ddr-a-data-contracts.md).

## Backend

| Layer | Key files (under `apps/api/app/`) |
|-------|-----------|
| Contract | `cases/models/case.py`, `case_index.py` |
| Loaders | `cases/loader/yaml_loader.py`, `index_loader.py`, `validator.py` |
| Services | `cases/services/case_service.py`, `index_case_service.py`, `semantic_search_service.py`, `embedding_service.py`, `graph_service.py`, `graph_entity_service.py` |
| Routers | `cases/routers/cases.py`, `indexed_cases.py`, `search.py`, `graph.py`, `graph_entities.py` |
| Derived store | `shared/core/pg_client.py`, `migrations/001_create_vector_schema.sql` |

## Pipeline (scripts)

Source PDF → `scripts/cases/extract_case_from_source.py` / `ingest_case.py` → draft → integrity gates →
`scripts/cases/review_draft.py` → human review → `scripts/cases/promote_case_pipeline.py` → canonical.

See [operations/ingestion.md](../operations/ingestion.md) and
[promotion-checklist.md](../operations/promotion-checklist.md).

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/cases`, `/cases/{id}` | Canonical records |
| GET | `/indexed-cases`, `/indexed-cases/{id}` | Indexed layer |
| GET | `/search`, `/search/semantic`, `/search/market`, `/search/all` | Search |
| GET | `/graph/*` | Neighbourhood and entity aggregates |

## Frontend

| Route | Feature module |
|-------|----------------|
| `/explore` | `features/cases/explore/` (`ExploreClient`, `SearchForm`, …) |
| `/graph` | `features/cases/graph/` (`NavigationGraph`, `GraphView`, …) |
| `/cases/[case_id]` | `features/cases/components/` (`Evidence`, `CaseHistory`, …) |
| `/indexed-cases/[case_id]` | `features/cases/components/` + `app/indexed-cases/` route wrapper |

## Embed step

After adding cases, run semantic indexing:

```bash
docker compose --profile embed up embed
# or: apps/api/scripts/cases/index_embeddings.py
```

Requires `GOOGLE_API_KEY` for `gemini-embedding-001` (768-dim).
