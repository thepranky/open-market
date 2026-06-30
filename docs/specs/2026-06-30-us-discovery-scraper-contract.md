# 5.22a - US discovery scraper contract and shared index builder

## Goal

**Before:** No US scraper scripts exist. The `UsDojFtcResolver` in `pdf_resolvers.py` can
resolve a *known* case page to a merits PDF, but there is no typed intermediate shape for what
a US scraper produces. The EU scraper already has a local intermediate dataclass
(`ScrapedCase`) and a conversion function that manually builds a CaseIndex-shaped dict, but
the naming is generic and the conversion pattern is not reusable. If 5.22b/c add DOJ and FTC
scrapers directly, EU and US will drift into parallel conversion code.

**After:** Discovery scripts have two explicit layers:

1. Jurisdiction-specific scraped records: `EuScrapedCase` for EUR-Lex/Cellar facts and
   `UsScrapedCase` for DOJ/FTC listing facts.
2. A shared `case_index_builder.py` helper that turns a normalized `CaseIndexSeed` into a
   validated `CaseIndexEntry`-compatible dict for YAML writing.

`scrape_eu_index.py` is lightly refactored to use the shared builder without changing its
scraping behavior. `us_discovery_contract.py` defines `UsScrapedCase`, US case-ID generation,
and the US conversion into `CaseIndexSeed` / CaseIndex dict. Canned HTML excerpts for DOJ and
FTC listing pages are stored as fixtures for use in 5.22b/c tests.

**Why it matters:** DOJ and FTC listing pages have different HTML structures, requiring
separate parsing logic, and EU uses still another source shape. The raw scraper dataclasses
should stay jurisdiction-specific, but the final CaseIndex normalization should be shared.
That keeps 5.22b and 5.22c independent while converging on the same `CaseIndexEntry`
validation path and the same resolver handoff behavior.

**Out of scope:**
- Actual scraping / network calls (5.22b/c)
- Writing to `data/case_index/us/` (5.22b/c/d)
- PDF resolution (the `UsDojFtcResolver` already exists; 5.22d wires it to batch output)
- DOJ or FTC HTML parsing logic (5.22b/c own that)
- Changing `CaseIndexEntry` schema or existing `data/case_index/**` YAML files

## Approach

### Shared `CaseIndexSeed` builder

Create `apps/api/scripts/cases/discovery/case_index_builder.py` with a small normalized seed
type and builder:

```python
PartyRoleValue = Literal["acquirer", "target", "merged_entity", "third_party"]

@dataclass(frozen=True)
class CaseIndexParty:
    name: str
    role: PartyRoleValue

@dataclass(frozen=True)
class CaseIndexSeed:
    case_id: str
    case_name: str
    jurisdiction: Literal["EU", "UK", "US"]
    authority: str
    decision_date: str
    sector: str
    outcome: str
    source_url: str | None = None
    ai_summary: str | None = None
    parties: tuple[CaseIndexParty, ...] = ()

def build_case_index_dict(seed: CaseIndexSeed) -> dict: ...
```

`build_case_index_dict()` constructs the final dict, validates it through
`CaseIndexEntry.model_validate(...)`, and returns a YAML-safe dict. It owns only the shared
CaseIndex boilerplate:

- `case_type: "merger"`
- `ai_summary` placeholder, matching existing generated index YAML
- normalized party dicts
- `concept_refs: []` default
- Pydantic validation for jurisdiction, date, outcome, parties, and schema drift

It must not emit workflow fields that belong to later stages: `pdf_url`, `pdf_language`, or
`extraction_status`. In particular, do **not** write `extraction_status: null`; the classifier
uses key presence to distinguish unclassified entries from classified ones.

### EU alignment

Refactor `scrape_eu_index.py` just enough to match the new pattern:

- Rename `ScrapedCase` to `EuScrapedCase`.
- Keep EU-specific raw fields (`case_number`, `decision_celex`, `nace_codes`,
  `notif_cellar_id`, etc.) on `EuScrapedCase`; do not force them into a shared US/EU shape.
- Replace the manual CaseIndex dict construction with `to_case_index_seed(sc, case_id)` plus
  `build_case_index_dict(seed)`.
- Keep EU-specific case-ID logic in the EU scraper. The shared builder receives a completed
  `case_id`; it does not decide jurisdiction-specific naming.
- Preserve the existing no-network behavior of any new tests by constructing `EuScrapedCase`
  directly.

This should be a mechanical refactor only. It must not change SPARQL queries, Cellar fetch
logic, deduplication, rate limiting, CLI flags, or existing YAML data.

### `UsScrapedCase` dataclass

Create a new frozen dataclass in `us_discovery_contract.py`. Fields are the facts a US listing
page can reliably supply before PDF resolution:

```python
authority: Literal["DOJ", "FTC"]
case_name: str
parties: tuple[CaseIndexParty, ...]
source_url: str
decision_date: str | None          # ISO date (YYYY-MM-DD) or None when absent
outcome_guess: str | None          # mapped from listing metadata, else pending
sector: str                        # coarse sector slug; "other" when not determinable
```

`decision_date` remains optional on the scraped record because some authority listing pages
omit dates. `to_case_index_seed()` raises `ValueError` when it is missing, and the later DOJ
/ FTC scrapers should skip such entries, matching the UK scraper's `year is None` guard.

### US helpers

`us_discovery_contract.py` owns only US-specific normalization:

- `generate_us_case_id(authority, case_name, year) -> str`
  - produces `us_doj_..._{year}` or `us_ftc_..._{year}` slugs
  - lowercases, replaces non-alphanumeric runs with underscores, collapses runs, trims
  - follows existing hand-curated IDs such as `us_doj_att_timewarner_2018` and
    `us_ftc_illumina_grail_2023`
- `to_case_index_seed(record: UsScrapedCase) -> CaseIndexSeed`
  - sets `jurisdiction: "US"`
  - sets `authority` to `"DOJ"` or `"FTC"`
  - maps `outcome` to `record.outcome_guess or "pending"`
  - passes through parties, source URL, sector, and date
- `to_case_index_dict(record: UsScrapedCase) -> dict`
  - thin convenience wrapper around `build_case_index_dict(to_case_index_seed(record))`

Do not add a `Scraper` protocol in this spec. A structural protocol is only useful once a
shared runner or shared 5.22b/c test harness consumes it; otherwise it is nominal alignment
without enforcement.

### Resolver handoff test

The handoff test verifies: `to_case_index_dict` output loads into `CaseIndexEntry` without
validation errors, the loaded entry satisfies `UsDojFtcResolver.can_handle()`, and the
result is `True`. This guarantees that 5.22b/c output can flow into the existing
`resolve_case_index_pdf_urls` batch without schema changes.

### HTML fixtures

Two static HTML files - `tests/fixtures/us_doj/listing_sample.html` and
`tests/fixtures/us_ftc/listing_sample.html` - containing representative excerpts from each
authority's listing page, hand-extracted once during implementation. They are inert data
files; no parsing logic ships in 5.22a. 5.22b and 5.22c tests will load these files and
pass their text to scraper functions.

### Why not extend `pdf_resolvers.py`?

`pdf_resolvers.py` owns *resolver* knowledge (extracting and ranking PDFs from a known
case page). Discovery scraper knowledge - listing structure, outcome vocabulary, case-ID
generation, and CaseIndex seed construction - is a different concern. Mixing them would
conflate two independent decision boundaries. A shared builder in discovery keeps resolver
adapters focused on PDF selection.

### DDR

No DDR needed. `CaseIndexEntry` schema is unchanged. The new builder and dataclass names are
script-layer utilities; they do not affect API module boundaries or any existing data
contract. DDR-a already documents the `CaseIndexEntry`/discovery-layer relationship.

## Files

| Path | Action | Purpose |
|------|--------|---------|
| `apps/api/scripts/cases/discovery/case_index_builder.py` | CREATE | Shared `CaseIndexSeed`, `CaseIndexParty`, and `build_case_index_dict()` validation helper |
| `apps/api/scripts/cases/discovery/scrape_eu_index.py` | MODIFY | Rename `ScrapedCase` to `EuScrapedCase`; convert via `CaseIndexSeed` and shared builder |
| `apps/api/scripts/cases/discovery/us_discovery_contract.py` | CREATE | `UsScrapedCase`, `generate_us_case_id`, `to_case_index_seed`, `to_case_index_dict` |
| `apps/api/tests/test_case_index_builder.py` | CREATE | Offline shared-builder tests, including no `pdf_url` / `pdf_language` / `extraction_status` null output |
| `apps/api/tests/test_scrape_eu_index_contract.py` | CREATE | Offline EU conversion test using `EuScrapedCase` and the shared builder |
| `apps/api/tests/test_us_discovery_contract.py` | CREATE | Offline US contract tests and resolver handoff |
| `apps/api/tests/fixtures/us_doj/listing_sample.html` | CREATE | Canned DOJ listing HTML for 5.22b tests |
| `apps/api/tests/fixtures/us_ftc/listing_sample.html` | CREATE | Canned FTC listing HTML for 5.22c tests |

## Verification

```bash
# from apps/api/
.venv/bin/python -m pytest \
  tests/test_case_index_builder.py \
  tests/test_scrape_eu_index_contract.py \
  tests/test_us_discovery_contract.py \
  -v
# Expected: all tests pass; no network access or live authority pages required

# Existing resolver tests must stay green
.venv/bin/python -m pytest tests/test_pdf_resolvers.py -v
# Expected: exits 0

# Ruff must not flag the touched discovery modules
.venv/bin/ruff check \
  scripts/cases/discovery/case_index_builder.py \
  scripts/cases/discovery/scrape_eu_index.py \
  scripts/cases/discovery/us_discovery_contract.py
# Expected: no output (exits 0)
```

Manual check: confirm the shared builder and US/EU contract imports are side-effect free:

```bash
.venv/bin/python -c "from scripts.cases.discovery.case_index_builder import CaseIndexSeed, build_case_index_dict; from scripts.cases.discovery.scrape_eu_index import EuScrapedCase; from scripts.cases.discovery.us_discovery_contract import UsScrapedCase, to_case_index_dict; print('ok')"
```

## Rollback

Delete `apps/api/scripts/cases/discovery/case_index_builder.py`,
`apps/api/scripts/cases/discovery/us_discovery_contract.py`,
`apps/api/tests/test_case_index_builder.py`, `apps/api/tests/test_scrape_eu_index_contract.py`,
`apps/api/tests/test_us_discovery_contract.py`, and the two fixture HTML files. Revert the
`scrape_eu_index.py` rename/refactor from `EuScrapedCase` / shared builder back to its local
dict construction. No data files, YAML entries, or Pydantic models were changed.
