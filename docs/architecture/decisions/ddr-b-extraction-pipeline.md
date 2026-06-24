# DDR-B: Extraction pipeline

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `apps/api/scripts/cases/extract_case_from_source.py`, `ingest_case.py`
- `apps/api/scripts/cases/review_draft.py`, `promote_case_pipeline.py`
- `docs/operations/ingestion.md`, `promotion-checklist.md`
- `data/pipeline_profiles/` (one example)
- `data/review_learning/` structure

Run (read-only): `promote_case_pipeline.py --dry-run` on a known case if available.

## Agent prompt

> Explain the full case extraction pipeline from PDF URL to canonical YAML. Walk through each script stage, what can fail, and why drafts never auto-promote. Cover `review_draft.py` and the review-learning loop. Explain multi-focus extraction at a high level (`docs/operations/hard-cases.md`). Compare pipeline-in-scripts vs a workflow engine. What's missing for scale to 1000 cases?

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
