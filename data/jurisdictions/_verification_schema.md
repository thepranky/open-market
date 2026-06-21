# Jurisdiction Verification Sidecar Schema

Sidecars sit beside jurisdiction YAML files:

```
data/jurisdictions/uk.yaml
data/jurisdictions/uk.verification.yaml
```

They store machine-generated verification metadata. Hand-edited jurisdiction YAML remains the source of legal content.

## Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `jurisdiction_id` | string | Must match sibling YAML |
| `verified_at` | datetime | Last gate run that updated this sidecar |
| `source_verification_tier` | int 0–4 | Highest passed source grounding tier |
| `source_tier_breakdown` | object | Per-gate pass/fail/skip status |
| `regression_status` | enum | `not_run` \| `passed` \| `failed` |
| `freshness_status` | enum | `fresh` \| `stale` \| `drift_detected` \| `unknown` |
| `freshness` | object | Staleness check metadata |
| `failures` | array | Structured gate failures |
| `conditions_verified` | object | Per-condition verification detail |

## Source verification tiers

| Tier | Name | Meaning |
|------|------|---------|
| 0 | `schema_valid` | YAML loads; URLs present or explicitly unreachable |
| 1 | `passages_grounded` | Hard-fact passages found in linked sources |
| 2 | `numbers_confirmed` | Grounded numbers match YAML values |
| 3 | `structure_complete` | Archetype checklist satisfied |
| 4 | `cross_checked` | Independent re-extraction agrees |

Regression and freshness are separate signals — not higher tiers.

## Example

```yaml
jurisdiction_id: uk
verified_at: "2026-06-20T14:00:00Z"
source_verification_tier: 3
source_tier_breakdown:
  passages_grounded: pass
  numbers_confirmed: pass
  structure_complete: pass
  cross_checked: not_run
regression_status: not_run
freshness_status: fresh
freshness:
  checked_at: "2026-06-20T14:00:00Z"
  policy_window_days: 180
  anchors_checked: []
failures: []
conditions_verified:
  uk_turnover_target:
    tier: 2
    passage_id: uk_ea2002_s23_1
    numeric_match: true
    source_type: primary_legislation
```

## Gate status values

`source_tier_breakdown` values: `pass`, `fail`, `skip`, `not_run`.

## Failure object

```yaml
- gate: verify_jurisdiction_passages
  code: quote_not_found
  message: Quoted text not found at document_url
  field_path: source_passages[0].quoted_text
```
