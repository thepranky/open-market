# DDR-D: Threshold engine

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `apps/api/app/screening/services/threshold_engine.py` (full file)
- `apps/api/app/screening/models/jurisdiction.py` — `threshold_tests`, conditions
- `data/jurisdictions/_gold_deals.yaml`
- `apps/api/tests/test_jurisdiction_regression.py`
- `apps/api/app/screening/routers/jurisdictions.py` → `features/screening/components/ScreenClient.tsx`

Screen a test deal via API docs or curl.

## Agent prompt

> Teach me `threshold_engine.py` from `DealParameters` through `screen_jurisdiction`. Explain how threshold tests compose (AND/OR), gap-to-trigger, and confidence fields. Walk one gold deal from `_gold_deals.yaml` through regression test. Why in-memory YAML vs DB? What's untested beyond gold-deal regression?

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
