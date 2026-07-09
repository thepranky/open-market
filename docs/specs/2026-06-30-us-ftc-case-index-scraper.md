# 5.22c - FTC case-index scraper

## Goal

**Before:** The shared US discovery contract can turn a normalized
`UsScrapedCase` into a valid CaseIndex record, and 5.22b will add a DOJ scraper.
FTC merger cases still have no repeatable discovery script. The FTC listing page
has a different result shape from DOJ: merger filtering uses the numeric
competition-topic query, result rows include FTC matter numbers and case status,
and the visible listing date is `Last Updated`, not necessarily the
disposition/merits date the case index should store.

**After:** `scrape_us_ftc_index.py` fetches the FTC cases/proceedings listing
with the Merger topic filter, parses only case-result rows, fetches each FTC
case detail page, derives a true decision/disposition date from the detail page,
and converts eligible rows through the existing `UsScrapedCase` ->
`CaseIndexEntry` contract. Rows whose detail page has no true decision date are
skipped with a structured reason rather than written with `Last Updated`.

**Why it matters:** FTC pages often remain updated after the legally meaningful
decision event. Using `Last Updated` as `decision_date` would make US case IDs
and timeline filters drift from the actual FTC order, final opinion, court
decision, or abandonment date. The scraper should produce CaseIndex-ready
records for reviewed backfill instead of delegating date cleanup to 5.22d.

**Out of scope:**

- DOJ scraping or refactoring the DOJ scraper (5.22b)
- Writing a reviewed batch into `data/case_index/us/` (5.22d)
- Resolving or patching `pdf_url` fields (5.22d uses the existing resolver)
- Changing `CaseIndexEntry`, `UsScrapedCase`, or `pdf_resolvers.py`
- Fetching PDFs or reading PDF text to classify outcomes
- Perfect party/outcome classification for every FTC page; ambiguous rows may
  emit conservative `outcome: pending` or be skipped with a reason

## Approach

Create `apps/api/scripts/cases/discovery/scrape_us_ftc_index.py` as the FTC-only
scraper. It owns FTC listing pagination, FTC result parsing, FTC detail-page
date enrichment, and CLI orchestration. It must reuse
`us_discovery_contract.UsScrapedCase` and `to_case_index_dict()` for final
CaseIndex output instead of duplicating CaseIndex construction.

The scraper should expose small offline-testable helpers:

- `parse_ftc_listing_page(html: str) -> list[FtcListingCase]`
- `parse_ftc_case_detail(html: str) -> FtcDecisionFacts`
- `to_us_scraped_case(listing: FtcListingCase, facts: FtcDecisionFacts) -> UsScrapedCase`

`FtcListingCase` should keep facts available on the listing page: title, source
URL, listing `Last Updated`, matter/file numbers, docket numbers, case status,
and type of action. The parser must select only `article.node--type-case`
results and ignore public statements, commissioner statements, PDFs, and other
legal-library result types that can appear on the same filtered page.

Use the numeric FTC merger-topic query that returns actual result rows:

```text
https://www.ftc.gov/legal-library/browse/cases-proceedings?field_competition_topics=708&items_per_page=20&page=N
```

Do not rely on `field_competition_topics=Merger`; that query can preserve the
filter UI but return no result rows in raw HTML. Pagination follows the FTC
pager links with the same query parameters.

`FtcDecisionFacts` should identify a true decision/disposition date from the FTC
detail page. The detail parser should inspect body text, dated document rows,
and case-status sections for final events such as final Commission opinion,
final order, consent order finalization, court decision/order, dismissal after
abandonment, or transaction abandonment. It must not use listing `Last Updated`
as the CaseIndex `decision_date`. If a detail page has no such event, skip the
row as `missing_decision_date`; pending merger matters without final events are
expected skips.

Outcome mapping should be conservative and based only on visible detail-page
text or document labels:

- final consent/order/divestiture language -> `cleared_with_conditions`
- final opinion/order blocking or requiring divestiture/undoing a consummated
  acquisition -> `blocked` or `abandoned` only when the page clearly says so
- pending or unclear final result -> `outcome_guess=None`, which the shared
  contract emits as `outcome: pending`

Matter-number handling should preserve the 5.22a-fix ID contract. The scraper
passes the FTC detail `source_url` and the true decision-date year into
`generate_us_case_id()` indirectly via `to_case_index_dict()`. If the listing
has no matter number but the source URL is valid, do not invent an ID; let the
existing FTC URL fallback in `generate_us_case_id()` produce a deterministic
case ID and report a `missing_matter_number` warning counter.

Party parsing should clean common FTC title suffixes (`In the Matter of`,
`Matter`, `FTC v.`, `USA v.`) and split on `/`, ` and `, or comma patterns only
when that produces clear merger parties. If parties cannot be parsed
confidently, keep a single `third_party` party with the cleaned title rather
than dropping an otherwise valid dated case.

The CLI should mirror existing discovery scripts:

- `--dry-run` prints records/skips without writing files.
- `--limit N` stops after N successfully built records, not after N fetched
  listing rows.
- `--force` permits overwriting files when `--output-dir` points at a real
  index directory.
- `--output-dir` defaults to a temporary or explicit path for tests; writing to
  `../../data/case_index/us` is allowed only when the caller passes it
  explicitly.
- `--delay`, `--timeout`, and `--start-page` support polite/resumable network
  runs.

Network code should use `httpx` with a Meridian user agent, follow redirects,
and report summary counters for `built`, `written`, `dry_run`,
`skipped_existing`, `missing_decision_date`, `missing_source_url`,
`missing_matter_number`, `invalid_case_index`, and `fetch_error`. In dry-run
mode, at least one built FTC fixture record should print its generated
`case_id`, true `decision_date`, outcome, matter number when present, and
`source_url`.

No DDR is needed. This is an authority-specific scraper behind the existing
discovery-layer contract documented by DDR-A (`CaseIndexEntry`) and the 5.22a
US discovery contract.

## Files

| Path | Action | Purpose |
|------|--------|---------|
| `apps/api/scripts/cases/discovery/scrape_us_ftc_index.py` | CREATE | FTC listing/detail scraper, true-date enrichment, CLI, and YAML writing through `to_case_index_dict()` |
| `apps/api/tests/test_scrape_us_ftc_index.py` | CREATE | Offline parser/conversion/CLI tests for FTC listing fixture, detail fixture, skip reasons, matter numbers, and CaseIndex validation |
| `apps/api/tests/fixtures/us_ftc/listing_sample.html` | MODIFY | Refresh to representative current FTC merger-filter listing HTML with one case result and one non-case result |
| `apps/api/tests/fixtures/us_ftc/detail_sample.html` | CREATE | FTC detail-page fixture containing both `Last Updated` and a separate true final decision/disposition date |
| `ROADMAP.md` | MODIFY | Link 5.22c to this spec when implemented |

## Verification

```bash
# from apps/api/
.venv/bin/python -m pytest \
  tests/test_scrape_us_ftc_index.py \
  tests/test_us_discovery_contract.py \
  tests/test_case_index_builder.py \
  -v
# Expected: all tests pass; fixture tests perform no live network calls

.venv/bin/python scripts/cases/discovery/scrape_us_ftc_index.py \
  --dry-run --limit 1 --delay 0 --timeout 20
# Expected: exits 0 and prints one built FTC CaseIndex-shaped record using a
# true detail-page decision date, plus summary counters

.venv/bin/python scripts/cases/discovery/validate_case_index.py \
  --index-dir ../../data/case_index
# Expected: exits 0; existing case-index YAML remains valid

.venv/bin/ruff check \
  scripts/cases/discovery/scrape_us_ftc_index.py \
  tests/test_scrape_us_ftc_index.py
# Expected: exits 0 with no lint errors
```

Manual check: run the dry-run command and confirm the printed record's
`decision_date` comes from a final order/opinion/court/abandonment event on the
FTC detail page, not from listing `Last Updated`. Confirm the dry-run output does
not include `pdf_url`, `pdf_language`, or `extraction_status` fields.

## Rollback

Delete `scrape_us_ftc_index.py`, `test_scrape_us_ftc_index.py`, and the FTC
detail fixture. Revert the FTC listing fixture refresh and the 5.22c roadmap
link. No data migration or schema rollback is required because this spec does
not write reviewed US case-index YAML.
