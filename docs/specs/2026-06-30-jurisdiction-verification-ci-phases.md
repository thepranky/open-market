# Spec: Jurisdiction verification CI — three phases toward regulator alignment

Three sequential PRs that extend the jurisdiction verification pipeline from
**structural correctness** toward **detecting drift from the regulator’s current
legal position**. Each phase is one PR; implement in order.

**Context:** Today’s push tier gates schema/completeness/gold-deal regression only.
Nightly runs advisory offline passage checks and hard-fails on staleness
`drift_detected` (PR #43). Live source grounding is manual (`--tier full`). Only
US HSR has a staleness anchor. ~15 offline source fixtures exist.

**Reference:** `docs/operations/jurisdiction-verification.md`, DDR-E
(`docs/architecture/decisions/ddr-e-jurisdiction-verification.md`).

---

## Goal

After all three phases:

1. **Push (PR) tier** catches quote regressions on fixture-backed jurisdictions
   and blocks structural breaks (existing behaviour preserved).
2. **Nightly tier** detects annual threshold drift across all
   `annual_adjustment` jurisdictions and reports URL / passage backlog.
3. **Weekly live tier** fetches authoritative sources, reports quote/number
   mismatches, and alerts — without blocking merges during remediation.
4. **Verified jurisdictions** (sidecar tier ≥ `numbers_confirmed`) cannot
   regress on PR without a hard gate.

This does **not** claim lawyer-grade legal accuracy for all 47 profiles. It
builds progressive assurance: structural → frozen-source regression → annual
numeric drift → live drift monitoring → no regression on verified profiles.

---

## Out of scope (all phases)

- Auto-rewriting jurisdiction YAML from live fetch or re-extraction (report only).
- Hard-failing all PRs on live passage checks while most profiles remain below tier 2.
- Adversarial agent loop (operations doc PR 9).
- Expanding passage grounding to non-threshold fields (see
  `docs/specs/2026-06-25-expand-field-grounding.md`).
- Case source integrity / `check_source_integrity.py` (ROADMAP 9.3 case lane).
- Slack/email provider choice — use GitHub Actions job summary + optional
  `workflow_dispatch` artifact; webhook URL via repo secret if configured.

---

## Tier contract (target state)

| Trigger | Gates | Network | Blocks merge |
|---------|-------|---------|--------------|
| **push** (PR touching `data/jurisdictions/**`) | Schema, completeness, gold deals, offline passage on **changed** jurisdictions with fixtures, progressive hard gate for tier-2+ | Offline | Yes |
| **nightly** (cron) | push gates + advisory offline passages + staleness (`drift_detected` hard) + advisory URL check | Offline + anchor compare | No |
| **weekly** (cron) | `--tier full` live passage + re-extract diff | Live | No (alert + artifact) |
| **manual** `workflow_dispatch` | Any tier | Per tier | No |

Push and nightly remain **different by design** — fast deterministic PR gates vs
monitoring dashboard. Weekly adds the live “current law” signal.

---

# Phase 1 — Close easy gaps (ROADMAP 6.1)

## Goal

Detect annual threshold drift for all `annual_adjustment` jurisdictions; catch
quote regressions on PRs that edit fixture-backed YAML; surface broken source
URLs nightly without blocking merges.

## Approach

### 1a. Expand staleness anchors

Add entries to `data/jurisdictions/_staleness_anchors.yaml` for every
jurisdiction YAML that has at least one `threshold_tests[].annual_adjustment:
true`.

**Current set (13 files):** `ar`, `ca`, `cl`, `co`, `il`, `it`, `mx`, `no`,
`pe`, `ph`, `pt`, `us_hsr` (already anchored).

For each jurisdiction:

- `policy_source`: URL of the official annual notice, gazette, or authority
  page that publishes current threshold values.
- `effective_date`: ISO date of the notice in force.
- `policy_window_days`: default `180` unless jurisdiction publishes on a
  fixed calendar (e.g. US HSR February).
- `thresholds`: map of `condition_id` → expected numeric `value` from that
  notice (same units as YAML).

Anchor curation is **manual research** in this PR (or a companion data commit in
the same PR). The gate compares YAML values to anchors only — it does not live-fetch
the `policy_source` URL in phase 1.

**Exit behaviour:** unchanged from PR #43 — nightly passes
`--allow-unknown`; `drift_detected` still hard-fails nightly.

### 1b. Push-tier offline passage check on changed jurisdictions

Extend `run_jurisdiction_verification.py` push tier:

1. Detect changed jurisdiction YAML files in the PR via
   `git diff --name-only origin/main...HEAD -- data/jurisdictions/*.yaml`
   (exclude `_*.yaml` config files and `*.verification.yaml` sidecars).
2. For each changed `jurisdiction_id`, if an offline fixture exists for any
   of its `source_passages[].document_url` (same mapping as
   `build_offline_fetch`), run:

   ```bash
   verify_jurisdiction_passages.py --offline --json -j <id>
   ```

3. **Hard-fail** push tier if any such jurisdiction fails passage gate.
4. If changed jurisdiction has **no** matching fixtures, skip (no new failure).

Add helper `fixture_backed_jurisdiction_ids(fixtures_dir) -> set[str]` in
`jurisdiction_passages.py` that returns jurisdiction IDs verifiable offline
(derive from which fixture URL keys each jurisdiction’s passages reference).

**CI wiring:** In `jurisdiction-verification.yml` PR job, pass changed files
env var or let orchestrator run git diff internally (prefer internal — works
locally too).

### 1c. Nightly advisory URL check

Add optional step to nightly tier in orchestrator:

```bash
verify_jurisdiction_urls.py --json
```

via new `_run(..., required=False)` — same advisory pattern as offline passages.
Broken links appear in logs; exit 0 unless script crashes.

Do **not** add URL check to push tier (network flake on every PR).

## Files

| File | Change |
|------|--------|
| `data/jurisdictions/_staleness_anchors.yaml` | Add anchors for 12 remaining annual-adjustment jurisdictions |
| `apps/api/app/screening/services/jurisdiction_passages.py` | `fixture_backed_jurisdiction_ids()` helper |
| `apps/api/scripts/screening/run_jurisdiction_verification.py` | Push: offline passage on git-changed fixture-backed IDs; nightly: advisory URL check |
| `apps/api/scripts/screening/verify_jurisdiction_urls.py` | Add `--json` output mode if not present |
| `apps/api/tests/test_verify_jurisdiction_passages.py` | Test `fixture_backed_jurisdiction_ids` |
| `apps/api/tests/test_run_jurisdiction_verification.py` | New: push tier skips passage when no fixtures; hard-fails injected quote mismatch on changed uk |
| `.github/workflows/jurisdiction-verification.yml` | Comment update documenting push offline passage behaviour |

## Verification

```bash
cd apps/api

# Staleness: all annual-adjustment jurisdictions have anchors (no unknown for anchored set)
.venv/bin/python scripts/screening/monitor_jurisdiction_staleness.py --json | \
  python -c "import sys,json; r=json.load(sys.stdin); assert r['failed']==0, r"

# Push tier passes on main
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push

# Nightly tier passes (advisory sections may print ADVISORY: lines)
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier nightly

# Offline passage on UK fixture jurisdiction
.venv/bin/python scripts/screening/verify_jurisdiction_passages.py --offline -j uk --json

# Unit tests
.venv/bin/python -m pytest -q \
  tests/test_verify_jurisdiction_passages.py \
  tests/test_monitor_jurisdiction_staleness.py \
  tests/test_run_jurisdiction_verification.py
```

Expected: all commands exit 0; staleness `failed` count 0 when YAML matches anchors.

---

# Phase 2 — Live monitoring (ROADMAP 6.2)

## Goal

Automated weekly live verification against regulator websites; structured report
artifacts; GitHub Actions failure + summary on drift so the team is notified
without blocking merges.

Partially delivers ROADMAP 9.3 (jurisdiction alerting lane).

## Approach

### 2a. Weekly workflow job

New workflow file `.github/workflows/jurisdiction-verification-weekly.yml` (or
second job in existing workflow with `schedule: cron: "0 5 * * 0"` — Sunday 05:00 UTC).

```yaml
on:
  schedule:
    - cron: "0 5 * * 0"
  workflow_dispatch:
    inputs:
      tier:
        default: full
        type: choice
        options: [full]
```

Job runs:

```bash
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier full
.venv/bin/python scripts/screening/verify_jurisdiction_reextract.py --json \
  > /tmp/jurisdiction_reextract.json
```

**Exit code policy for weekly job:**

- Orchestrator `--tier full`: passage gate **required=True** (strict live).
- Job **always uploads artifacts** (passage JSON, reextract JSON, staleness JSON).
- Job **fails the workflow** (exit 1) when:
  - staleness `drift_detected`, OR
  - any jurisdiction with sidecar `source_verification_tier >= numbers_confirmed`
    fails live passage gate (regression on previously verified profile)
- Job **passes** (exit 0) when only unverified/low-tier jurisdictions fail live
  passage — backlog remains visible in artifact, not as CI failure.

Implement `weekly_failure_predicate(reports, sidecars) -> bool` in orchestrator
or a small `scripts/screening/evaluate_weekly_verification.py` wrapper.

### 2b. Sharding (optional fallback)

If weekly full run exceeds 30-minute timeout or flakes heavily, add
`--jurisdiction-batch N/7` to run ~7 jurisdictions per day (full sweep in a
week). **Default:** all 47 in one job; add sharding only if first weekly run
proves necessary (document in workflow comment).

### 2c. Alerting

On workflow failure:

- GitHub Actions job failure notification (default).
- Write human-readable summary to `$GITHUB_STEP_SUMMARY` with: drift list,
  tier-2+ regressions, broken URL count.
- Upload artifacts: `jurisdiction-weekly-passages.json`,
  `jurisdiction-weekly-reextract.json` (90-day retention, `if: always()`).

Optional: if `VERIFICATION_ALERT_WEBHOOK` secret set, POST summary JSON (single
`httpx.post` in orchestrator — no new abstraction).

### 2d. Wire re-extract into full tier

Add to `run_jurisdiction_verification.py` when `tier == full`:

```bash
verify_jurisdiction_reextract.py --json
```

`required=False` (report-only) unless sidecar tier is `cross_checked`, in which
case hard-fail on mismatch.

## Files

| File | Change |
|------|--------|
| `.github/workflows/jurisdiction-verification-weekly.yml` | New weekly scheduled workflow |
| `apps/api/scripts/screening/run_jurisdiction_verification.py` | Full tier: weekly failure predicate; optional reextract step |
| `apps/api/scripts/screening/evaluate_weekly_verification.py` | New: encode pass/fail rules for weekly job |
| `apps/api/tests/test_evaluate_weekly_verification.py` | Unit tests for failure predicate |

## Verification

```bash
cd apps/api

# Full tier runs locally (may fail on live network — expected during remediation)
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier full; echo "exit:$?"

# Weekly predicate unit tests
.venv/bin/python -m pytest -q tests/test_evaluate_weekly_verification.py

# Re-extract offline (UK)
.venv/bin/python scripts/screening/verify_jurisdiction_reextract.py -j uk --json
```

Manual: trigger `workflow_dispatch` on the weekly workflow; confirm artifacts
upload and step summary renders.

---

# Phase 3 — Progressive assurance (ROADMAP 6.3)

## Goal

Jurisdictions already at `numbers_confirmed` (or higher) cannot regress on PR.
Document fixture-capture workflow so each live remediation permanently adds
offline push coverage.

## Approach

### 3a. Progressive hard gate on push

In push tier offline passage check (phase 1b), extend failure rules:

| Sidecar tier | Changed jurisdiction | Push passage gate |
|--------------|---------------------|-------------------|
| `< numbers_confirmed` | any | Hard-fail only if fixtures exist (phase 1b) |
| `>= numbers_confirmed` | YAML or sidecar changed | **Hard-fail** on offline passage failure |
| `>= numbers_confirmed` | unchanged | Skip |

Load sidecar from `data/jurisdictions/{id}.verification.yaml` via existing
`jurisdiction_verification_store.load_sidecar`.

If tier ≥ `numbers_confirmed` but **no** offline fixtures exist, hard-fail with
explicit code `missing_offline_fixture_for_verified_jurisdiction` — forces
fixture capture before claiming tier 2 on CI.

### 3b. Fixture capture convention

Add `docs/operations/jurisdiction-fixture-capture.md` (short runbook):

1. Run live passage gate for jurisdiction; fix YAML until pass.
2. Save normalized source text to
   `apps/api/tests/fixtures/jurisdiction_sources/{jurisdiction}_{source_key}.txt`
   with provenance header (URL + “Source:” marker in first 1200 chars — existing
   `fixture_provenance_issues` guard).
3. Register URL substring mapping in `build_offline_fetch` if not filename-derived.
4. Re-run push tier offline; commit fixture + YAML + sidecar in same PR.

Add CI test that `fixture_provenance_issues(default_fixtures_dir())` returns [].

### 3c. Nightly report metric

Extend nightly orchestrator stdout (or JSON artifact when `--json` passed to
orchestrator — add flag if useful) with counts:

- jurisdictions at each `source_verification_tier`
- fixture-backed vs live-only verified count

No new gate — observability only.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/screening/run_jurisdiction_verification.py` | Progressive tier-2+ hard gate logic |
| `apps/api/app/screening/services/jurisdiction_passages.py` | Expose `missing_fixture_for_verified()` helper |
| `docs/operations/jurisdiction-fixture-capture.md` | New runbook |
| `apps/api/tests/test_run_jurisdiction_verification.py` | Tier-2+ regression cases |
| `apps/api/tests/test_verify_jurisdiction_passages.py` | Provenance guard test (may exist — extend if so) |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest -q \
  tests/test_run_jurisdiction_verification.py \
  tests/test_verify_jurisdiction_passages.py

# Provenance guard clean
.venv/bin/python -c "
from app.screening.services.jurisdiction_passages import default_fixtures_dir, fixture_provenance_issues
assert fixture_provenance_issues(default_fixtures_dir()) == []
"

# Push tier on main
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
```

---

## Implementation order

| PR | ROADMAP | Depends on |
|----|---------|------------|
| Phase 1 | 6.1 | PR #43 merged (nightly advisory baseline) |
| Phase 2 | 6.2 | 6.1 |
| Phase 3 | 6.3 | 6.1 (6.2 optional) |

## Rollback

- Phase 1: revert orchestrator push passage step; remove new anchors (US HSR anchor remains).
- Phase 2: disable weekly workflow (`workflow_dispatch` only).
- Phase 3: revert progressive gate; push tier falls back to phase 1 behaviour.
