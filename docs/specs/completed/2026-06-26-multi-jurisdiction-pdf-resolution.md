# Spec: Multi-jurisdiction PDF resolution

## Goal

Make `data/case_index/{eu,uk,us}/` entries consistently extractable by resolving a
direct decision-document `pdf_url` from each entry's `source_url`, then wiring that
same resolver path into `ingest_case.py --from-index`.

This is the intake counterpart to dual extraction: dual extraction can reduce human
review work only after indexed cases can reliably produce a source PDF and a draft.
The current implementation is fragmented:

- EU has `resolve_eu_pdf_urls.py` plus duplicated CELEX logic inside
  `ingest_case.py`.
- UK has `resolve_uk_pdf_urls.py` with its own fetch, ranking, and YAML patching.
- US index entries have `source_url`s but no `pdf_url`s.

Out of scope:

- Scraping new index entries. This spec resolves PDFs for existing
  `CaseIndexEntry` records; `scrape_{eu,uk}_index.py` remain separate discovery
  jobs.
- Promoting drafts or running dual extraction automatically.
- Replacing authority-specific judgment. Each authority still needs its own
  adapter because the publication systems differ.
- Resolving every historical miss. The resolver must explain misses and leave them
  for manual inspection rather than guessing.

## Approach

### One resolver contract, authority-specific adapters

Introduce a shared resolver module under `apps/api/scripts/cases/discovery/`:

```python
@dataclass(frozen=True)
class PdfCandidate:
    url: str
    label: str
    source: str
    score: int
    reason: str

@dataclass(frozen=True)
class PdfResolution:
    status: Literal["resolved", "manual_required", "not_found", "error"]
    pdf_url: str | None
    candidates: list[PdfCandidate]
    resolver: str
    reason: str
```

Each adapter implements:

```python
class PdfResolver(Protocol):
    jurisdiction: str
    authority: str | None

    def can_handle(self, entry: CaseIndexEntry) -> bool: ...
    def resolve(self, entry: CaseIndexEntry, *, timeout: float) -> PdfResolution: ...
```

The contract is deliberately small and MECE:

- **Extract candidates** from the authority page or derived endpoint.
- **Rank candidates** according to authority-specific document-role rules.
- **Return a structured decision** with a reason, never patch YAML directly.

Adapters own authority knowledge; batch processing, YAML IO, dry-run behavior,
overwrite behavior, rate limiting, and reporting are shared.

### Initial adapters

**EU Cellar adapter.** Move the CELEX resolver currently duplicated in
`resolve_eu_pdf_urls.py` and `ingest_case.py` into the shared module. It handles
standard EUR-Lex / Cellar Phase I decisions by deriving
`3{year}M{case_number}` from `source_url` and `decision_date`, then confirming the
endpoint resolves to PDF. If the outcome or URL shape suggests a Phase II / manual
Commission decision outside Cellar, return `manual_required` rather than a generic
failure.

**UK GOV.UK adapter.** Move the existing GOV.UK page fetch and PDF scoring from
`resolve_uk_pdf_urls.py` into the shared module. Preserve the key behavior: rank
final reports above provisional findings, reject orders, undertakings, appendices,
notices, submissions, and other non-decision documents, and only fall back to a
single surviving PDF when disqualification leaves exactly one plausible document.

**US DOJ / FTC adapter.** Add an adapter for `jurisdiction == "US"` that fetches the
DOJ or FTC case page, extracts linked PDFs, and ranks likely merits documents above
complaints, press releases, appendices, orders, and procedural filings. For this
first pass, use conservative scoring:

- court opinion / memorandum opinion / findings of fact / decision and order:
  high score,
- complaint / amended complaint / proposed order / press release / notice:
  low or disqualified,
- multiple high-scoring candidates with close scores: `manual_required`, with
  candidates listed.

US publication pages often link litigation records rather than one canonical merger
decision. The adapter should prefer a correct manual-required result over an
overconfident wrong `pdf_url`.

### Shared batch CLI

Add `resolve_case_index_pdf_urls.py` as the shared entrypoint:

```bash
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction us \
  --dry-run \
  --limit 5
```

Required behavior:

- loads entries through `CaseIndexEntry` so resolver inputs match the schema,
- skips entries with `pdf_url` unless `--overwrite` is set,
- supports `--jurisdiction`, `--authority`, `--case-id`, `--all-outcomes`,
  `--dry-run`, `--limit`, `--overwrite`, `--delay`, and `--timeout`,
- writes only `pdf_url` and optional resolver metadata fields if adopted below,
- prints grouped counts for `resolved`, `manual_required`, `not_found`, `error`,
  `skipped_existing`, and `skipped_outcome`,
- exits non-zero only for operational errors, not for ordinary unresolved cases.

Keep `resolve_eu_pdf_urls.py` and `resolve_uk_pdf_urls.py` as thin compatibility
wrappers for one release:

- they parse their existing flags,
- call the shared CLI/library path,
- print a deprecation note naming `resolve_case_index_pdf_urls.py`.

This avoids breaking existing operator muscle memory while removing duplicate
resolver logic.

### YAML writes

Use one shared YAML writer for case-index records. Do not let each resolver patch
files independently.

The writer should preserve the existing top-level field order:

```yaml
case_id
case_name
jurisdiction
authority
decision_date
sector
outcome
case_type
source_url
pdf_url
ai_summary
parties
concept_refs
```

If resolver metadata is added, keep it outside canonical case fields and make it
optional in `CaseIndexEntry`, for example:

```yaml
pdf_resolution:
  resolver: uk_govuk
  resolved_at: "2026-06-26"
  status: resolved
  reason: final_report_highest_score
```

If that metadata adds noise to diffs, skip it in v1 and rely on dry-run reports.
Do not introduce free-form fields without updating `CaseIndexEntry`; the schema
uses `extra="forbid"`.

### `ingest_case.py --from-index`

Replace `_resolve_pdf_url_from_ec_portal()` with the shared resolver registry.
Resolution order for `--from-index`:

1. explicit `--pdf-url`,
2. `pdf_url` already present on the index entry,
3. shared resolver selected from the index entry,
4. fail with the structured resolver reason and candidate list.

The scaffold remains unchanged: one decision `source_document` with
`case_page_url = source_url` and `pdf_url = resolved pdf_url`.

This keeps one source of truth for resolver behavior. Batch resolution and single
case ingestion should never diverge again.

### Why not one generic scraper

A generic "first PDF on page" scraper would be shorter but unsafe. Authority pages
often include complaints, appendices, orders, undertakings, notices, submissions,
and press releases alongside the decision document. The long-term solution is a
shared orchestration layer plus small, testable authority adapters.

### Why not fold PDF resolution into scraping

Keep index scraping and PDF resolution separate. Scraping builds the backlog cheaply;
PDF resolution is a slower, authority-specific enrichment step that can be retried,
audited, and run with different overwrite limits. This matches the existing
case-index design and keeps expensive extraction decoupled from flaky publication
pages.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/cases/discovery/pdf_resolvers.py` | New shared resolver contract, registry, result dataclasses, EU/UK/US adapters, candidate ranking helpers |
| `apps/api/scripts/cases/discovery/resolve_case_index_pdf_urls.py` | New shared batch CLI for resolving `pdf_url` across jurisdictions |
| `apps/api/scripts/cases/discovery/resolve_eu_pdf_urls.py` | Replace duplicated logic with a thin wrapper around the shared resolver path |
| `apps/api/scripts/cases/discovery/resolve_uk_pdf_urls.py` | Replace duplicated logic with a thin wrapper around the shared resolver path |
| `apps/api/scripts/cases/extract/ingest_case.py` | Remove local EU-only resolver; use shared resolver registry for `--from-index` fallback |
| `apps/api/app/cases/models/case_index.py` | Optional only if resolver metadata is stored; otherwise no schema change |
| `apps/api/tests/test_pdf_resolvers.py` | Unit tests for EU CELEX derivation, UK ranking/disqualification, US conservative ranking, resolver status semantics |
| `apps/api/tests/test_resolve_case_index_pdf_urls.py` | CLI/YAML tests for dry-run, overwrite, field ordering, skipped existing PDFs, and unresolved-but-nonfatal misses |
| `apps/api/tests/test_ingest_case_from_index_resolution.py` | Tests that `ingest_case.py --from-index` uses explicit `--pdf-url`, existing index `pdf_url`, then shared resolver fallback |
| `docs/operations/ingestion.md` | Update operator commands and explain resolver statuses |
| `ROADMAP.md` | Mark 5.10 complete after implementation and verification |

## Verification

From `apps/api/` with `.venv` active:

```bash
# Unit coverage for shared resolver behavior
.venv/bin/python -m pytest \
  tests/test_pdf_resolvers.py \
  tests/test_resolve_case_index_pdf_urls.py \
  tests/test_ingest_case_from_index_resolution.py \
  -v

# Existing case-index schema still passes
.venv/bin/python scripts/cases/discovery/validate_case_index.py \
  --index-dir ../../data/case_index

# Existing source checks still pass on index records
.venv/bin/python scripts/cases/discovery/check_case_index_sources.py \
  --index-dir ../../data/case_index --no-http

# EU dry-run still resolves through the consolidated path
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction eu --dry-run --limit 5

# UK dry-run still ranks GOV.UK report PDFs through the consolidated path
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction uk --dry-run --limit 5 --all-outcomes

# US dry-run reports resolved/manual-required candidates without writing bad URLs
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction us --dry-run --limit 5

# Compatibility wrappers still work
.venv/bin/python scripts/cases/discovery/resolve_eu_pdf_urls.py --dry-run --limit 2
.venv/bin/python scripts/cases/discovery/resolve_uk_pdf_urls.py --dry-run --limit 2 --all-outcomes
```

Manual checks:

- For at least one EU, one UK, and one US resolved case, open the selected
  `pdf_url` and confirm it is the substantive decision/report/opinion, not a
  complaint, order, undertaking, press release, appendix, or case landing page.
- For at least one US `manual_required` case, confirm the dry-run output lists the
  plausible candidates and explains why no single PDF was selected.
- Run `ingest_case.py --from-index --no-claude` on one index entry without an
  existing `pdf_url` but with a resolver hit, and confirm the generated scaffold
  uses the same URL reported by the shared resolver.

## Rollback

The change is additive if the old per-jurisdiction script names remain as wrappers.
Rollback steps:

1. Revert `ingest_case.py` to its local `--pdf-url` / EU CELEX fallback.
2. Restore the old bodies of `resolve_eu_pdf_urls.py` and `resolve_uk_pdf_urls.py`.
3. Delete `pdf_resolvers.py`, `resolve_case_index_pdf_urls.py`, and their tests.
4. If resolver metadata was added to `CaseIndexEntry`, remove the model field and
   any `pdf_resolution` blocks written during testing.
