# Meridian (`open-market` repo)

Market-definition research + merger-control threshold screening for competition lawyers.
**Product name:** Meridian. **Repo folder:** `open-market`.

## Products

1. **Case research** — source-linked EU/UK/US merger YAML; keyword + semantic search; graph views.
2. **Jurisdiction screening** — ~60 `data/jurisdictions/*.yaml` profiles; `threshold_engine.py`; `/screen` deal intake.

## Layout

```
apps/api/     FastAPI — app/{cases,screening,shared}/, scripts/{cases,screening}/, tests/
apps/web/     Next.js 14 — src/app/ (routes), src/features/{cases,screening}/, src/components/ (shared)
data/         YAML source of truth
docs/         architecture/, operations/, specs/, architecture/decisions/
```

**Data:**
- `data/cases/` — canonical `CaseRecord` (270+)
- `data/drafts/` — AI extraction only; never auto-promoted
- `data/case_index/` — lighter discovery metadata
- `data/jurisdictions/` — threshold profiles
- `data/evals/`, `source_text/`, `pipeline_profiles/`, `review_learning/`

**Derived:** Postgres+pgvector (case embeddings only). Neo4j is legacy optional — graph routes fall back to YAML.

## Architecture

```
app/cases/routers → app/cases/services → app/cases/loader → data/cases/
app/screening/routers → app/screening/services (threshold_engine) → data/jurisdictions/
app/shared/ — config, pg_client, health only
```

**Pipeline:** PDF → `scripts/cases/extract/extract_case_from_source.py` / `extract/ingest_case.py` → `data/drafts/` → integrity gates → human review → `scripts/cases/promote/promote_case_pipeline.py` → `data/cases/`.

**Screening:** in-memory YAML at `POST /jurisdictions/screen`.

## Product boundaries

| Product | API | Web routes + features |
|---------|-----|----------------------|
| Case research | `app/cases/` | `/explore`, `/graph`, `/cases`, `/indexed-cases` → `src/features/cases/` |
| Screening | `app/screening/` | `/jurisdictions`, `/screen` → `src/features/screening/` |

**`jurisdiction` overloaded:** cases = regulator (`EU`/`UK`/`US`); screening = country id (`au`, `de`).

## Commands

```bash
# repo root
docker compose up --build
docker compose --profile embed up embed   # needs GOOGLE_API_KEY

# apps/api/ (.venv active)
.venv/bin/uvicorn main:app --reload
.venv/bin/python -m pytest tests/ -v
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/check_source_links.py
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/evals/run_eval_benchmark.py --config ../../data/evals/benchmark.market_definition.ci.yaml
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
.venv/bin/ruff check .

# apps/web/
npm run dev
npm run lint && npm run build
```

Env: `DATABASE_URL`, `DATA_CASES_PATH`, `DATA_CASE_INDEX_PATH`, `GOOGLE_API_KEY`.

## Non-negotiables

- YAML is source of truth; Postgres is derived.
- Drafts never auto-promote to `data/cases/`.
- Verbatim `quote_snippet` at stated page/paragraph; else omit and mark `SOURCE NEEDED`.
- Complaint allegations → `definition_status: discussed`, not `defined`.
- Surgical changes only; no drive-by refactors.
- No auth, observability, or new abstractions unless the spec requires them.

## Spec-driven development

**Trivial** (typo, one-line fix with test): implement directly.

**Non-trivial** (>3 files, schema change, restructure, new feature):

1. **Spec** in `docs/specs/YYYY-MM-DD-name.md` — goal, approach, files, verification (not progress/status).
2. **Small PR** — one spec, one change set.
3. **Verify** — every command/check from the spec.
4. **Independent review** — once the PR is open and the user has no outstanding comments, spawn a *fresh* sub-agent on a different model (e.g. Sonnet, for uncorrelated judgement — same reason the pipeline favours independent extraction over one model rubber-stamping another) to critically review the diff. Triage its findings, fix the real ones, and report what you accepted or rejected and why.
5. **Progress** — update `ROADMAP.md` only; do not duplicate status in specs or DDRs. Move the implemented spec to `docs/specs/completed/`.

**DDRs** (`docs/architecture/decisions/`) — decisions and rationale; reference when changing that area.

## How to work (bias to caution over speed; use judgment on trivial tasks)
- **Think before coding.** State assumptions explicitly; if uncertain, ask. 
If multiple interpretations or a simpler approach exist, surface them — 
don't pick silently. When something is unclear, stop and name it.
- **Simplicity first.** Write the minimum code that solves the problem — 
nothing speculative. No unrequested features, abstractions for single-use 
code, "flexibility," or error handling for impossible cases. If 200 lines 
could be 50, rewrite it.
- **Surgical changes.** Touch only what the request requires; every changed 
line should trace to it. Match existing style; don't refactor what isn't 
broken or "improve" adjacent code. Remove only the orphans your own changes 
created — flag pre-existing dead code, don't delete it unasked.
- **Goal-driven execution.** Turn tasks into verifiable criteria and loop 
until met (e.g. "fix the bug" → write a failing test that reproduces it, 
then make it pass; "refactor X" → tests green before and after). For multi-
step work, state a brief plan with a verify step each.
- **Name by purpose, not by plan.** Never bake transient planning labels — 
`phase`, `gap`, `step`, ROADMAP/PR numbers — into durable artifacts (variable, 
file, function names; docstrings; comments). They read as noise once the plan 
moves on. Describe what the thing does, not which task introduced it.
- **Explain after implementing.** Close every non-trivial change with a short 
plain-English summary (3–5 bullets). Lead with the underlying concept — what 
problem this solves and why the pattern exists — then explain what specifically 
changed. Assume the reader is still building their mental model; teach the "why" 
before the "what".

## Key docs

- `README.md` — onboarding
- `docs/architecture/overview.md` — system map
- `ROADMAP.md` — phased work to production (single source of truth for progress)
- `docs/specs/completed/2026-06-24-restructure-layout.md` — repo layout spec
