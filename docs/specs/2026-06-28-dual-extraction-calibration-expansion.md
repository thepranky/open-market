# Spec: Dual-extraction calibration for full depth and per jurisdiction (ROADMAP 5.18)

## Goal

The dual-extraction workflow (5.9) skips human review on fields where two independent
model extractions agree, trusting that agreement predicts correctness (agreement precision
≥ 0.98 on gold). That bar was verified only for EU market-definition golds. Before the
theories, remedies, UK, and US lanes scale, each needs its own calibration run confirming
the same precision holds there.

Today, running `calibrate_dual_extraction.py` against a theories or remedies benchmark
config would produce meaningless results: the reconciliation machinery does not handle
`commitments` at all (theories_of_harm is handled; commitments are not), and no gold
files exist for theories/remedies focuses or UK/US jurisdictions.

After this spec: the comparison and calibration scripts handle commitments; reviewed
market-definition and theories golds exist for the UK/US and EU/UK/US slices covered
by the current canonical case set; benchmark configs reference those available golds;
and the market-definition / theories calibration lanes can be scored before those
lanes are trusted at scale. Remedies calibration is wired as a scaffold, but verified
remedies golds remain deferred until candidate cases with structured commitments are
extracted and human reviewed.

## Out of scope

- Running theories/remedies extraction at scale over the backlog (5.19–5.21)
- Changing extraction prompts or pipeline profiles
- Grounding gates (5.17)
- Automated promotion without human sign-off
- The `remedies: list[str]` backward-compat field on `CaseRecord` — only the structured
  `commitments: list[Commitment]` field is calibrated here
- The EU market_definition slice — already calibrated; benchmark config may gain new
  cases but no code changes affect that slice
- Creating reviewed remedies golds when no current canonical case has structured
  `commitments`; this spec wires the commitments path so that follow-up gold creation
  can be scored once remedy-focused extractions exist

## Approach

### 1. Extend reconciliation to handle commitments (`extract_case_from_source.py`)

`_reconcile` reconciles product markets, geographic markets, and theories_of_harm. When
`focus=remedies`, all three passes are skipped (lines 3591–3613), so the function returns
no findings and `align_drafts` produces empty alignment — no comparison is possible.

Add a `commitments` reconciliation pass inside `_reconcile`:

```
if focus == "remedies":
    _match_list(
        existing_record.get("commitments") or [],
        draft_record.get("commitments") or [],
        id_field="commitment_id",
        item_label="commitment",
        name_field="title",
        market_type="commitment",
    )
```

`_match_list` currently hard-codes `ex.get("name", "")` and `dr.get("name", "")` for
the similarity target. Add a `name_field: str = "name"` parameter so the commitments
pass can use `"title"` instead, preserving current behaviour for all existing call sites.

Also update `_draft_meta` inside `_reconcile` to fall back to `commitment_id`:

```python
mid = str(dr.get("market_id") or dr.get("theory_id") or dr.get("commitment_id") or "")
```

**Files to change:**
- `apps/api/scripts/cases/extract/extract_case_from_source.py` — add `name_field`
  param to `_match_list`; add commitments pass when `focus=remedies`; update
  `_draft_meta`

### 2. Extend comparison to handle commitments (`compare_extractions.py`)

Two additions:

**a. Add `commitments` to `_MARKET_LISTS` and `_TYPE_TO_LIST`:**

```python
_MARKET_LISTS = (
    ("product_markets_considered", "product_markets"),
    ("geographic_markets_considered", "geographic_markets"),
    ("theories_of_harm", "theories"),
    ("commitments", "commitments"),
)

_TYPE_TO_LIST = {
    ...
    "commitment": ("commitments", "commitments"),
}
```

**b. Add `commitment_type` to `_MARKET_SCALAR_FIELDS`:**

```python
_MARKET_SCALAR_FIELDS = ("definition_status", "market_importance", "commitment_type")
```

This is safe for existing market/theory entries because `commitment_type` is absent on
those dicts → empty string → the `if not va and not vb: continue` guard skips the field.

**c. Generalise `_index_markets_by_name` to use `title` for commitments:**

```python
name = m.get("name", "") or m.get("title", "")
```

This lets commitment dicts (which have no `name` key) be keyed by `title`. The fallback
order (`name` first) keeps existing behaviour for markets and theories.

**d. Update `_list_for_type` fallback:**

The fallback currently returns `_TYPE_TO_LIST["theory"]` for unknown types. No change
needed — `"commitment"` is now an explicit key.

**Files to change:**
- `apps/api/scripts/cases/extract/compare_extractions.py` — four targeted edits as
  described above

### 3. Extend calibration scoring for commitments (`calibrate_dual_extraction.py`)

**a. Update `_gold_field_table`** to key commitments by `title`:

```python
name = m.get("name", "") or m.get("title", "")
```

**b. Add `commitment_type` to `_GOLD_FIELD_ALIAS`:**

```python
_GOLD_FIELD_ALIAS = {
    "definition_status": "expected_definition_status",
    "commitment_type": "expected_commitment_type",
}
```

Gold YAML files for the remedies focus store the human-verified commitment type under
`expected_commitment_type` on each commitment entry (same `expected_*` convention as
existing market golds).

**c. Update `_draft_field_table`** — same `name or title` fallback in the draft index
lookup (mirrors the `_index_markets_by_name` change in 2c).

**Files to change:**
- `apps/api/scripts/cases/extract/calibrate_dual_extraction.py` — three targeted edits

### 4. Gold sets

A gold YAML is a human-verified extraction output. Process for each case:
1. Run `ingest_case.py --focus <focus>` (or the e2e orchestrator) to produce a draft.
2. Open the source PDF and verify each extracted entry against the relevant passage.
3. Save the corrected YAML to `data/evals/gold/<case_id>.<focus>.gold.yaml`.
4. Mark `_gold_metadata.partial: true` if only a representative subset was reviewed;
   mark `reviewed: true` on each verified entry so the calibration script scores only
   those fields.

For remedies golds, each commitment entry also gets `expected_commitment_type: <verified
value>` alongside the extracted `commitment_type`.

**Slices and case targets:**

| Slice | Target count | Candidate cases |
|-------|-------------|-----------------|
| EU theories | 2–3 | eu_apple_shazam_2018 + 2 EU cases with non-empty `theories_of_harm` in the canonical record that have PDF source text cached or a `pdf_url` |
| EU remedies | deferred | 2–3 EU Phase-I-with-conditions or Phase-II-with-commitments decisions; confirmed by running a remedies-focus extraction and checking `commitments` is non-empty |
| UK market_definition | 2 | uk_viasat_inmarsat_2023, meta_giphy_2022 (only 2 canonical UK cases exist) |
| UK theories | 2 | uk_viasat_inmarsat_2023, meta_giphy_2022 |
| UK remedies | deferred | UK cases where the CMA imposed behavioural or structural commitments; identify from the 2 canonical cases or promote 1 additional UK case with known remedies before creating the gold |
| US market_definition | 3 | jetblue_spirit_2024, microsoft_activision_2023, us_tapestry_capri_2024 |
| US theories | 3 | same 3 US cases |
| US remedies | deferred | microsoft_activision_2023 (DOJ sought divestiture) + 1–2 additional US cases with consent decree or divestiture terms |

Gold files live in `data/evals/gold/` and follow the naming convention already in use:
`<case_id>.<focus>.gold.yaml` (full) or `<case_id>.<focus>.partial.gold.yaml`
(if `_gold_metadata.partial: true`).

### 5. Benchmark configs

**Update `data/evals/benchmark.market_definition.ci.yaml`:**
Add the UK/US market_definition gold cases (with their `gold_yaml`, `cache_dir` entries).
The `focus: market_definition` field at the top remains unchanged.

**Create `data/evals/benchmark.theories.ci.yaml`:**

```yaml
focus: theories
output_dir: data/evals/results

benchmarks:
  # EU theories cases
  - case_id: <eu_case_1>
    gold_yaml: data/evals/gold/<eu_case_1>.theories.gold.yaml
    cache_dir: <path to cached source text or fixture>
  # ... additional EU cases
  # UK cases
  - case_id: uk_viasat_inmarsat_2023
    gold_yaml: data/evals/gold/uk_viasat_inmarsat_2023.theories.gold.yaml
    cache_dir: data/evals/fixtures/theories/uk_viasat_inmarsat_2023
  - case_id: meta_giphy_2022
    gold_yaml: data/evals/gold/meta_giphy_2022.theories.gold.yaml
    cache_dir: data/evals/fixtures/theories/meta_giphy_2022
  # US cases
  - case_id: jetblue_spirit_2024
    ...
```

**Create `data/evals/benchmark.remedies.ci.yaml`:**
Create the `focus: remedies` config as explicit scaffolding with `benchmarks: []` and
instructions for adding reviewed remedies golds. It should not be part of the passing
calibration gate until at least one verified remedies gold exists.

### 6. Calibration runs

Run the populated market-definition and theories configs against the gold fixtures.
Each populated config must exit 0:

```bash
cd apps/api
.venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py \
  --golds --config ../../data/evals/benchmark.market_definition.ci.yaml

.venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py \
  --golds --config ../../data/evals/benchmark.theories.ci.yaml
```

If any slice shows agreement precision < 0.98, investigate before trusting that focus
or jurisdiction at scale. Findings go into the PR description, not this spec. Do not
treat the remedies scaffold as a passing gate until remedies golds are populated.

## Verification

```bash
cd apps/api

# Code correctness
.venv/bin/python -m pytest tests/ -v -k "calibrat or compare or reconcil"
.venv/bin/ruff check scripts/cases/extract/extract_case_from_source.py \
  scripts/cases/extract/compare_extractions.py \
  scripts/cases/extract/calibrate_dual_extraction.py

# Scoring logic: remedies-focus alignment produces non-empty output on a
# case with commitments (confirms _reconcile now handles commitments)
.venv/bin/python scripts/cases/extract/compare_extractions.py \
  --case-id <any case with commitments> \
  --draft-a <path to draft_a> \
  --draft-b <path to draft_b> \
  --focus remedies
# Expected: "Agreed fields: N" and/or "Conflicts: M" where N+M > 0

# Calibration gate — populated configs must exit 0
.venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py \
  --golds --reuse-drafts --config ../../data/evals/benchmark.market_definition.ci.yaml

.venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py \
  --golds --reuse-drafts --config ../../data/evals/benchmark.theories.ci.yaml
```

Expected output for each populated config: `PASS: agreement precision X.XXX >= threshold 0.980`.
The remedies config is expected to remain a non-passing scaffold until remedies golds
are added.

Note: `--reuse-drafts` scores drafts already on disk (no model calls). During
implementation, remove the flag for the first run of each focus to actually extract and
produce the draft pairs; then use `--reuse-drafts` for re-scoring and verification.
