# Jurisdiction Verification Build — Planning & Implementation Guide

*Created 2026-06-20. Reference doc for the automated jurisdiction profile verification programme.*

---

## Purpose

CompMap has 47 jurisdiction YAML profiles covering merger control thresholds, regime flags, review periods, gun-jumping, FDI screening, and practical nuance. These were largely produced by research agents. Before lawyers can rely on screening results for first-instance transaction review, each profile must be **machine-verified against primary sources** — not manually lawyer-reviewed, but grounded with explicit confidence tiers.

This document is the single reference for scope, architecture, PR plan, and acceptance criteria. **Do not start implementation until this doc is signed off.**

---

## Current state (post-commit baseline)

### What exists today

| Layer | Status |
|-------|--------|
| **Schema** | Rich Pydantic model in `apps/api/app/models/jurisdiction.py`; spec in `data/jurisdictions/_schema.md` |
| **Data** | 47 jurisdiction YAMLs with thresholds, `source_passages`, `minority_thresholds`, practitioner notes |
| **Screening** | `threshold_engine.py` evaluates deals; `/jurisdictions/screen` returns status + legal citations |
| **URL check** | `apps/api/scripts/verify_jurisdiction_urls.py` — async link checker (live links ≠ accurate content) |
| **Maintenance** | `fix_jurisdiction_redirects.py`, `insert_minority_thresholds.py` |
| **UI** | Chat intake (`/screen`), jurisdiction detail pages, `last_verified` dates |

### What is missing

| Gap | Risk |
|-----|------|
| Quote grounding | Agent may have paraphrased or hallucinated statutory text |
| Numeric verification | Threshold values may not match the cited provision |
| Completeness | Missing tests, exclusions, or archetype-specific fields |
| Logic correctness | Engine may mis-evaluate even with correct YAML |
| Staleness | Annual-adjustment jurisdictions (e.g. US HSR) drift without detection |
| Confidence surfacing | UI treats all fields as equally reliable |

### Precedent in this repo

The case ingestion pipeline already solves a similar problem:

- `repair_source_passages.py` — grounds quotes in PDF text
- Quote validation gate — rejects passages not found in source
- Gold fixtures — `data/evals/gold/` for regression
- Review status + confidence on every field

**This build ports that pattern to jurisdiction YAML.**

---

## Quality model

### Verification tiers

Every jurisdiction profile (and optionally every field) carries a tier. Screening confidence is capped by the **lowest tier among fields used in that result**.

| Tier | Name | Meaning | Automated gate |
|------|------|---------|----------------|
| 0 | `schema_valid` | Pydantic load + URL live | Existing schema + `verify_jurisdiction_urls.py` |
| 1 | `passages_grounded` | All primary-legislation conditions have verbatim quotes found in linked sources | `verify_jurisdiction_passages.py` |
| 2 | `numbers_confirmed` | Extracted numbers from passages match condition values | Same script, numeric pass |
| 3 | `structure_complete` | Archetype checklist satisfied; condition↔passage linkage enforced | `verify_jurisdiction_completeness.py` |
| 4 | `cross_checked` | Independent re-extraction agrees on all numeric conditions | `verify_jurisdiction_reextract.py` |
| 5 | `regression_passed` | Gold deal suite passes for jurisdiction archetype | `test_jurisdiction_regression.py` |
| 6 | `fresh` | Staleness monitor green (<6 months, or post official update) | `monitor_jurisdiction_staleness.py` |

### Field classes

Not all fields need the same tier to be useful:

| Class | Examples | Required tier for high-confidence screening |
|-------|----------|---------------------------------------------|
| **Hard facts** | Threshold numbers, mandatory/suspensory flags, phase days | Tier 2+ |
| **Structured nuance** | Exclusions, minority threshold rules with citations | Tier 1+ |
| **Practitioner synthesis** | Control threshold narrative, CMA discretion notes | Tier 0; show as guidance only |

Hard facts drive screening results. Synthesis fields are displayed but never raise confidence above `medium` unless passage-grounded.

---

## Architecture

```mermaid
flowchart TB
    subgraph inputs [Inputs]
        YAML[Jurisdiction YAML]
        Primary[Primary source URLs]
        Gold[Gold deal fixtures]
    end

    subgraph gates [Verification gates]
        G0[Schema + URL check]
        G1[Passage grounding]
        G2[Numeric match]
        G3[Completeness rubric]
        G4[Re-extraction diff]
        G5[Gold deal regression]
        G6[Staleness monitor]
    end

    subgraph outputs [Outputs]
        Report[Verification report JSON]
        Sidecar[.verification.yaml sidecar]
        API[Screening API confidence]
        UI[UI tier badges]
    end

    YAML --> G0
    Primary --> G1
    G0 --> G1
    G1 --> G2
    G2 --> G3
    G3 --> G4
    Gold --> G5
    G4 --> G5
    G5 --> G6
    G6 --> Report
    Report --> Sidecar
    Sidecar --> API
    Sidecar --> UI
```

### Sidecar file convention

Verification metadata lives in a sidecar to avoid polluting hand-edited YAML:

```
data/jurisdictions/uk.yaml
data/jurisdictions/uk.verification.yaml   ← generated by gates, committed after pass
```

```yaml
# uk.verification.yaml (example)
jurisdiction_id: uk
verified_at: "2026-06-20T14:00:00Z"
overall_tier: 4
tier_breakdown:
  passages_grounded: pass
  numbers_confirmed: pass
  structure_complete: pass
  cross_checked: pass
  regression_passed: fail   # pending gold deals for UK
  fresh: pass
failures: []
conditions_verified:
  uk_turnover_target:
    tier: 2
    passage_id: uk_ea2002_s23_1
    numeric_match: true
```

The threshold engine reads sidecar at load time to set per-jurisdiction `confidence` caps.

### Archetype templates

Completeness is checked against jurisdiction archetypes defined in:

```
data/jurisdictions/_archetypes.yaml
```

| Archetype | Jurisdictions | Required elements |
|-----------|---------------|-------------------|
| `eu_turnover` | eu | 2 tests, two-thirds exclusion, Article 7 gun-jumping |
| `us_hsr_two_tier` | us_hsr | standard + large transaction tests, annual_adjustment |
| `voluntary_slc` | uk | turnover + share-of-supply tests, voluntary regime flag |
| `mandatory_turnover` | de, fr, it, … | mandatory + suspensory, domestic/worldwide conditions |
| `market_share_trigger` | br, … | share-based conditions |
| `fdi_parallel` | uk, eu, … | fdi_screening section when applicable |

Archetypes are config, not code — easy to extend without redeploying gates.

---

## Source fetcher design

Shared library: `apps/api/app/services/source_fetcher.py`

| Source | Strategy |
|--------|----------|
| eur-lex.europa.eu | HTML fetch; extract `#TexteOnly` or article div |
| legislation.gov.uk | HTML fetch; extract section content |
| uscode.house.gov | HTML fetch; extract section text |
| ecfr.gov | HTML fetch; extract § text |
| ftc.gov press releases | HTML/PDF for annual threshold notices |
| Bot-protected sites | Mark `fetch_status: bot_protected`; skip numeric check, flag tier 0 |

Normalization pipeline:

1. Strip HTML tags and entities
2. Collapse whitespace
3. Unicode normalize (NFKC)
4. Fuzzy match threshold: exact first, then normalized substring (≥95% token overlap)

Reuse patterns from `repair_source_passages.py` where applicable.

---

## Gate specifications

### Gate 1: `verify_jurisdiction_passages.py`

**Purpose:** Prove quoted statutory text exists at the linked URL; prove numbers match.

**Checks per `source_passages[]` entry:**
- Fetch `document_url`
- Assert `quoted_text` found (normalized)
- For each `supports_conditions[]` ID, find matching condition in `threshold_tests`
- Extract numbers/currency from quote; compare to `condition.value` and `condition.currency`
- Fail if `source_type: primary_legislation` condition has no supporting passage

**Output:** JSON report + update sidecar. Exit 1 if any hard failure.

**CLI:**
```bash
python apps/api/scripts/verify_jurisdiction_passages.py [--jurisdiction uk] [--fix] [--verbose]
```

**Tests:** Fixture HTML snippets for EU Art 1(2), UK s.23, US HSR §801 — no live network in CI.

---

### Gate 2: `verify_jurisdiction_completeness.py`

**Purpose:** Structural completeness without fetching law.

**Checks:**
- Every `primary_legislation` condition has `source_url` or linked passage
- Every `threshold_tests[]` has `legal_basis` + `source_url`
- `annual_adjustment: true` → `effective_date` present
- Regime consistency: `mandatory: true` + `suspensory: true` → `gun_jumping` section exists
- Archetype checklist for jurisdiction's assigned archetype(s)
- No duplicate `condition_id` or `test_id`
- `practitioner` source_type requires `note` explaining why

**CLI:**
```bash
python apps/api/scripts/verify_jurisdiction_completeness.py [--jurisdiction all]
```

---

### Gate 3: `verify_jurisdiction_reextract.py`

**Purpose:** Independent extraction cross-check.

**Flow:**
1. For each jurisdiction, collect all `source_url` / `document_url` from primary-legislation conditions
2. Run structured extraction (Gemini with strict JSON schema): thresholds only, no prose
3. Diff against existing YAML numerics (value, operator, party, scope)
4. Report mismatches; do not auto-write YAML

**Promotion rule:** Tier 4 requires zero unresolved mismatches (or explicit `accepted_drift` entry in sidecar with reason).

---

### Gate 4: Gold deal regression suite

**Purpose:** Behavioral correctness of screening engine + YAML logic.

**Data:** `data/jurisdictions/_gold_deals.yaml`

```yaml
deals:
  - deal_id: eu_below_threshold_2019
    description: "Public deal confirmed no EU notification required"
    jurisdictions: [eu]
    expected:
      eu: not_triggered
    deal:
      acquirer: { worldwide: 3_000_000_000, eu_eea: 200_000_000 }
      target: { worldwide: 500_000_000, eu_eea: 100_000_000 }
    source_url: "https://..."
```

**Target:** Minimum 3 deals per major archetype (EU, US HSR, UK, DE, FR) = ~15 deals for v1.

**Test:** `apps/api/tests/test_jurisdiction_regression.py` — parametrize over gold deals.

---

### Gate 5: `monitor_jurisdiction_staleness.py`

**Purpose:** Detect drift in annual-adjustment jurisdictions.

**For each YAML with `annual_adjustment: true`:**
- Fetch canonical anchor (FTC notice, official gazette, etc.)
- Extract current threshold values
- Compare to YAML
- If mismatch: set `staleness: detected` in sidecar, optionally open GitHub issue

**Schedule:** Weekly CI cron + manual pre-release run.

---

## PR plan

Branches follow `jurisdiction-verification/<slug>`. Each PR is one reviewable unit. Merge sequentially — later PRs depend on earlier ones.

### PR 1 — Scaffolding & verification model
**Branch:** `jurisdiction-verification/scaffolding`  
**Size:** ~400 lines  
**Review focus:** Data model, sidecar format, archetype config

| Deliverable | Path |
|-------------|------|
| Verification tier enums + sidecar Pydantic models | `apps/api/app/models/jurisdiction_verification.py` |
| Archetype templates | `data/jurisdictions/_archetypes.yaml` |
| Sidecar schema doc | `data/jurisdictions/_verification_schema.md` |
| Stub CLI entrypoints (no logic yet) | `apps/api/scripts/verify_jurisdiction_passages.py` (skeleton) |
| Unit tests for model load | `apps/api/tests/test_jurisdiction_verification_model.py` |

**Acceptance:** Models load; archetypes validate; stubs run `--help`.

---

### PR 2 — Source fetcher library
**Branch:** `jurisdiction-verification/source-fetcher`  
**Size:** ~500 lines  
**Review focus:** Fetch reliability, text normalization, offline fixtures

| Deliverable | Path |
|-------------|------|
| Fetch + normalize service | `apps/api/app/services/source_fetcher.py` |
| HTML fixture files for CI | `apps/api/tests/fixtures/jurisdiction_sources/` |
| Unit tests (offline) | `apps/api/tests/test_source_fetcher.py` |

**Acceptance:** Fixtures normalize and match expected text; live fetch works for eur-lex + legislation.gov.uk in manual smoke test.

---

### PR 3 — Passage grounding gate
**Branch:** `jurisdiction-verification/passage-gate`  
**Size:** ~700 lines  
**Review focus:** Quote matching logic, numeric extraction, failure reporting

| Deliverable | Path |
|-------------|------|
| Full implementation | `apps/api/scripts/verify_jurisdiction_passages.py` |
| Numeric extraction helpers | `apps/api/app/services/jurisdiction_numeric.py` |
| Tests with fixtures | `apps/api/tests/test_verify_jurisdiction_passages.py` |

**Acceptance:** Runs against EU, UK, US HSR fixtures offline; produces sidecar with tier 1–2 status; exit code reflects pass/fail.

**Note:** First PR that should be run against real YAML data. Expect failures — that's the point.

---

### PR 4 — Completeness & linkage gate
**Branch:** `jurisdiction-verification/completeness-gate`  
**Size:** ~450 lines  
**Review focus:** Archetype rules, linkage invariants

| Deliverable | Path |
|-------------|------|
| Completeness verifier | `apps/api/scripts/verify_jurisdiction_completeness.py` |
| Tests | `apps/api/tests/test_verify_jurisdiction_completeness.py` |

**Acceptance:** All 47 YAMLs run; report lists missing elements per archetype; tier 3 computed in sidecar.

---

### PR 5 — Cross-check & gold deal regression
**Branch:** `jurisdiction-verification/regression-suite`  
**Size:** ~650 lines  
**Review focus:** Gold deal selection, regression test design

| Deliverable | Path |
|-------------|------|
| Re-extraction diff script | `apps/api/scripts/verify_jurisdiction_reextract.py` |
| Gold deal fixtures (v1) | `data/jurisdictions/_gold_deals.yaml` |
| Regression tests | `apps/api/tests/test_jurisdiction_regression.py` |

**Acceptance:** ≥15 gold deals; regression tests pass on current engine; re-extract produces diff report for EU + US HSR.

**Note:** Gold deals are the highest-leverage manual curation step in the entire build (~2 hours of research). Everything else is automated.

---

### PR 6 — Staleness monitor
**Branch:** `jurisdiction-verification/staleness-monitor`  
**Size:** ~300 lines  
**Review focus:** Anchor source mapping, drift detection

| Deliverable | Path |
|-------------|------|
| Staleness script | `apps/api/scripts/monitor_jurisdiction_staleness.py` |
| Anchor config | `data/jurisdictions/_staleness_anchors.yaml` |
| Tests with mocked anchors | `apps/api/tests/test_monitor_jurisdiction_staleness.py` |

**Acceptance:** Detects injected drift in test fixture; US HSR anchor maps to FTC notice URL.

---

### PR 7 — Product integration (API + UI)
**Branch:** `jurisdiction-verification/product-integration`  
**Size:** ~400 lines  
**Review focus:** Confidence capping, UX clarity

| Deliverable | Path |
|-------------|------|
| Load sidecar in threshold engine | `apps/api/app/services/threshold_engine.py` |
| Verification tier in screening API | `apps/api/app/routers/jurisdictions.py` |
| Staleness/verification badges | `apps/web/src/app/screen/ScreenClient.tsx`, `jurisdictions/[id]/page.tsx` |
| TypeScript types | `apps/web/src/lib/types.ts` |

**Acceptance:** Screening results show verification tier; stale jurisdictions show yellow badge; low-tier nuance fields labeled as guidance.

---

### PR 8 — CI pipeline
**Branch:** `jurisdiction-verification/ci`  
**Size:** ~150 lines  
**Review focus:** What runs on every push vs nightly

| Deliverable | Path |
|-------------|------|
| GitHub Actions workflow | `.github/workflows/jurisdiction-verification.yml` |
| Orchestrator script | `apps/api/scripts/run_jurisdiction_verification.py` |

**CI tiers:**

| Trigger | Gates |
|---------|-------|
| Every push | Schema + completeness (offline) + gold deal regression |
| Nightly cron | Passage grounding (live fetch, subset) + staleness monitor |
| Manual / pre-release | Full 47-jurisdiction passage gate |

**Acceptance:** CI green on main; nightly job documented in workflow comments.

---

### Optional PR 9 (post-v1) — Adversarial agent loop

**Branch:** `jurisdiction-verification/adversarial-loop`  
Defer until PRs 1–8 ship. Automated red-team: proponent/skeptic/arbiter agents. Only needed for jurisdictions that fail gates repeatedly.

---

## PR summary table

| # | Branch | Est. lines | Depends on | Reviewer focus |
|---|--------|------------|------------|----------------|
| 1 | `scaffolding` | 400 | — | Models, sidecar format |
| 2 | `source-fetcher` | 500 | 1 | Text normalization |
| 3 | `passage-gate` | 700 | 2 | Core verification logic |
| 4 | `completeness-gate` | 450 | 1 | Archetype rules |
| 5 | `regression-suite` | 650 | 1, 3 | Gold deals + engine correctness |
| 6 | `staleness-monitor` | 300 | 2 | Drift detection |
| 7 | `product-integration` | 400 | 1–6 | UX + confidence |
| 8 | `ci` | 150 | 1–7 | Pipeline wiring |

**Total estimated:** ~3,550 lines across 8 PRs. At ~450 lines/PR average, each review should take 20–40 minutes.

---

## Implementation order & timeline

| Week | PRs | Outcome |
|------|-----|---------|
| 1 | PR 1, 2 | Foundation + source fetching |
| 2 | PR 3, 4 | First real verification results; YAML gap list |
| 3 | PR 5, 6 | Behavioral tests + staleness |
| 4 | PR 7, 8 | Product-facing confidence + CI |

After PR 3 lands, run passage gate against all 47 YAMLs and produce a **gap report** — jurisdictions failing tier 1/2 get targeted YAML fixes in separate small data PRs (not part of this build's code PRs).

---

## YAML remediation workflow (parallel track)

Verification gates will fail on many profiles initially. Fix data in dedicated PRs:

```
jurisdiction-verification/data-fix-eu
jurisdiction-verification/data-fix-us-hsr
jurisdiction-verification/data-fix-batch-emea
...
```

Each data-fix PR:
1. Addresses failures from gate report for named jurisdictions
2. Re-runs passage gate locally
3. Updates `last_verified` and sidecar
4. ≤5 jurisdiction files per PR for reviewability

---

## Testing strategy

| Level | What | Where |
|-------|------|-------|
| Unit | Text normalization, numeric extraction, model load | `apps/api/tests/` |
| Integration | Gate scripts against fixture YAML + fixture HTML | `apps/api/tests/` |
| Regression | Gold deals through threshold engine | `test_jurisdiction_regression.py` |
| Smoke | Manual run of full orchestrator on 3 jurisdictions | Pre-merge checklist |
| CI | Offline gates every push; live fetch nightly | GitHub Actions |

**No live network in default CI** — use fixtures. Nightly job handles live source fetch.

---

## Success criteria (v1 complete)

- [ ] All 47 jurisdictions pass tier 3 (completeness) in CI
- [ ] ≥35 jurisdictions pass tier 2 (passages + numbers) — remaining flagged explicitly
- [ ] Gold deal regression suite: 15+ deals, 100% pass rate
- [ ] US HSR staleness monitor detects 2026 threshold values
- [ ] Screening UI shows verification tier and staleness badge
- [ ] Orchestrator script runs all gates with single command
- [ ] No screening result shows `confidence: high` when jurisdiction tier < 2

---

## Explicit non-goals (v1)

- Manual lawyer review workflow
- Adversarial agent loop (PR 9 deferred)
- Automated YAML rewriting from re-extraction (report only)
- Full coverage of practitioner synthesis field verification
- Sector-specific carve-out completeness (flag as `coverage: partial` in sidecar)

---

## Commands reference (target state)

```bash
# Run all offline gates
python apps/api/scripts/run_jurisdiction_verification.py --offline

# Run passage gate for one jurisdiction
python apps/api/scripts/verify_jurisdiction_passages.py --jurisdiction uk --verbose

# Run completeness for all
python apps/api/scripts/verify_jurisdiction_completeness.py

# Run gold deal regression
pytest apps/api/tests/test_jurisdiction_regression.py -v

# Check staleness (live)
python apps/api/scripts/monitor_jurisdiction_staleness.py --annual-adjustment-only

# Existing URL check (tier 0)
python apps/api/scripts/verify_jurisdiction_urls.py
```

---

## Open questions for sign-off

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | Sidecar files committed to repo, or generated in CI only? | **Commit** — makes tier visible in PR diffs and powers UI offline |
| 2 | Block merge if any jurisdiction below tier 2? | **No** — block only on tier 0/1 failures in CI; show tiers in UI |
| 3 | Gold deals: who curates the initial 15? | **Bhavya** — 2h research using public filing announcements |
| 4 | Re-extraction: Gemini or Claude? | **Gemini** — consistent with chat intake; strict JSON schema |
| 5 | Run data-fix PRs before or after PR 7 (UI)? | **Before PR 7** — UI should reflect real tiers, not all-red |

---

## Sign-off

| Role | Name | Date | Approved |
|------|------|------|----------|
| Product / legal | | | ☐ |
| Engineering | | | ☐ |

Once signed off, start with **PR 1** on branch `jurisdiction-verification/scaffolding`.
