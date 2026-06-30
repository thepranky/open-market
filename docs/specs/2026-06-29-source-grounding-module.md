# Spec: Source grounding module (ROADMAP 4.7)

## Goal

Create one shared source-grounding implementation for fetching source documents, normalising text, matching quoted passages, and reporting grounding issues. Before this change, case integrity and jurisdiction passage verification duplicate the same mechanics in different shapes: `check_source_integrity.py` owns case PDF/HTML fetching, quote matching, page-cache checks, and issue policy, while `source_fetcher.py` and `jurisdiction_passages.py` own a separate fetch/normalise/match path for screening. After this change, both products keep their own data contracts but adapt into one grounding interface.

Out of scope:

- Merging case `SourcePassage` and jurisdiction `SourcePassage` Pydantic models. DDR-0 and DDR-A intentionally keep those product-owned.
- Mass-repairing bad quotes, stale URLs, page numbers, or jurisdiction YAML.
- Replacing the field-path grounding work already specified in `docs/specs/2026-06-25-expand-field-grounding.md`.
- Changing which issue levels block promotion or verification. Callers keep their existing policy choices.
- Adding new external source providers beyond the current HTTP/PDF/HTML behavior.

## Approach

Create `app/shared/source_grounding/` as an implementation module, not a shared domain model package. The external interface is a small set of implementation-agnostic records:

```python
GroundingDocument(
    document_id: str,
    title: str | None,
    primary_url: str | None,
    document_type: str | None,
)

GroundingPassage(
    passage_id: str,
    document_id: str,
    quote: str,
    page: int | None = None,
    field_refs: list[str] = [],
)

verify_grounding(
    documents: list[GroundingDocument],
    passages: list[GroundingPassage],
    *,
    fetcher: SourceFetcher,
    cache: PageCache | None,
    options: GroundingOptions,
) -> GroundingReport
```

The module owns:

- URL fetch result types, content-type handling, bot/SSL/broken-link statuses.
- PDF/HTML text extraction through `app.shared.utils.pdf_extractor`.
- Quote normalisation and approximate quote matching.
- Optional page-cache lookup and "quote found on another page" reporting.
- Document-level URL heuristics that are genuinely product-neutral.
- Structured `GroundingIssue` records with stable issue codes and levels.

Product-specific adapters convert domain models into those records:

- Case adapter: `scripts/cases/integrity/check_source_integrity.py` becomes a CLI and case adapter. It still loads case YAML, applies case-specific document URL priority (`pdf_url`, then `case_page_url`, then `url`), preserves the current terminal summary, and maps `GroundingReport` issues back to the existing output.
- Screening adapter: `app/screening/services/jurisdiction_passages.py` keeps condition support, numeric verification, sidecar updates, and missing authoritative-condition checks. It delegates fetch and quote grounding to the shared module before applying screening-specific numeric logic.
- `check_source_links.py` should either call the shared document-fetch path or share the same low-level fetcher so link liveness does not drift from quote grounding.

This is a ports-and-adapters shape only where a second adapter already exists: production HTTP/PDF fetching and tests that provide fixture/in-memory fetchers. Do not add a remote-service-style port for code that only has one implementation.

Why not a shared `SourcePassage` model? The fields mean different things. Case passages point at source documents, pages, markets, theories, and legal propositions; jurisdiction passages point at statutory conditions and field paths. Sharing the implementation gives leverage without creating a false domain contract.

## Files

| File | Change |
|------|--------|
| `apps/api/app/shared/source_grounding/__init__.py` | Export the small grounding interface. |
| `apps/api/app/shared/source_grounding/models.py` | Add `GroundingDocument`, `GroundingPassage`, `GroundingIssue`, `GroundingReport`, `GroundingOptions`, fetch status/result types. |
| `apps/api/app/shared/source_grounding/fetcher.py` | Move shared HTTP fetch, content-type handling, PDF/HTML extraction, and URL cache-key behavior here. |
| `apps/api/app/shared/source_grounding/matching.py` | Move quote/text normalisation and approximate matching here. |
| `apps/api/app/shared/source_grounding/grounder.py` | Implement `verify_grounding()` over documents, passages, fetcher, optional page cache, and options. |
| `apps/api/scripts/cases/integrity/check_source_integrity.py` | Keep CLI/output compatibility while delegating fetch, text extraction, quote matching, and page-cache grounding to the shared module. |
| `apps/api/scripts/cases/integrity/check_source_links.py` | Use the shared fetch result type or fetcher for document liveness. Preserve current CLI defaults. |
| `apps/api/app/screening/services/source_fetcher.py` | Collapse into a compatibility wrapper around `app.shared.source_grounding.fetcher`, or delete after callers move. |
| `apps/api/app/screening/services/jurisdiction_passages.py` | Adapt jurisdiction passages into `GroundingPassage`, call the shared grounder, then apply condition/numeric/sidecar logic. |
| `apps/api/tests/test_source_grounding.py` | New direct tests for quote matching, fetch status mapping, page-cache behavior, and structured issue codes. |
| Existing source tests | Keep `test_source_integrity.py`, `test_source_fetcher.py`, and `test_verify_jurisdiction_passages.py` green through the old public surfaces. |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest tests/test_source_grounding.py -v
.venv/bin/python -m pytest tests/test_source_integrity.py tests/test_source_fetcher.py -v
.venv/bin/python -m pytest tests/test_verify_jurisdiction_passages.py tests/test_jurisdiction_verification_model.py -v
.venv/bin/python -m pytest tests/test_check_source_links.py -v

# Case CLI compatibility: same scoped interface, same summary shape.
.venv/bin/python scripts/cases/integrity/check_source_integrity.py \
  --cases-dir ../../data/cases \
  --case-id eu_daimler_geely_smart_2020 \
  --no-cache

# Screening push gate still exercises jurisdiction passage grounding.
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push

.venv/bin/ruff check \
  app/shared/source_grounding \
  app/screening/services/jurisdiction_passages.py \
  scripts/cases/integrity/check_source_integrity.py \
  scripts/cases/integrity/check_source_links.py \
  tests/test_source_grounding.py
```

Expected results: pytest and ruff exit 0. The case integrity CLI still prints the existing per-case issue list and `Total: ... error(s), ... warning(s)` summary. The screening push tier still updates sidecars through the existing verification model.

## Rollback

Revert the new `app/shared/source_grounding/` package and restore the old case and screening fetch/match implementations. No data migration is involved because the shared module introduces no YAML fields.
