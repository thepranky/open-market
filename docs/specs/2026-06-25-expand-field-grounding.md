# Spec: Expand passage grounding to non-threshold fields

## Goal

Extend the jurisdiction verification pipeline so that source passages can
also back non-threshold fields — review periods, filing deadlines, fees,
gun-jumping fines — using the same `quote_in_text` / `value_in_text` machinery
already used for `threshold_tests` conditions.

Out of scope:
- Populating `supports_fields` across the 47 existing YAML files (separate data work).
- Array item paths (`minority_thresholds.rules[*]` — each rule already carries its
  own `source` and `source_url`).
- New source-fetching or live re-grounding; all existing fetching machinery is reused.
- Interpretation-level cross-checking (e.g. whether `regime.mandatory: true` is the
  correct classification) — that is handled by Tier 4 re-extraction
  (`verify_jurisdiction_reextract.py`), which is a separate gate already specified in
  `docs/operations/jurisdiction-verification.md`.

## Approach

Add `supports_fields: list[str] = []` to `SourcePassage` (alongside the existing
`supports_conditions`). Field paths are dot-notation references into
`JurisdictionRule`, e.g. `review_periods.phase_1.days` or
`gun_jumping.max_fine_pct_turnover` or `regime.mandatory`.

A small resolver (`resolve_field_value`) walks the Pydantic model tree with
`getattr`, returning the raw field value. The verification logic then branches:

- **Numeric fields** (int/float, e.g. `review_periods.phase_1.days: 25`,
  `gun_jumping.max_fine_pct_turnover: 10`): `value_in_text` checks the value
  appears in the quoted text or full fetched page. Mismatch raises `numeric_mismatch`.
- **Qualitative fields** (bool, str, enum, e.g. `regime.mandatory: true`,
  `scope.substantive_test: "siec"`): passage-existence credit only. The quoted
  text is the human-readable evidence that supports the field value; the pipeline
  confirms the quote is still genuine (not moved or removed from the official source)
  but does not auto-classify the value. A future human or Tier 4 re-extraction agent
  checks the interpretation.

This distinction means regime flags, scope definitions, and substantive test
classifications all get source-backed evidence in the YAML, verified for
authenticity by the pipeline — without the circular risk of an LLM
auto-verifying another LLM's interpretation.

A new `fields_grounded` gate (true when all resolved numeric fields match) is
tracked in `PassageReport` and surfaced in `JurisdictionVerification`. The
existing `numbers_confirmed` gate covers threshold conditions only; `fields_grounded`
is parallel and additive. Both are needed for a jurisdiction to reach the
`numbers_confirmed` tier in the SourceVerificationTier enum (which will be
renamed `numbers_and_fields_confirmed` here, or introduced as a distinct value —
decided during implementation; see below).

**Why not a separate passage list?** A single `SourcePassage` often covers both
a threshold condition and a surrounding field (e.g., the same statutory article
sets both the notification threshold and the Phase 1 review clock). Splitting into
two passage types would duplicate quoted text and double the fetch burden.

**Tier model:** Rather than introducing a new int tier (which shifts all downstream
comparisons), `numbers_confirmed` (tier 2) is redefined as: threshold conditions
numeric-matched AND key numeric fields numeric-matched. This preserves the existing
tier scale.

**Relationship to Tier 4 (re-extraction / cross_checked):** This spec handles Tiers
1–2 for non-threshold fields — grounding quoted text and verifying numerics. Tier 4
(`verify_jurisdiction_reextract.py`) performs a cold independent extraction against
the same source URLs and diffs the structured output against the YAML — that is where
qualitative interpretation (mandatory vs voluntary, SLC vs SIEC) gets cross-checked,
independent of both the original Cursor extraction and any human corrections. These
two mechanisms are complementary: this spec ensures the evidence is anchored; Tier 4
ensures the interpretation is independently reproducible.

## Files

| File | Change |
|------|--------|
| `apps/api/app/screening/models/jurisdiction.py` | Add `supports_fields: list[str] = []` to `SourcePassage` |
| `apps/api/app/screening/services/jurisdiction_passages.py` | Add `resolve_field_value(rule, path) → float | None`; extend `verify_passages()` to iterate `supports_fields`; add `fields_grounded` property to `PassageReport` |
| `apps/api/app/screening/models/jurisdiction_verification.py` | Add `FieldVerification` model; add `fields_verified: dict[str, FieldVerification]` to `JurisdictionVerification`; add `fields_with_passage_support_count` + `key_fields_missing_support_count` to `BaselineCoverageReport` and `BaselineJurisdictionRow` |
| `apps/api/app/screening/services/jurisdiction_baseline.py` | Extend `compute_baseline_report()` to count field passage coverage across all jurisdictions |
| `apps/api/tests/test_jurisdiction_verification_model.py` | Extend `test_baseline_report_counts` with new field-coverage metrics; add tests for `resolve_field_value` edge cases |

The `_archetypes.yaml` schema and completeness gate are **not** changed in this
spec — the completeness gate should be extended to require key field passage
coverage as a follow-on once data is populated.

## Verification

From `apps/api/` with `.venv` active:

```bash
# Schema: SourcePassage accepts supports_fields
.venv/bin/python -c "
from app.screening.models.jurisdiction import SourcePassage
p = SourcePassage(
    passage_id='test', document_title='T', article_reference='Art 1',
    document_url='https://example.com', quoted_text='25 working days',
    supports_conditions=[], supports_fields=['review_periods.phase_1.days']
)
assert p.supports_fields == ['review_periods.phase_1.days']
print('SourcePassage.supports_fields: OK')
"

# Field resolver: correct navigation
.venv/bin/python -c "
from app.screening.services.jurisdiction_passages import resolve_field_value
from app.screening.services.threshold_engine import load_all_jurisdictions
rules = {r.jurisdiction_id: r for r in load_all_jurisdictions('../../data/jurisdictions')}
# EU phase_1 review period should resolve to an integer
val = resolve_field_value(rules['eu'], 'review_periods.phase_1.days')
assert val is not None, 'expected a value for eu review_periods.phase_1.days'
print(f'eu review_periods.phase_1.days: {val}')
"

# Full test suite
.venv/bin/python -m pytest tests/test_jurisdiction_verification_model.py tests/test_jurisdiction_passages.py -v

# Baseline report includes new field-coverage metrics
.venv/bin/python -c "
from app.screening.services.jurisdiction_baseline import compute_baseline_report
from pathlib import Path
report = compute_baseline_report(
    Path('../../data/jurisdictions'),
    Path('../../data/jurisdictions/_archetypes.yaml'),
)
print('fields_with_passage_support_count:', report.fields_with_passage_support_count)
print('key_fields_missing_support_count:', report.key_fields_missing_support_count)
"

# Existing push-tier verification still passes
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
```

## Rollback

The `supports_fields` field defaults to `[]` — removing it from `SourcePassage`
is a backwards-compatible deletion (no existing YAML sets it until the data work
lands). Reverting the model file and the service changes is sufficient.
