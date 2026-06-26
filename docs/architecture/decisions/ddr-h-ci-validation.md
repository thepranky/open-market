# DDR-H: CI, tests, and validation gates


## Before you start

Read/trace:
- `.github/workflows/api-ci.yml`, `jurisdiction-verification.yml`
- `apps/api/tests/` — list files; skim `test_schema.py`, `test_eval_pipeline.py`
- `data/evals/benchmark.market_definition.ci.yaml`
- `apps/api/scripts/cases/integrity/validate_cases.py`, `apps/api/scripts/cases/evals/run_eval_benchmark.py`, `apps/api/scripts/screening/run_jurisdiction_verification.py`
- `CLAUDE.md` validation gates section vs what CI actually runs

Run locally: `pytest tests/test_schema.py -v` and compare to CI test list.

## Agent prompt

> Audit Meridian's test and CI story. What runs on every PR vs nightly vs manual? Map each validation script to when it should run. List tests that exist but aren't in CI. Explain the eval benchmark pass criteria. What would you add to PR CI first and why? How does this relate to promotion gates vs merge gates?

---

## What it does

## Why this way

## Alternatives considered

## Gaps
