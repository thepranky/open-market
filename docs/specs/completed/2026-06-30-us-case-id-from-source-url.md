# 5.22a-fix — US case-index IDs from authority source URLs

## Goal

**Before:** `generate_us_case_id()` in `us_discovery_contract.py` derives IDs from
`case_name` using party-name heuristics (`_PHRASE_SLUGS`, `_DESCRIPTORS`, legal-suffix
stripping). That logic was fitted to the 11 hand-curated entries in `data/case_index/us/`
and does not generalize to arbitrary DOJ/FTC listing titles. 5.22b/c scrapers will always
have a listing `source_url` before they need a `case_id`.

**After:** US `case_id` values are derived deterministically from the authority listing
`source_url`, using authority-specific rules:

- **DOJ** — normalized caption slug from the `/atr/case/{slug}` path segment
- **FTC** — matter number from the `/cases-proceedings/{slug}` path segment

`case_name` remains the human-readable listing title; it is not an input to ID generation.
The 11 seed YAML files are renamed so on-disk `case_id`, filename, and generated IDs all
align. Tests assert URL → ID mappings from fixtures and seed `source_url` values.

**Why it matters:** 5.22b/c should not ship with an alias table that grows per case. URL
slugs are the stable authority identifiers available at scrape time — the same reason the
UK scraper keys off CMA URL slugs rather than display titles.

**Out of scope:**

- DOJ/FTC listing scrapers (`scrape_us_doj_index.py`, `scrape_us_ftc_index.py`) — 5.22b/c
- `UsDojFtcResolver` or other PDF-resolution logic (`pdf_resolvers.py`)
- `CaseIndexEntry` schema changes
- Historical audit artifacts (`data/batch_runs/case_index_pdf_resolution_20260627.yaml`) —
  these record IDs as they existed at resolution time; leave unchanged
- Promoted canonical cases (`data/cases/us/` is empty; no canonical IDs to migrate)
- Web frontend changes (no hardcoded US `case_id` values in `apps/web/`)

## Approach

### API change

Replace:

```python
generate_us_case_id(authority, case_name, year) -> str
```

with:

```python
generate_us_case_id(authority, source_url, year) -> str
```

`to_case_index_seed()` calls the new signature using `record.source_url`. `UsScrapedCase`
already requires `source_url: str`; no dataclass field changes.

Remove `_PHRASE_SLUGS`, `_DESCRIPTORS`, `_LEGAL_SUFFIXES`, `_CAPTION_PREFIXES`,
`_strip_caption_boilerplate`, and `_party_slug` — they exist only for the old
party-name path.

### URL path extraction (shared)

Use `urllib.parse.urlparse(source_url).path` so both relative listing hrefs
(`/atr/case/...`) and absolute `source_url` values (`https://www.justice.gov/atr/case/...`)
work. Take the last non-empty path segment as the raw slug.

### DOJ: caption slug fingerprint

Input example:
`https://www.justice.gov/atr/case/us-and-plaintiff-states-v-jetblue-airways-corporation-and-spirit-airlines-inc`

Algorithm:

1. Extract raw slug (last path segment)
2. Strip caption prefixes, in order: `us-and-plaintiff-states-v-`, `us-et-al-v-`, `us-v-`
3. Strip trailing `-et-al`
4. Replace non-alphanumeric runs with `_`, lowercase, collapse/truncate to max 55 chars
   (trim trailing `_`)
5. Return `us_doj_{slug}_{year}`

**Known limitations (accepted):**

- IDs reflect **legal caption defendants**, not deal shorthand. Example: Penguin Random
  House / Simon & Schuster → `us_doj_bertelsmann_se_co_kgaa_2022` because DOJ sued the
  parent entity.
- `-et-al` captions drop unnamed co-defendants. Example: Sabre / Farelogix →
  `us_doj_sabre_corp_2020` (Farelogix is only in `et al`).
- Long captions truncate at 55 chars. Example: American / JetBlue →
  `us_doj_american_airlines_group_inc_and_jetblue_airways_corpora_2023`.

These are acceptable: `case_name` carries the lawyer-facing label; `case_id` is a stable
discovery key tied to the authority page.

### FTC: matter number

Input examples:

| `source_url` tail | Generated ID |
|---|---|
| `201-0144-illumina-inc-grail-inc-matter` | `us_ftc_201_0144_2023` |
| `2210077-microsoftactivision-blizzard-matter` | `us_ftc_221_0077_2023` |
| `221-0040-meta-platforms-incmark-zuckerbergwithin-unlimited-ftc-v` | `us_ftc_221_0040_2023` |

Algorithm:

1. Extract raw slug (last path segment)
2. Parse matter number with `^(\d{3})-?(\d{4})-` (handles both `201-0144-` and `2210077-`
   concatenated forms)
3. Return `us_ftc_{matter_group1}_{matter_group2}_{year}`
4. **Fallback** (only if matter number does not parse): normalize the full slug
   (hyphens → underscores, truncate) as `us_ftc_{tail}_{year}`. Document in a test that
   this path exists but is not expected for current FTC merger listings.

Matter numbers are authority-native, stable, and avoid parsing mangled party tails
(`microsoftactivision`, lawsuit captions).

### Seed YAML migration

For each file in `data/case_index/us/`:

1. Compute new `case_id` from existing `source_url`, `authority`, and `decision_date` year
2. Update the `case_id` field inside the YAML
3. Rename `{old_case_id}.yaml` → `{new_case_id}.yaml`

All other fields (`case_name`, `parties`, `source_url`, `pdf_url`, etc.) stay unchanged.

| Old `case_id` | New `case_id` |
|---|---|
| `us_doj_aetna_humana_2017` | `us_doj_aetna_inc_and_humana_inc_2017` |
| `us_doj_american_jetblue_alliance_2023` | `us_doj_american_airlines_group_inc_and_jetblue_airways_corpora_2023` |
| `us_doj_anthem_cigna_2017` | `us_doj_anthem_inc_and_cigna_corp_2017` |
| `us_doj_att_timewarner_2018` | `us_doj_att_inc_directv_group_holdings_llc_and_time_warner_inc_2018` |
| `us_doj_jetblue_spirit_2024` | `us_doj_jetblue_airways_corporation_and_spirit_airlines_inc_2024` |
| `us_doj_penguin_simonschuster_2022` | `us_doj_bertelsmann_se_co_kgaa_2022` |
| `us_doj_sabre_farelogix_2020` | `us_doj_sabre_corp_2020` |
| `us_doj_unitedhealth_changehealthcare_2022` | `us_doj_unitedhealth_group_inc_and_change_healthcare_inc_2022` |
| `us_ftc_illumina_grail_2023` | `us_ftc_201_0144_2023` |
| `us_ftc_meta_within_2023` | `us_ftc_221_0040_2023` |
| `us_ftc_microsoft_activision_2023` | `us_ftc_221_0077_2023` |

### Why not party-name slugs?

The 5.22a party-name approach required per-case aliases (`AT&T` → `att`, `Penguin Random
House` → `penguin`) and still failed on edge cases (`& Schuster`, parent-company captions).
Mechanical first-token heuristics would reintroduce the same problem. URL-derived IDs trade
shorter labels for determinism without an alias table.

### Why not one shared rule for DOJ and FTC?

The authorities encode different things in listing URLs: DOJ uses court-caption slugs with
no matter number; FTC uses matter numbers with inconsistently formatted party tails. A
single algorithm would either ignore FTC matter numbers or over-parse DOJ captions.

### DDR

No new DDR. `CaseIndexEntry` schema is unchanged. This is a script-layer naming convention
correction; see ddr-a for the discovery vs canonical layer split.

## Files

| Path | Action | Purpose |
|------|--------|---------|
| `apps/api/scripts/cases/discovery/us_discovery_contract.py` | MODIFY | URL-based `generate_us_case_id`; remove party-name constants; wire `to_case_index_seed` to `source_url` |
| `apps/api/tests/test_us_discovery_contract.py` | MODIFY | Assert URL → ID from fixtures + all 11 seed `source_url` values; update seed-based conversion tests |
| `data/case_index/us/*.yaml` | MODIFY + RENAME | Update `case_id` field and filename for all 11 seed entries (mapping table above) |
| `apps/api/tests/test_indexed_cases_api.py` | MODIFY | Update hardcoded US indexed-case detail test to new `us_ftc_221_0077_2023` (or equivalent) |
| `ROADMAP.md` | MODIFY | Add done row for this fix (blocks 5.22b/c) when implemented |

**Not modified:**

| Path | Reason |
|------|--------|
| `apps/api/scripts/cases/discovery/pdf_resolvers.py` | Resolver keys off `source_url`, not `case_id` |
| `data/batch_runs/case_index_pdf_resolution_20260627.yaml` | Historical audit snapshot |
| `docs/specs/completed/2026-06-30-us-discovery-scraper-contract.md` | Archived; superseded by this spec for ID generation only |
| `apps/api/tests/fixtures/us_doj/listing_sample.html` | Unchanged; tests parse href from fixture text |
| `apps/api/tests/fixtures/us_ftc/listing_sample.html` | Unchanged |

## Verification

```bash
# from apps/api/
.venv/bin/python -m pytest \
  tests/test_us_discovery_contract.py \
  tests/test_indexed_cases_api.py::test_indexed_case_detail_us \
  -v
# Expected: all tests pass; no network access

.venv/bin/python scripts/cases/discovery/validate_case_index.py \
  --index-dir ../../data/case_index
# Expected: 11 US entries valid (plus existing EU/UK entries)

.venv/bin/ruff check scripts/cases/discovery/us_discovery_contract.py
# Expected: exits 0
```

Manual check — every seed file's `case_id` matches generator output:

```bash
.venv/bin/python - <<'PY'
import yaml
from pathlib import Path
from scripts.cases.discovery.us_discovery_contract import generate_us_case_id

root = Path("../../data/case_index/us")
for path in sorted(root.glob("*.yaml")):
    entry = yaml.safe_load(path.read_text())
    year = str(entry["decision_date"])[:4]
    expected = generate_us_case_id(entry["authority"], entry["source_url"], year)
    assert entry["case_id"] == expected, (path.name, entry["case_id"], expected)
    assert path.stem == entry["case_id"], (path.name, entry["case_id"])
print("ok", len(list(root.glob("*.yaml"))), "entries")
PY
# Expected: ok 11 entries
```

## Rollback

Revert `us_discovery_contract.py` and tests to the party-name implementation. Rename the
11 YAML files back to old `case_id` values and restore `case_id` fields inside each file.
Revert the `test_indexed_cases_api.py` assertion. No schema or resolver changes to undo.
