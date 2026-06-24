# DDR-E: Jurisdiction verification

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `docs/operations/jurisdiction-verification.md`
- `apps/api/scripts/screening/run_jurisdiction_verification.py`
- `apps/api/app/services/jurisdiction_completeness.py`, `jurisdiction_passages.py`, `jurisdiction_staleness.py`, `jurisdiction_regression.py`
- `apps/api/app/models/jurisdiction_verification.py`
- `apps/web/src/features/screening/components/VerificationBadges.tsx`

Run: `run_jurisdiction_verification.py --tier push`

## Agent prompt

> Explain the jurisdiction verification programme: tiers (push/nightly/full), each gate, and what "verified" means in the UI. How do archetypes, completeness, passages, staleness, and gold-deal regression fit together? Compare to case `check_source_integrity.py`. What's the data-remediation vs automation split? Gaps for lawyer-grade reliance.

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
