# Documentation index

| Doc | Purpose |
|-----|---------|
| [architecture/overview.md](architecture/overview.md) | System map: two products, data flow, code layout |
| [architecture/case-research.md](architecture/case-research.md) | Case pipeline, search, graph |
| [architecture/jurisdiction-screening.md](architecture/jurisdiction-screening.md) | Threshold engine, verification, screen UI |
| [operations/ingestion.md](operations/ingestion.md) | Extraction pipeline stages and gates |
| [operations/promotion-checklist.md](operations/promotion-checklist.md) | Draft → canonical human workflow |
| [operations/hard-cases.md](operations/hard-cases.md) | Multi-pass extraction review |
| [operations/jurisdiction-verification.md](operations/jurisdiction-verification.md) | Jurisdiction verification tiers and gates |
| [data/source-integrity.md](data/source-integrity.md) | Quote/locator rules and enforcement |
| [specs/restructure-layout.md](specs/restructure-layout.md) | Repo layout restructure (completed 2026-06-24) |
| [architecture/decisions/](architecture/decisions/) | Design decision records (DDRs) |
| [ROADMAP.md](../ROADMAP.md) | Phased work plan to production |

**Data contracts (in repo):** `data/jurisdictions/_schema.md`, `_verification_schema.md`

**Agent onboarding:** root [`README.md`](../README.md), [`CLAUDE.md`](../CLAUDE.md), [`.cursor/rules/meridian.mdc`](../.cursor/rules/meridian.mdc)
