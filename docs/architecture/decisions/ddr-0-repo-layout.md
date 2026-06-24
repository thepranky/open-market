# DDR-0: Repository layout

**Status:** draft | **Date:**

## Decision

Keep **one monorepo** (`open-market`) under `apps/` (api + web unchanged). Split API code into **`app/cases/`**, **`app/screening/`**, and **`app/shared/`** (infrastructure only). Mirror in `scripts/cases/`, `scripts/screening/`, and `src/features/`. Do not split repos or move `data/` paths.

## Context

Two products share one deployable API and one web app. Data top-level folders already group by workflow (see overview § Data layout). Code mixing is the problem: flat `routers/`, `services/`, `scripts/`, and `lib/api.ts` hide boundaries.

## Why monorepo (not two repos)

| For | Against split |
|-----|----------------|
| One Docker compose, one PR for cross-product fixes | Duplicated types or publishable-package overhead |
| Shared CI, capstone-simple deploy | Two pipelines for little isolation gain |
| Complementary workflows (research + screening) | Products not independently versioned today |

## Why two packages + minimal shared (not one flat `app/`)

| `app/cases/` | `app/screening/` |
|--------------|------------------|
| Models: `CaseRecord`, `CaseIndexEntry`, `concept`, `api_responses` | Models: `JurisdictionRule`, verification sidecars |
| Routers: cases, search, graph | Router: jurisdictions |
| Services: case, search, graph, embed | Services: threshold_engine, jurisdiction_*, source_fetcher |
| Loader: YAML case ingestion | Loads YAML in threshold_engine |
| Uses Postgres/pgvector | Pure in-memory YAML |

**`app/shared/`** — infrastructure only: `core/` (config, pg_client), `routers/health`, `utils/pdf_extractor` (low-level PDF helper used by both pipelines).

**Not in shared:** domain Pydantic models. `CaseRecord` and `JurisdictionRule` live in their product packages. `SourcePassage` is defined separately in each (same name, different fields) — colocating models avoids a false “shared contract” impression.

**Scripts:** `scripts/cases/` (including `pipeline_profile.py`) and `scripts/screening/` — no `scripts/shared/`.

## Alternatives considered

- **Status quo** — works but hard to learn; overloaded names (`jurisdiction`).
- **`shared/models/` for all Pydantic** — rejected; models are product-owned, not shared domain.
- **Nest all data under `data/cases/` + `data/jurisdictions/`** — rejected; massive path churn; `drafts/` vs `cases/` sibling boundary is valuable.
- **Two repos / microservices** — rejected for capstone scale.

## What we are not deciding here

- Splitting `jurisdictions.py` into multiple routers (DDR-F).
- Renaming `Juris.tsx` / stats labels (DDR-G).
- Removing Neo4j (DDR-C).
- Flattening `apps/` to root-level `api/` + `web/`.

See `docs/specs/restructure-layout.md` for move list and doc update checklist.

## Consequences

- **Positive:** Imports document ownership; deep-dives A–I use stable product paths.
- **Negative:** Three PRs of import churn; docs must update (checklist in spec).
- **Risk:** Screening imports `shared/utils/pdf_extractor` — acceptable infra dependency, not cases→screening domain coupling.

## Next steps

1. Review this DDR + `docs/specs/restructure-layout.md`.
2. PR 1: API package moves (pytest + ruff).
3. Update doc checklist; then start DDR-A on new paths.
