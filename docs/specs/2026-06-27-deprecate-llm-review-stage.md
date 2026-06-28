# Spec: Deprecate Stage 5a LLM review and review-learning loop

## Goal

Remove the Stage 5a LLM critic (`review_draft.py`) and its associated review-learning
loop (`create_review_learning_log.py`, `apply_review_learning.py`) from the extraction
pipeline. Dual extraction (ROADMAP 5.9) supersedes Stage 5a: two cold, independent
extractions produce a conflict surface that is a strictly better review signal than an
LLM self-critiquing one draft. Stage 5a is already skipped in bulk runs and in
`--dual-extract` mode; retaining it adds latency and cost without replacing the human
review step on conflict resolution.

Out of scope:

- `check_review_readiness.py` — a deterministic structural gate (checks for orphaned
  passages, planned-but-empty sections, duplicate snippets). It is not an LLM call, is
  still invoked by `promote_case_pipeline.py` and `run_controlled_case.py`, and is
  listed as a required step in ROADMAP 5.11. It stays in `scripts/cases/review/`.
- Changing the dual-extraction workflow or `compare_extractions.py` — unaffected.
- Promotion guards (`validate_cases.py`, `check_source_integrity.py`) — unaffected.

## Approach

**What to remove**

Three scripts are deleted: `review_draft.py` (LLM critic), `create_review_learning_log.py`
(post-promotion delta capture), and `apply_review_learning.py` (proposal aggregation). Their
call sites are removed from `ingest_case.py` and `promote_case_pipeline.py`. Three
corresponding test files are deleted. The `review/` folder keeps its `__init__.py` and
`check_review_readiness.py`; no folder is removed.

**Call sites**

`ingest_case.py` has two Stage 5a touch-points:

1. `stage_llm_review()` function (lines ~526–605) — remove the function and its import of
   `review_draft`.
2. The Stage 5a dispatch block in `run()` (lines ~1213–1231), the `--llm-review` CLI
   argument (line ~820), the `llm_review_path` variable and its references in the review
   report writer (lines ~299, 499–510), and the `LLM client upfront` comment that cites
   Stage 5a (line ~1033).

`promote_case_pipeline.py` calls `create_review_learning_log.py` (Stage 8) and
`apply_review_learning.py` (Stage 9) via `subprocess.run` after promotion. Remove both
subprocess calls and the `data/review_learning` path references in the status dict and
progress output. Update the pipeline stage-count comment at the top of the file.

**Data**

`data/review_learning/` holds six manually generated delta YAMLs and a `proposals/` folder
produced from four promoted cases. These are historical artifacts from a workflow that no
longer runs; delete the delta files and proposals. Retain the `.gitkeep` so the directory
entry survives in git and operators can see where the files used to live (the directory
itself is harmless and makes the git history readable).

**DDR update**

`ddr-b-extraction-pipeline.md` references `review_draft.py` in its "Before you start"
list, the pipeline diagram, and the Q&A section. Update the diagram to remove the critic
step, strike `review_draft.py` from the read-list, and add a short note recording that
Stage 5a was retired (date + reason) so the DDR reflects the current design.

**Docs**

`docs/operations/ingestion.md` has a Stage 5a section describing `review_draft.py` and a
`data/review_learning/` entry in the data-directory table. Remove the section; remove the
table row.

`docs/operations/promotion-checklist.md` lists steps 7 (create_review_learning_log) and 8
(apply_review_learning). Remove both steps.

`docs/architecture/case-research.md` lists `review_draft.py` in the pipeline flow. Remove
it.

`docs/architecture/overview.md` lists `data/review_learning/` as "Human correction deltas."
Remove the row.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/cases/review/review_draft.py` | Delete |
| `apps/api/scripts/cases/review/create_review_learning_log.py` | Delete |
| `apps/api/scripts/cases/review/apply_review_learning.py` | Delete |
| `apps/api/tests/test_review_draft.py` | Delete |
| `apps/api/tests/test_apply_review_learning.py` | Delete |
| `apps/api/tests/test_create_review_learning_log.py` | Delete |
| `apps/api/scripts/cases/extract/ingest_case.py` | Remove `stage_llm_review()`, `--llm-review` flag, Stage 5a dispatch block, `llm_review_path` variable and report references |
| `apps/api/scripts/cases/promote/promote_case_pipeline.py` | Remove Stage 8 (`create_review_learning_log`) and Stage 9 (`apply_review_learning`) subprocess calls and `data/review_learning` status references |
| `apps/api/tests/test_promote_case_pipeline.py` | Remove assertions that `create_review_learning_log` and `apply_review_learning` appear in the pipeline stage list |
| `data/review_learning/*.yaml` | Delete the 6 delta YAML files; keep `.gitkeep` |
| `data/review_learning/proposals/review_learning_proposals.yaml` | Delete |
| `data/review_learning/proposals/review_learning_proposals.md` | Delete |
| `docs/architecture/decisions/ddr-b-extraction-pipeline.md` | Remove `review_draft.py` from read-list; update pipeline diagram; add retirement note |
| `docs/operations/ingestion.md` | Remove Stage 5a section; remove `data/review_learning/` table row |
| `docs/operations/promotion-checklist.md` | Remove steps 7 and 8 (review-learning loop) |
| `docs/architecture/case-research.md` | Remove `review_draft.py` from pipeline flow |
| `docs/architecture/overview.md` | Remove `data/review_learning/` row |
| `ROADMAP.md` | Mark 5.24 done |

## Verification

```bash
# 1. Deleted scripts no longer exist
ls apps/api/scripts/cases/review/
# Expected: __init__.py  check_review_readiness.py  (only these two)

# 2. No import or subprocess invocation of the removed scripts remains
grep -rn "review_draft\|apply_review_learning\|create_review_learning_log" \
  apps/api/ data/ docs/ \
  | grep -v "docs/specs/2026-06-27-deprecate-llm-review-stage" \
  | grep -v "docs/architecture/decisions/ddr-b-extraction-pipeline"
# Expected: zero hits (ddr-b is the only permitted mention — the retirement note)
# Note: ROADMAP.md is excluded from the search because the 5.24 row names
# the deleted scripts as historical backlinks; that is expected and correct.

# 3. ingest_case.py no longer accepts --llm-review
.venv/bin/python apps/api/scripts/cases/extract/ingest_case.py --help | grep llm
# Expected: no output

# 4. promote_case_pipeline.py dry-run completes without referencing deleted scripts
.venv/bin/python apps/api/scripts/cases/promote/promote_case_pipeline.py \
  --case-id eu_siemens_gamesa_2017 --focus market_definition --dry-run
# Expected: stages printed do not include create_review_learning_log or apply_review_learning

# 5. check_review_readiness.py still works (deterministic gate, must survive)
.venv/bin/python apps/api/scripts/cases/review/check_review_readiness.py --help
# Expected: prints usage without error

# 6. Test suite passes
cd apps/api && .venv/bin/python -m pytest tests/ -v
# Expected: green; the three deleted test files do not appear

# 7. Lint clean
.venv/bin/ruff check .
```
