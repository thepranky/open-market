# Jurisdiction Verification Baseline

*Generated 2026-06-21 by `report_jurisdiction_verification_baseline.py`.*

## Summary

| Metric | Count |
|--------|-------|
| Jurisdiction YAML profiles | 47 |
| Threshold conditions | 163 |
| Conditions with `source_type: primary_legislation` | 119 |
| Authoritative hard-fact conditions | 155 |
| Conditions with direct `source_url` | 17 |
| `source_passages[]` entries | 60 |
| Condition IDs supported by passages | 103 |
| Authoritative conditions missing passage support | 54 |
| Jurisdictions with no `source_passages` | 10 |
| Annual-adjustment threshold tests | 12 |

## Jurisdictions without source passages

`cl`, `cz`, `dk`, `gr`, `hu`, `id`, `pe`, `ph`, `pt`, `ro`

## Per-jurisdiction coverage

| Jurisdiction | Conditions | Auth. | Passages | Supported | Missing support | Annual tests | Archetypes |
|--------------|------------|-------|----------|-----------|-----------------|--------------|------------|
| `ar` | 1 | 1 | 1 | 1 | 0 | 1 | mandatory_turnover |
| `at` | 6 | 6 | 2 | 3 | 3 | 0 | mandatory_turnover |
| `au` | 8 | 8 | 2 | 4 | 4 | 0 | mandatory_turnover |
| `be` | 2 | 2 | 2 | 2 | 0 | 0 | mandatory_turnover |
| `br` | 2 | 2 | 1 | 2 | 0 | 0 | market_share_trigger |
| `ca` | 4 | 4 | 2 | 4 | 0 | 2 | mandatory_turnover |
| `ch` | 4 | 4 | 2 | 4 | 0 | 0 | mandatory_turnover |
| `cl` | 2 | 2 | 0 | 0 | 2 | 1 | mandatory_turnover |
| `cn` | 4 | 4 | 2 | 4 | 0 | 0 | mandatory_turnover |
| `co` | 2 | 2 | 1 | 2 | 0 | 1 | market_share_trigger |
| `cz` | 4 | 4 | 0 | 0 | 4 | 0 | mandatory_turnover |
| `de` | 6 | 6 | 2 | 3 | 3 | 0 | mandatory_turnover |
| `dk` | 4 | 4 | 0 | 0 | 4 | 0 | mandatory_turnover |
| `eg` | 4 | 0 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `es` | 3 | 3 | 2 | 3 | 0 | 0 | mandatory_turnover |
| `eu` | 6 | 6 | 5 | 6 | 0 | 0 | eu_turnover, fdi_parallel |
| `fi` | 2 | 2 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `fr` | 4 | 4 | 2 | 2 | 2 | 0 | mandatory_turnover |
| `gr` | 2 | 2 | 0 | 0 | 2 | 0 | mandatory_turnover |
| `hu` | 2 | 2 | 0 | 0 | 2 | 0 | mandatory_turnover |
| `id` | 1 | 1 | 0 | 0 | 1 | 0 | mandatory_turnover |
| `il` | 3 | 3 | 1 | 3 | 0 | 0 | mandatory_turnover |
| `in` | 5 | 5 | 2 | 4 | 1 | 0 | mandatory_turnover |
| `it` | 2 | 2 | 2 | 2 | 0 | 1 | mandatory_turnover |
| `jp` | 6 | 6 | 2 | 2 | 4 | 0 | mandatory_turnover |
| `ke` | 2 | 2 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `kr` | 8 | 4 | 2 | 4 | 0 | 0 | mandatory_turnover |
| `mx` | 3 | 3 | 1 | 3 | 0 | 2 | mandatory_turnover |
| `ng` | 2 | 2 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `nl` | 2 | 2 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `no` | 2 | 2 | 2 | 2 | 0 | 0 | mandatory_turnover |
| `nz` | 1 | 1 | 1 | 1 | 0 | 0 | mandatory_turnover |
| `pe` | 2 | 2 | 0 | 0 | 2 | 1 | mandatory_turnover |
| `ph` | 2 | 2 | 0 | 0 | 2 | 1 | mandatory_turnover |
| `pl` | 2 | 2 | 2 | 2 | 0 | 0 | mandatory_turnover |
| `pt` | 4 | 4 | 0 | 0 | 4 | 0 | mandatory_turnover |
| `ro` | 2 | 2 | 0 | 0 | 2 | 0 | mandatory_turnover |
| `ru` | 4 | 4 | 1 | 4 | 0 | 0 | mandatory_turnover |
| `sa` | 3 | 3 | 1 | 3 | 0 | 0 | mandatory_turnover |
| `se` | 2 | 2 | 2 | 2 | 0 | 0 | mandatory_turnover |
| `sg` | 2 | 2 | 2 | 2 | 0 | 0 | mandatory_turnover |
| `tr` | 4 | 4 | 1 | 2 | 2 | 0 | mandatory_turnover |
| `tw` | 8 | 8 | 1 | 4 | 4 | 0 | mandatory_turnover |
| `uae` | 2 | 2 | 1 | 2 | 0 | 0 | mandatory_turnover |
| `uk` | 5 | 5 | 2 | 3 | 2 | 0 | voluntary_slc, fdi_parallel |
| `us_hsr` | 4 | 4 | 2 | 4 | 0 | 2 | us_hsr_two_tier |
| `za` | 8 | 8 | 1 | 4 | 4 | 0 | mandatory_turnover |

---

Regenerate with:

```bash
python apps/api/scripts/report_jurisdiction_verification_baseline.py --write
```
