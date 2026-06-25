# Jurisdiction screening architecture

Merger-control threshold profiles evaluated against deal parameters, with tiered
source verification and deal-intake chat.

## Data layout

| Path | Role |
|------|------|
| `data/jurisdictions/*.yaml` | `JurisdictionRule` profiles (~60 jurisdictions) |
| `data/jurisdictions/_schema.md` | Field reference |
| `data/jurisdictions/_archetypes.yaml` | Completeness rules by regime type |
| `data/jurisdictions/_gold_deals.yaml` | Regression deals for threshold engine |

## Backend

| Layer | Key files (under `apps/api/app/`) |
|-------|-----------|
| Contract | `screening/models/jurisdiction.py`, `jurisdiction_verification.py` |
| Engine | `screening/services/threshold_engine.py` (loads YAML inline) |
| Verification | `screening/services/jurisdiction_*.py`, `source_fetcher.py` |
| Router | `screening/routers/jurisdictions.py` |

## Threshold engine

`DealParameters` (revenues, shares, assets, flags) evaluated against each profile's
`threshold_tests`. Returns per-jurisdiction status, triggering test, gap-to-trigger, and
citations. Pure in-memory — no database.

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/jurisdictions/`, `/jurisdictions/{id}` | List/detail |
| GET | `/jurisdictions/{id}/passages` | Statutory quotes |
| POST | `/jurisdictions/screen` | Screen all jurisdictions |
| POST | `/jurisdictions/screen/{id}` | Screen one |
| POST | `/jurisdictions/chat` | Deal-intake LLM |
| POST | `/jurisdictions/knowledge-chat` | Threshold KB Q&A |
| POST | `/jurisdictions/parse-financials` | PDF/Excel extraction |

## Verification tiers

Orchestrator: `apps/api/scripts/screening/run_jurisdiction_verification.py`

| Tier | When | Gates |
|------|------|-------|
| `push` | PR / fast | Schema tests, completeness, gold-deal regression |
| `nightly` | Scheduled | + offline passages, staleness |
| `full` | Manual | Live passage fetch for all profiles |

See [operations/jurisdiction-verification.md](../operations/jurisdiction-verification.md).

## Frontend

| Route | Feature module |
|-------|----------------|
| `/jurisdictions`, `/jurisdictions/[id]` | `features/screening/components/` (`JurisdictionSidebar`, `VerificationBadges`, …) |
| `/screen` | `features/screening/components/` (`ScreenClient`, `ChatIntake`) |

Verification metadata (`source_verification_tier`, `freshness_status`, `regression_status`)
is surfaced in jurisdiction detail and screening results.
