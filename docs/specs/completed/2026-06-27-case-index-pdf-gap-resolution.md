# Spec: Case-index PDF gap resolution

## Goal

Close the remaining `pdf_url` gaps in `data/case_index/{eu,uk,us}/` so indexed
cases can either enter `ingest_case.py --from-index` or be explicitly identified
as having no extractable decision PDF.

The target gap is every index entry whose `pdf_url` is absent after the shared
resolver work:

- EU: 1 entry, `eu_illumina_grail_2022`, an annulment / appeal-shaped case that
  the Cellar resolver intentionally returns as `manual_required`.
- UK: 14 entries, mostly older Competition Commission pages and abandoned /
  cleared matters. The resolver returns a mix of `manual_required`, `not_found`,
  and default outcome-filter skips unless run with `--all-outcomes`.
- US: 10 entries. DOJ pages often expose litigation records without `.pdf`
  links; FTC pages expose multiple orders, complaints, or opinions where the
  resolver is correctly conservative.

Out of scope:

- Building new US index discovery. That remains separate discovery work.
- Running extraction or promotion after URLs are filled.
- Weakening resolver ranking just to reduce the miss count. A wrong `pdf_url`
  is worse than an explicit unresolved entry.
- Adding free-form fields to case-index YAML. `CaseIndexEntry` forbids extra
  fields; use a separate audit artifact for manual notes.

## Approach

### Treat this as a bounded triage pass, not a new resolver rewrite

Run the shared resolver in full audit mode:

```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction all \
  --all-outcomes \
  --dry-run \
  --delay 0 \
  --timeout 20
```

Use `--all-outcomes` because the normal UK outcome filter is optimized for bulk
extraction, not for closing the data gap. Without it, abandoned and brief
clearance entries stay hidden as `skipped_outcome`.

For each unresolved entry, inspect the authority page manually and classify it
into one of three outcomes:

- **Direct decision PDF found:** write the direct PDF URL into that entry's
  `pdf_url` using a targeted single-case command or a surgical YAML edit.
- **Only non-decision documents found:** leave `pdf_url` absent and record the
  reason in the audit artifact.
- **No official public PDF found:** leave `pdf_url` absent and record the source
  checked in the audit artifact.

When a direct PDF is found, prefer official authority URLs. Use court or tribunal
PDFs only when the indexed entry is litigation-shaped and the merits opinion is
the source document that extraction should read.

### Use `ingest_case.py --from-index --pdf-url` as the acceptance smoke test

For every manually chosen URL, run the single-case ingestion path far enough to
prove the scaffold and PDF cache can use it:

```bash
cd apps/api
.venv/bin/python scripts/cases/extract/ingest_case.py \
  --case-id <case_id> \
  --from-index \
  --pdf-url <direct_pdf_url> \
  --no-claude
```

This should write a scaffold under `data/drafts/{jurisdiction}/`, fetch or read
the PDF cache, and fail only on expected no-extraction conditions. If the PDF is
HTML, a portal page, an order, a complaint, or an unrelated procedural filing,
do not write it to the index.

### Keep unresolved cases visible

Create one audit file for the pass:

```text
data/batch_runs/case_index_pdf_resolution_YYYYMMDD.yaml
```

The audit file should be structured and small:

```yaml
generated_at: "YYYY-MM-DD"
command: ".venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py --jurisdiction all --all-outcomes --dry-run --delay 0 --timeout 20"
counts:
  missing_before:
    eu: 1
    uk: 14
    us: 10
  resolved: 0
  unresolved: 0
entries:
  - case_id: uk_example_2020
    jurisdiction: UK
    resolver_status: manual_required
    resolution: direct_pdf_found
    pdf_url: https://...
    note: official final report PDF
```

Allowed `resolution` values:

- `direct_pdf_found`
- `no_decision_pdf`
- `source_page_missing_pdf`
- `wrong_document_type_only`
- `defer_to_extraction_status`

This keeps the remaining count auditable without adding schema noise to every
`CaseIndexEntry`.

### Coordinate with extraction-status backfill

5.16 is still the prerequisite for backlog sizing: all current entries are
`extraction_status: pending`. This spec should not force non-substantive or
abandoned cases through extraction just because they lack a PDF.

After URL triage, rerun the classifier dry-run:

```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/classify_index_extraction_status.py \
  --jurisdiction all \
  --dry-run
```

Entries with no decision PDF and no extractable market-analysis document should
remain unresolved in the audit and be handled by the status backfill, not by
inventing placeholder PDFs.

### Only improve resolver rules when the manual pass proves a repeatable miss

If manual inspection finds a narrow, repeated pattern that the resolver can pick
conservatively, add that rule with tests. Examples:

- A UK legacy filename pattern that clearly means final report and is currently
  scored `0`.
- A US anchor-text pattern that clearly denotes a merits opinion and is not a
  complaint, order, proposed judgment, brief, exhibit, or press release.

Do not add one-off case IDs to resolver logic. One-off decisions belong in the
data file and the audit.

## Files

| File | Change |
|------|--------|
| `data/case_index/{eu,uk,us}/*.yaml` | Add `pdf_url` only for entries where a direct substantive decision PDF is identified; optionally add `pdf_language` only when known from an official manifestation. |
| `data/batch_runs/case_index_pdf_resolution_YYYYMMDD.yaml` | New audit artifact listing every entry reviewed, resolver status, manual resolution, final URL if any, and unresolved reason. |
| `apps/api/scripts/cases/discovery/pdf_resolvers.py` | Optional only if the manual pass identifies a repeated conservative ranking rule. |
| `apps/api/tests/test_pdf_resolvers.py` | Required only if resolver ranking changes. |
| `apps/api/tests/test_resolve_case_index_pdf_urls.py` | Required only if batch CLI behavior changes. |
| `docs/operations/ingestion.md` | Optional clarification if the manual audit workflow needs operator documentation after implementation. |
| `ROADMAP.md` | Mark the roadmap item complete and record final unresolved counts after verification. |

## Verification

Validate schema after data edits:

```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/validate_case_index.py
```

Confirm there are no accidentally hidden misses:

```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction all \
  --all-outcomes \
  --dry-run \
  --delay 0 \
  --timeout 20
```

Confirm extraction-status triage sees the new URLs:

```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/classify_index_extraction_status.py \
  --jurisdiction all \
  --dry-run
```

For each newly added URL, smoke-test the extraction scaffold:

```bash
cd apps/api
.venv/bin/python scripts/cases/extract/ingest_case.py \
  --case-id <case_id> \
  --from-index \
  --pdf-url <direct_pdf_url> \
  --no-claude
```

If resolver code changes, run the resolver tests:

```bash
cd apps/api
.venv/bin/python -m pytest \
  tests/test_pdf_resolvers.py \
  tests/test_resolve_case_index_pdf_urls.py \
  tests/test_ingest_case_from_index_resolution.py \
  -v
```

Final manual check:

```bash
cd apps/api
.venv/bin/python - <<'PY'
from pathlib import Path
import sys, yaml
sys.path.insert(0, ".")
from app.cases.models.case_index import CaseIndexEntry

root = Path("../..") / "data" / "case_index"
for jur_dir in sorted(root.iterdir()):
    if not jur_dir.is_dir():
        continue
    missing = []
    for path in sorted(jur_dir.glob("*.yaml")):
        entry = CaseIndexEntry.model_validate(yaml.safe_load(path.read_text()))
        if not entry.pdf_url:
            missing.append(entry.case_id)
    print(f"{jur_dir.name}: {len(missing)} missing pdf_url")
    for case_id in missing:
        print(f"  {case_id}")
PY
```

## Rollback

Revert only the touched `data/case_index/{eu,uk,us}/*.yaml` entries and remove
the audit file. If resolver code changed, revert the resolver and matching tests
together. Draft scaffolds or PDF cache files created by `--no-claude` smoke
tests can be deleted; they are generated artifacts, not source data.
