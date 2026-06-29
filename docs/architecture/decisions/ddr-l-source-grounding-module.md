# DDR-L: Source grounding module

**Date:** 2026-06-29

## Decision

Create a shared source-grounding implementation for fetch, text extraction, quote matching, page-cache checks, and structured grounding issues, while keeping case and jurisdiction passage models separate. The implementation spec is `docs/specs/2026-06-29-source-grounding-module.md`.

## Context

Case research and jurisdiction screening both need lawyer-grade source grounding, but their domain contracts differ. Case passages support markets, theories, pages, and source documents. Jurisdiction passages support threshold conditions and field paths. The current implementation duplicates lower-level mechanics across `check_source_integrity.py`, `source_fetcher.py`, and `jurisdiction_passages.py`.

## Why this way

The shared behavior is implementation detail, not domain language. A deep source-grounding module gives both products the same fetch and quote-matching behavior without implying that their `SourcePassage` fields have the same meaning. That preserves the DDR-0 and DDR-A decision that domain models are product-owned rather than placed in a false shared model package.

## Alternatives considered

- Unify both `SourcePassage` Pydantic models. Rejected because the common name hides different semantics.
- Leave duplicate fetch and quote-matching code. Rejected because integrity behavior can drift across case promotion and jurisdiction verification.
- Build a broad source-ingestion framework. Rejected because the repo only needs HTTP/PDF/HTML grounding today.

## Consequences

- Source-grounding bugs can be fixed once and verified through shared tests.
- Case and screening adapters still own policy: which URLs count, which issue levels block, how numeric checks and sidecars are interpreted.
- The module creates a real seam only where tests use a fake fetcher and production uses the HTTP/PDF adapter.
