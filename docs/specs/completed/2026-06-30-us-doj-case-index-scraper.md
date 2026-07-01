# 5.22b - DOJ case-index scraper

## Goal

**Before:** The US discovery contract exists (`UsScrapedCase`,
`generate_us_case_id()`, and `to_case_index_dict()`), and the
`UsDojFtcResolver` can resolve PDFs from a known DOJ or FTC case page. There is
still no DOJ scraper that can repeatedly discover DOJ civil merger case pages,
enrich them into valid `CaseIndexEntry` records, and report which rows are not
ready for indexed-case output.

**After:** `scrape_us_doj_index.py` fetches DOJ antitrust case listing pages,
filters to DOJ `Civil Merger` rows, fetches each DOJ case detail page, derives a
true disposition/merits `decision_date`, and converts eligible rows through the
existing `UsScrapedCase` -> `CaseIndexEntry` contract. Rows without a true
decision date are skipped with a machine-readable reason rather than written
with the DOJ listing `Case Open Date`.

**Why it matters:** Existing US seed data uses outcome/disposition dates such as
court opinions, findings, final judgments, or consent-decree dates. The DOJ
listing `Case Open Date` is a filing/opening date and must not become
`decision_date` in the case index. If the scraper emitted open dates, 5.22d
would need data cleanup before any reviewed backfill could be trusted.

**Out of scope:**

- FTC scraping (5.22c)
- Writing a reviewed batch into `data/case_index/us/` (5.22d)
- Resolving or patching `pdf_url` fields (5.22d uses the existing resolver)
- Changing `CaseIndexEntry`, `UsScrapedCase`, or `pdf_resolvers.py`
- Fetching PDFs or reading PDF text to classify outcomes
- Perfect party/outcome classification for every DOJ page; ambiguous rows may
  emit conservative `outcome: pending` or be skipped with a reason

## Approach

Create `apps/api/scripts/cases/discovery/scrape_us_doj_index.py` as the DOJ-only
scraper. It owns DOJ HTML parsing, DOJ listing pagination, DOJ detail-page
date enrichment, and CLI orchestration. It must reuse
`us_discovery_contract.UsScrapedCase` and `to_case_index_dict()` for the final
CaseIndex output instead of rebuilding CaseIndex dictionaries locally.

The scraper should expose small offline-testable helpers:

- `parse_doj_listing_page(html: str) -> list[DojListingCase]`
- `parse_doj_case_detail(html: str) -> DojDecisionFacts`
- `to_us_scraped_case(listing: DojListingCase, facts: DojDecisionFacts) -> UsScrapedCase`

`DojListingCase` should keep facts available on the listing page: case title,
case page URL, listing open date, case type, industry labels, and any listing
document labels. Listing rows are eligible only when `case_type == "Civil
Merger"`. The parser must ignore `Civil Non Merger`, `Criminal`, missing-link,
and malformed rows.

`DojDecisionFacts` should identify a true decision/disposition date from the DOJ
case detail page. The detail parser should inspect dated case-document links and
body entries, prefer merits/disposition labels such as `Findings of Fact`,
`Conclusions of Law`, `Opinion`, `Memorandum Opinion`, `Order`, `Judgment`, and
`Final Judgment`, and reject procedural/source-opening labels such as
`Complaint`, `Proposed Final Judgment`, `Stipulation`, `Brief`, `Exhibit`,
`Notice`, and `Schedule`. A selected date must be ISO `YYYY-MM-DD`. If no such
date exists, the row is skipped as `missing_decision_date`. The listing `Case
Open Date` may be retained in skip/report output but must never be passed to
`UsScrapedCase.decision_date`.

Outcome mapping should be conservative. Final-judgment or consent-decree
dispositions may map to `cleared_with_conditions` when the detail page clearly
supports that. Clear court blocking/prohibition dispositions may map to
`blocked`. If the detail page has a true decision date but the result cannot be
read confidently without fetching a PDF, set `outcome_guess=None` so the shared
contract emits `outcome: pending`. This keeps discovery repeatable without
inventing lawyer-facing outcomes.

Sector mapping should use DOJ industry labels when present and a small local map
to Meridian sector slugs; unknown labels map to `other`. Party parsing should
clean DOJ captions (`U.S. v.`, `U.S. et al. v.`, `U.S. and Plaintiff States v.`,
trailing `et al.`) and split the defendant caption on `and` only when that
produces clear merger parties. If parties cannot be parsed confidently, keep a
single `third_party` party with the cleaned title rather than dropping an
otherwise valid dated case.

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
and request unfiltered DOJ listing pages with `?page=N`. The DOJ facet URL for
`Civil Merger` is not a required dependency because it can reject direct fetches;
filter after parsing the unfiltered listing page. Stop pagination when a page has
no result rows or when the limit is reached.

The script should report summary counters for `built`, `written`, `dry_run`,
`skipped_existing`, `skipped_non_merger`, `missing_decision_date`,
`missing_source_url`, `invalid_case_index`, and `fetch_error`. In dry-run mode,
at least one built DOJ fixture record should be printed with its generated
`case_id`, true `decision_date`, outcome, and `source_url`.

No DDR is needed. This is an authority-specific scraper behind the existing
discovery-layer contract documented by DDR-A (`CaseIndexEntry`) and the 5.22a
US discovery contract.

## Files

| Path | Action | Purpose |
|------|--------|---------|
| `apps/api/scripts/cases/discovery/scrape_us_doj_index.py` | CREATE | DOJ listing/detail scraper, true-date enrichment, CLI, and YAML writing through `to_case_index_dict()` |
| `apps/api/tests/test_scrape_us_doj_index.py` | CREATE | Offline parser/conversion/CLI tests for DOJ listing fixture, detail fixture, skip reasons, and CaseIndex validation |
| `apps/api/tests/fixtures/us_doj/listing_sample.html` | MODIFY | Refresh to representative current DOJ listing HTML with at least one `Civil Merger` row and one non-merger row |
| `apps/api/tests/fixtures/us_doj/detail_sample.html` | CREATE | DOJ detail-page fixture containing a true merits/disposition document date and the listing open date |
| `ROADMAP.md` | MODIFY | Link 5.22b to this spec when implemented |

## Verification

```bash
# from apps/api/
.venv/bin/python -m pytest \
  tests/test_scrape_us_doj_index.py \
  tests/test_us_discovery_contract.py \
  tests/test_case_index_builder.py \
  -v
# Expected: all tests pass; fixture tests perform no live network calls

.venv/bin/python scripts/cases/discovery/scrape_us_doj_index.py \
  --dry-run --limit 1 --delay 0 --timeout 20
# Expected: exits 0 and prints one built DOJ CaseIndex-shaped record using a
# true detail-page decision date, plus summary counters

.venv/bin/python scripts/cases/discovery/validate_case_index.py \
  --index-dir ../../data/case_index
# Expected: exits 0; existing case-index YAML remains valid

.venv/bin/ruff check \
  scripts/cases/discovery/scrape_us_doj_index.py \
  tests/test_scrape_us_doj_index.py
# Expected: exits 0 with no lint errors
```

Manual check: run the dry-run command and confirm the printed record's
`decision_date` differs from the DOJ listing `Case Open Date` when the detail
fixture/live page exposes a later merits/disposition document date. Confirm the
dry-run output does not include `pdf_url`, `pdf_language`, or
`extraction_status` fields.

## Rollback

Delete `scrape_us_doj_index.py`, `test_scrape_us_doj_index.py`, and the DOJ
detail fixture. Revert the DOJ listing fixture refresh and the 5.22b roadmap
link. No data migration or schema rollback is required because this spec does
not write reviewed US case-index YAML.
