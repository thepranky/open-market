---
name: integrity
description: Run Meridian's data integrity gates before opening a PR or promoting a draft. Use this whenever case YAML files have been added or changed — it catches dead PDF links and misquoted passages that CI cannot check (CI only runs schema and semantic-lint). Always run /integrity before /ship on any PR that touches data/cases/. Invoke with /integrity.
---

# integrity

Run all integrity gates on the canonical case data. Always called from the repo root; the skill handles the `apps/api/` working directory internally.

## Two tiers — know which to run

**Fast gates** (also run by CI on every PR — run these locally for instant feedback):
- `validate_cases.py` — Pydantic schema: correct field types, required fields present
- `lint_case_semantics.py` — Lawyer rules: complaint markets must be `discussed` not `defined`; no dangling `supports_*` refs

**Grounding gates** (NOT in CI — only ever run locally; protect the product's core trust signal):
- `check_source_links.py` — Live HTTP check that every `pdf_url` resolves (catches dead or redirected links)
- `check_source_integrity.py` — Verifies each `quote_snippet` actually appears at the stated page in the PDF

## When to run each tier

| Situation | Run |
|---|---|
| Edited definition_status or other YAML fields | Fast only |
| Added or changed any `quote_snippet` | Full (both tiers) |
| Added or changed any `pdf_url` | Full (both tiers) |
| Before opening a PR touching `data/cases/` | Full (both tiers) |
| Promoting a draft to canonical | Full (both tiers) |

## Commands

All commands run from `apps/api/` with the venv Python.

### Full check (both tiers)

```bash
cd apps/api
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/lint_case_semantics.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/check_source_links.py
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir ../../data/cases
```

### Fast check only (no network calls)

```bash
cd apps/api
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/lint_case_semantics.py --cases-dir ../../data/cases
```

### Scoped to a single case (faster during active editing)

```bash
cd apps/api
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/lint_case_semantics.py --cases-dir ../../data/cases --case-id <case_id>
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir ../../data/cases --case-id <case_id>
```

## Interpreting output

- **`validate_cases.py`** — exits non-zero and lists field errors if schema invalid
- **`lint_case_semantics.py`** — prints `FAIL: <case_id>: <rule>` per violation
- **`check_source_links.py`** — prints `FAIL <url>` per dead link; exit 0 if all live
- **`check_source_integrity.py`** — prints `PASS`/`FAIL` per passage; FAIL = `quote_snippet` not found at stated page in the PDF

Any FAIL from any gate is a blocker. Do not open a PR or promote until all pass.

## What CI already covers

The `data-contracts` CI workflow runs `validate_cases.py`, `lint_case_semantics.py`, and `validate_case_index.py` on every PR touching `data/cases/` or `data/case_index/`. Running the fast gates locally here gives you the same signal before pushing. The grounding gates (`check_source_links`, `check_source_integrity`) are **never** run by CI — they require live network access and PDF downloads that are too slow and flaky for CI.
