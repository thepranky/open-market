# DDR-0: Repository layout

**Status:** draft | **Date:**

## Decision

Keep **one monorepo** (`open-market`) with **two API packages** (`app/cases/`, `app/screening/`) plus `app/shared/` for contracts and infrastructure. Mirror in `scripts/` and `src/features/`. Do not split repos or move `data/`.

## Context

Two products share one deployable API and one web app. Data is already split (`data/cases/` vs `data/jurisdictions/`). Code mixing is the problem: flat `routers/`, `services/`, `scripts/`, and `lib/api.ts` hide boundaries.

## Why monorepo (not two repos)

| For | Against split |
|-----|----------------|
| One Docker compose, one PR for cross-product fixes | Duplicated Pydantic types or a publishable package overhead |
| Shared `data/`, shared CI, capstone-simple deploy story | Two deploy pipelines for little isolation gain |
| Case research and screening are complementary workflows | Products are not independently versioned today |

Split repos only if products ship on different cadences with different teams.

## Why two packages (not one flat `app/`)

| `app/cases/` | `app/screening/` |
|--------------|------------------|
| Routers: cases, search, graph | Router: jurisdictions |
| Services: case, search, graph, embed | Services: threshold_engine, jurisdiction_* |
| Loader: YAML case ingestion | Loads YAML inline in threshold_engine |
| Uses Postgres/pgvector | Pure in-memory YAML |

**`app/shared/`:** Pydantic models (`CaseRecord`, `JurisdictionRule`), config, pg_client, health — used by both.

Clear folders make imports document ownership: `from app.cases.services.case_service` vs `from app.screening.services.threshold_engine`.

## Alternatives considered

- **Status quo** — works but hard to learn; overloaded names (`jurisdiction`).
- **Two repos** — rejected; unnecessary for capstone scale.
- **Microservices** — rejected; screening does not need a separate process.

## What we are not deciding here

- Splitting `jurisdictions.py` into multiple routers (DDR-F).
- Renaming `Juris.tsx` / stats labels (DDR-G).
- Removing Neo4j (DDR-C).

See `docs/specs/restructure-layout.md` for move list and doc update checklist.

## Consequences

- **Positive:** Deep-dives A–I read against stable paths; agents scope changes by package.
- **Negative:** Three PRs of import churn; all docs listing old paths must update (checklist in spec).
- **Risk:** Broken imports if tests not run — mitigated by full pytest per PR.

## Next steps

1. Review this DDR + `docs/specs/restructure-layout.md`.
2. PR 1: API package moves (spec verification: pytest + ruff).
3. Update doc checklist for PR 1 before starting DDR-A.
