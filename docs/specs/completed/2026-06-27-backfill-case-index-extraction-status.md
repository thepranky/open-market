# Backfill Case-Index Extraction Status

## Goal

Persist an explicit `extraction_status` on indexed case records so the extraction
queue and frontend can distinguish:

- `pending`: substantive source material exists and extraction is still needed.
- `not_applicable`: metadata-only record; no substantive market-analysis
  extraction is planned.
- `extracted`: a canonical record already exists.
- missing status: source material is unresolved.

## Approach

- Make missing `CaseIndexEntry.extraction_status` remain unresolved instead of
  defaulting to `pending`.
- Ensure the classifier writes an explicit `pending` status when it confidently
  identifies a long, extractable PDF.
- Keep `not_applicable` and `extracted` out of the bulk extraction queue.
- Expose `pdf_url`, `pdf_language`, and `extraction_status` on indexed-case API
  responses and the indexed-case frontend page.
- Mark abandoned indexed records as `not_applicable` so they remain visible but
  do not enter extraction.

## Verification

- `cd apps/api && .venv/bin/python -m pytest tests/test_indexed_cases_api.py tests/test_graph_seed_models.py tests/test_classify_index_extraction_status.py tests/test_pdf_resolvers.py -v`
- `cd apps/api && .venv/bin/ruff check app/cases/models/api_responses.py app/cases/models/case_index.py scripts/cases/discovery/classify_index_extraction_status.py scripts/cases/discovery/pdf_resolvers.py tests/test_indexed_cases_api.py tests/test_graph_seed_models.py tests/test_classify_index_extraction_status.py tests/test_pdf_resolvers.py`
- `cd apps/api && .venv/bin/python scripts/cases/discovery/validate_case_index.py --index-dir ../../data/case_index`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run build`
