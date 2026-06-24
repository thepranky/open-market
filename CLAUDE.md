# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CompMap — a market-definition research graph for competition lawyers, plus a merger-control threshold screening engine. Two products share one repo:

1. **Case research** — source-linked YAML records of EU/UK/US merger decisions, queryable by sector, market, theory of harm, outcome, with semantic search and graph views.
2. **Jurisdiction screening** — `data/jurisdictions/*.yaml` profiles of merger-control thresholds across ~60 jurisdictions, evaluated against a deal by `threshold_engine.py`.

> **README/spec drift:** `README.md` and `v0-spec.md` describe the original v0 (Neo4j-centric, 5 sample cases). The repo has moved well past that. The live datastore is **Postgres + pgvector**, not Neo4j; there are 270+ cases and ~60 jurisdiction profiles. Neo4j code (`core/neo4j_client.py`, `graph_service.py`, `graph/*.cypher`) is legacy and optional — graph routes fall back to YAML-derived data. Trust the code and `docs/`, not the README, when they disagree.

## Layout

- `apps/api/` — FastAPI backend (Python 3.10). `app/` is the web service; `scripts/` (41 files) is the data pipeline; `tests/` is the pytest suite.
- `apps/web/` — Next.js 14 frontend (App Router, TypeScript, Tailwind). Pages: `/explore`, `/cases/[case_id]`, `/indexed-cases`, `/jurisdictions`, `/screen` (deal-intake chat), `/graph`.
- `data/` — canonical source of truth (all YAML). `cases/{eu,uk,us}/` canonical case records; `drafts/` AI-extracted drafts (never promoted automatically); `jurisdictions/` threshold profiles; `evals/gold/` regression fixtures; `case_index/`, `source_text/` (PDF text cache), `concepts/`, `review_learning/`, `pipeline_profiles/`.
- `docs/` — the real design docs. Start with `docs/ingestion-design.md`, `docs/jurisdiction-verification-build.md`, `docs/human-promotion-checklist.md`.

## Common commands

All backend commands run from `apps/api/` with the venv active (`.venv/bin/python`).

```bash
# Setup
cd apps/api && python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run the full stack (Postgres + API + web)
docker compose up --build            # from repo root; postgres on host :5433, api :8000, web :3000
docker compose --profile embed up embed   # one-shot: embed cases into pgvector

# Run API locally (needs DATABASE_URL to a running pgvector Postgres)
cd apps/api && .venv/bin/uvicorn main:app --reload

# Frontend
cd apps/web && npm install && npm run dev    # lint: npm run lint; build: npm run build

# Tests (no DB required; graph/search fall back to YAML)
cd apps/api && .venv/bin/python -m pytest tests/ -v
.venv/bin/python -m pytest tests/test_schema.py -v          # single file
.venv/bin/python -m pytest tests/test_schema.py::test_name  # single test

# Lint Python
cd apps/api && .venv/bin/ruff check .
```

## Data validation gates (run before committing data changes)

These are the integrity gates; CI runs a subset. All are non-mutating and exit non-zero on failure.

```bash
cd apps/api
.venv/bin/python scripts/validate_cases.py --cases-dir ../../data/cases   # Pydantic schema (canonical only)
.venv/bin/python scripts/check_source_links.py                            # URLs resolve
.venv/bin/python scripts/check_source_integrity.py --cases-dir ../../data/cases  # quotes grounded in source PDFs
.venv/bin/python scripts/run_eval_benchmark.py --config ../../data/evals/benchmark.market_definition.ci.yaml

# Jurisdiction verification (orchestrator mirrors CI tiers)
.venv/bin/python scripts/run_jurisdiction_verification.py --tier push     # schema + completeness + regression
#   tiers: push (fast, CI-on-PR) | nightly (+offline passages/staleness) | full (live URL/quote fetch)
```

## Architecture

**Backend service** (`apps/api/app/`): `routers/` → `services/` → `loader/` (YAML) + `core/pg_client.py` (asyncpg pool to pgvector). `models/` holds the Pydantic schemas — `case.py` (`CaseRecord`) and `jurisdiction.py` (`JurisdictionRule`) are the two contracts everything else conforms to. Semantic search uses Google `gemini-embedding-001` (768-dim) via `embedding_service.py`, stored in pgvector (`migrations/001_create_vector_schema.sql`).

**Threshold engine** (`services/threshold_engine.py`): loads `data/jurisdictions/*.yaml`, evaluates a deal's revenue/share/asset parameters against each jurisdiction's `threshold_tests`, returns per-jurisdiction status + triggering test + gap-to-trigger. Exposed at `/jurisdictions/screen`.

**Extraction pipeline** (`apps/api/scripts/`): the path from a source PDF to a canonical case record. Key stages, all driven by standalone scripts:
- `extract_case_from_source.py` / `ingest_case.py` — fetch PDF → Claude extraction → **draft** YAML (written to `data/drafts/`, never `data/cases/`).
- Structural + source-integrity gates ground every `quote_snippet` against the actual PDF text. A quote not found in source is rejected.
- `review_draft.py` (LLM critic triage), `create_review_learning_log.py` / `apply_review_learning.py` (capture corrections, propose schema/prompt fixes).
- `promote_draft_to_canonical.py` / `promote_case_pipeline.py` — strip draft-only fields, run full Pydantic validation, move into `data/cases/`. This is the only way a draft becomes canonical.
- Bulk runs: `run_bulk_extraction.py`, `bulk_promote_pass.py`. Pipeline behaviour is configured per jurisdiction/doc-type via `data/pipeline_profiles/`.

## Working norms specific to this repo

- **YAML is the source of truth.** Postgres/pgvector and any Neo4j graph are derived stores, rebuilt by seed/embed scripts. Never treat the database as authoritative over the YAML.
- **Drafts vs canonical is a hard boundary.** AI extraction writes to `data/drafts/` only. Promotion to `data/cases/` requires passing validation + integrity gates. Drafts intentionally omit fields (`metadata`, `procedure_stage`) that promotion adds — so `validate_cases.py` (full Pydantic) applies to canonical records only; drafts get a lighter structural check.
- **Ground every proposition in primary sources.** Every `source_passage` must cite a `source_document_id` in the same record, and its `quote_snippet` must be verbatim text found at the stated page/paragraph in the linked document — never paraphrased or AI-reconstructed. If no verified source exists, omit the passage and mark notes `SOURCE NEEDED`. Do not characterise complaint allegations as adjudicated findings (`definition_status: discussed`, not `defined`). Verification grounds against official primary sources, never against AI-paraphrased fixtures.
- **Long-running extraction/verification runs:** use `caffeinate` + `nohup` + `timeout` for overnight bulk jobs.
- **Cost note:** the `$0.53` cost display in extraction scripts is inflated (uses a Sonnet rate); "simplified" skipped cases are not failures.
