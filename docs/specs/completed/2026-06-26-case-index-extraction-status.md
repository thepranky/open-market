# Spec: `extraction_status` for case-index entries

## Goal

Make a `CaseIndexEntry` say whether it is a candidate for deep extraction into a
canonical `CaseRecord`. Today an unpromoted index entry is ambiguous: it may be a
simplified-procedure clearance with no market analysis to extract, or a substantive
decision still awaiting extraction. The bulk-extraction lane therefore keeps
re-fetching and SKIPping simplified cases, and a human prioritising work cannot tell
the two apart.

Observed during the dual-extraction end-to-end test: every unpromoted EU entry
sampled (25/25) was a 2-page simplified clearance the pipeline correctly SKIPs —
the substantive EU decisions are largely already promoted.

Add one field that records this, so simplified entries stay in the discovery index
(they are real, citeable decisions) but drop out of the extraction backlog.

Out of scope:
- Any web/API change (the field exists for the loader and future UI badge; no route
  is added here).
- Re-scraping or changing existing index *content* beyond adding the field.
- Changing the extraction pipeline's own simplified-SKIP behaviour.

## Approach

### Schema

Add to `CaseIndexEntry` (`apps/api/app/cases/models/case_index.py`):

```python
extraction_status: Literal["pending", "not_applicable", "extracted"] = "pending"
```

- `extracted` — a canonical `CaseRecord` exists in `data/cases/<jur>/<id>.yaml`.
- `not_applicable` — simplified procedure / no market-analysis sections; nothing to
  extract.
- `pending` — substantive, not yet extracted (the default, so existing YAMLs without
  the field still validate under `extra="forbid"`).

The field is additive and defaulted, so every existing entry loads unchanged.

### Classifier (one-time, resumable backfill)

New `apps/api/scripts/cases/discovery/classify_index_extraction_status.py`:

For each index entry:
1. If a canonical record exists for its `case_id` → `extracted` (no fetch).
2. Else fetch `pdf_url` and count pages:
   - `page_count <= --max-simplified-pages` (default 3) → `not_applicable`.
   - otherwise → `pending`.
3. Write the field back into the YAML in place, preserving key order.

Page count is the detector because it is the same signal the pipeline already keys
on (simplified EU clearances are 2 pages) and needs no LLM call. It is a heuristic,
documented as such: the threshold is configurable. A missing URL or failed fetch is
treated as *unknown* (distinct from a confident `pending`): a never-classified entry
stays `pending`, and a settled `not_applicable`/`extracted` is **kept** — a transient
404 during `--reclassify` must never silently downgrade a correct classification.

Flags: `--index-dir` (default `data/case_index`), `--jurisdiction eu|uk|us`,
`--case-id` (single), `--limit N` (sampling), `--max-simplified-pages 3`,
`--reclassify` (re-evaluate entries already classified), `--dry-run`. Idempotent:
without `--reclassify`, entries already carrying a non-default status whose canonical
state is unchanged are skipped, so the backfill can resume.

### Why a script, not in-scrape

The detector needs the resolved `pdf_url`, which is populated by a later resolver
stage, and the backfill must run over thousands of existing entries. A standalone,
resumable script is the right shape; `scrape_eu_index.py` keeps emitting `pending`
via the model default, and the classifier upgrades entries as PDFs resolve.

## Files

| File | Change |
|------|--------|
| `apps/api/app/cases/models/case_index.py` | Add `extraction_status` Literal field, default `pending` |
| `apps/api/scripts/cases/discovery/classify_index_extraction_status.py` | New — backfill classifier (canonical-exists / page-count) |
| `apps/api/tests/test_classify_index_extraction_status.py` | New — classifier logic with injected page-counter + temp index dir |

## Verification

```bash
cd apps/api
# 1. Schema accepts the new field and still defaults
.venv/bin/python -c "from app.cases.models.case_index import CaseIndexEntry; \
  print(CaseIndexEntry(case_id='x', case_name='X', jurisdiction='EU', authority='EC', \
  decision_date='2022-01-01', sector='x', outcome='cleared').extraction_status)"   # -> pending

# 2. Existing index still validates (field is optional/defaulted)
.venv/bin/python scripts/cases/discovery/validate_case_index.py

# 3. Classifier dry-run on a small sample
.venv/bin/python scripts/cases/discovery/classify_index_extraction_status.py \
  --jurisdiction eu --limit 5 --dry-run

# 4. Unit tests
.venv/bin/python -m pytest tests/test_classify_index_extraction_status.py -v
```

Expected: schema prints `pending`; existing index validates; the dry-run reports a
mix of `extracted` (canonical exists) and `not_applicable` (2-page PDFs) without
writing; unit tests pass.

## Rollback

The field is additive and defaulted; removing it reverts the schema with no data
migration. Classifier output is a per-entry string that can be re-run or reset by
deleting the key.
