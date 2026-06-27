# Spec: Data-contract CI gates (ROADMAP 3.1–3.4)

## Goal

Gate PR merges on data-contract validation when relevant YAML changes, without touching
unrelated PRs. Three path-filtered CI jobs enforce the contracts defined in
[DDR-A](../../architecture/decisions/ddr-a-data-contracts.md): canonical case schema
(`data/cases/**`), jurisdiction push-tier verification (`data/jurisdictions/**`), and
case-index schema (`data/case_index/**`). A fourth change adds the DDR-A cross-link to
the case-research architecture doc. All jobs run in `apps/api/` with the existing Python
venv pattern; no new dependencies or third-party actions are introduced.

## Approach

### 3.1 — Canonical case schema gate

New workflow `.github/workflows/data-contracts.yml` triggers on `pull_request` to `main`
when `data/cases/**` or `data/case_index/**` changes (GitHub native path filter; no
third-party action). It installs dependencies the same way as `api-ci.yml` and runs:

```
.venv/bin/python scripts/cases/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python -m pytest tests/test_schema.py -v
```

`test_schema.py` is not currently in `api-ci.yml`'s test list; this workflow is the first
to run it in CI.

### 3.2 — Jurisdiction push-tier gate on PR

Extend `.github/workflows/jurisdiction-verification.yml` to add a `pull_request` trigger
with `paths: ['data/jurisdictions/**']`. Update the in-job tier-selection logic to treat
`pull_request` events as `push` tier (alongside `workflow_dispatch`). The nightly schedule
trigger and its `nightly` tier are unchanged.

### 3.3 — Case-index schema gate

New script `apps/api/scripts/cases/validate_case_index.py` — a thin CLI wrapper mirroring
`validate_cases.py` but iterating via `index_loader.load_all_index_cases()`. Chosen over
extending `validator.py` because each data layer already has its own loader iteration
function and each script is a ~15-line CLI wrapper over it; merging them would require
making `validator.py` generic or adding a second function with different semantics, touching
more code for no gain.

This script is added as a second job (`validate-case-index`) in the same
`data-contracts.yml` workflow. Both jobs run whenever either `data/cases/**` or
`data/case_index/**` changes — the overlap is negligible (both are sub-second Pydantic
runs).

**Baseline fix required before enabling this gate:**

Running `validate_case_index.py` against the current `data/case_index/` tree fails on
2647 of 2840 files with:

```
CaseIndexEntry
pdf_url
  Extra inputs are not permitted [type=extra_forbidden]
```

`CaseIndexEntry` has `extra="forbid"` and lacks a `pdf_url` field, but the YAML files
written by scrape scripts include one. Fix: add `pdf_url: Optional[str] = None` to
`CaseIndexEntry` in `apps/api/app/cases/models/case_index.py`. This is a one-line
additive change; no existing code breaks.

This fix must land in the same PR as the CI gate, otherwise CI will fail immediately on
merge.

### 3.4 — DDR-A cross-link in case-research doc

Add one sentence to the Data layout section of `docs/architecture/case-research.md`
linking to `docs/architecture/decisions/ddr-a-data-contracts.md`. No other changes to
that file.

## Files to touch

| File | Change |
|------|--------|
| `.github/workflows/data-contracts.yml` | New — path-filtered PR workflow for 3.1 + 3.3 |
| `.github/workflows/jurisdiction-verification.yml` | Add `pull_request` + paths trigger; update tier logic |
| `apps/api/scripts/cases/validate_case_index.py` | New — CLI wrapper for case-index validation |
| `apps/api/app/cases/models/case_index.py` | Add `pdf_url: Optional[str] = None` (baseline fix) |
| `docs/architecture/case-research.md` | Add DDR-A link in Data layout section |

## Workflow sketches

### `.github/workflows/data-contracts.yml` (new)

```yaml
name: Data contracts

on:
  pull_request:
    branches: [main]
    paths:
      - 'data/cases/**'
      - 'data/case_index/**'

permissions:
  contents: read

jobs:
  validate-cases:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: apps/api
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install dependencies
        run: |
          python -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install -r requirements.txt
      - name: Validate case schema
        run: .venv/bin/python scripts/cases/validate_cases.py --cases-dir ../../data/cases
      - name: Run schema tests
        run: .venv/bin/python -m pytest tests/test_schema.py -v

  validate-case-index:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: apps/api
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install dependencies
        run: |
          python -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install -r requirements.txt
      - name: Validate case-index schema
        run: .venv/bin/python scripts/cases/validate_case_index.py --index-dir ../../data/case_index
```

### `jurisdiction-verification.yml` — diff only

```yaml
on:
  schedule:
    - cron: "0 4 * * *"
  pull_request:               # add
    branches: [main]          # add
    paths:                    # add
      - 'data/jurisdictions/**'  # add
  workflow_dispatch:
    ...

# In the verify job steps, update tier selection:
      - name: Run verification orchestrator
        env:
          EVENT_NAME: ${{ github.event_name }}
          INPUT_TIER: ${{ inputs.tier }}
        run: |
          if [ "$EVENT_NAME" = "schedule" ]; then
            TIER="nightly"
          elif [ "$EVENT_NAME" = "pull_request" ]; then   # add
            TIER="push"                                    # add
          else
            TIER="${INPUT_TIER:-push}"
          fi
          .venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier "$TIER"
```

### `validate_case_index.py` (new)

```python
#!/usr/bin/env python3
"""
Validate all YAML case-index entries against CaseIndexEntry.

Usage:
  python apps/api/scripts/cases/validate_case_index.py [--index-dir data/case_index]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.cases.loader.index_loader import load_all_index_cases


def main():
    parser = argparse.ArgumentParser(description="Validate Meridian YAML case-index entries")
    parser.add_argument("--index-dir", default="data/case_index")
    args = parser.parse_args()

    print(f"Validating case index in {args.index_dir} ...\n")
    ok = 0
    errors = []
    for path, result in load_all_index_cases(args.index_dir):
        if isinstance(result, Exception):
            errors.append(f"{path}: {result}")
        else:
            ok += 1

    if errors:
        for msg in errors:
            print(f"ERROR: {msg}\n")

    print(f"Results: {ok} valid, {len(errors)} invalid")

    if errors:
        sys.exit(1)
    else:
        print("All case-index entries valid.")


if __name__ == "__main__":
    main()
```

## Verification

Run these from `apps/api/` with `.venv` active before raising the PR:

```bash
# 3.1 — case schema gate
.venv/bin/python scripts/cases/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python -m pytest tests/test_schema.py -v

# 3.3 — case-index schema gate (must pass after the pdf_url baseline fix)
.venv/bin/python scripts/cases/validate_case_index.py --index-dir ../../data/case_index

# 3.2 — jurisdiction push tier (offline fixtures only; no live network)
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
```

Expected CI behaviour:

| PR touches | `api-ci.yml` | `data-contracts.yml` | `jurisdiction-verification.yml` |
|------------|-------------|---------------------|--------------------------------|
| `apps/api/**` only | runs | skips | skips |
| `data/cases/**` | runs | runs (`validate-cases` + `validate-case-index`) | skips |
| `data/case_index/**` | runs | runs (`validate-cases` + `validate-case-index`) | skips |
| `data/jurisdictions/**` | runs | skips | runs (`--tier push`) |
| `docs/**` or unrelated | runs | skips | skips |

Note: `api-ci.yml` currently has no path filter, so it runs on every PR. That is unchanged.

Both `data-contracts.yml` jobs run when either `data/cases/**` or `data/case_index/**`
changes. The redundant run (e.g. only case_index changed but validate-cases also runs) is
acceptable; each job completes in under a minute.
