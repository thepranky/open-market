# Design decision records

Short DDRs documenting why the system is built this way. Fill one per deep-dive session (~1 day each).

| Session | File | Topic |
|---------|------|-------|
| 0 | [ddr-0-repo-layout.md](ddr-0-repo-layout.md) | Monorepo + cases/screening packages (review before PR 1) |
| A | [ddr-a-data-contracts.md](ddr-a-data-contracts.md) | Pydantic models, YAML layout, source integrity |
| B | [ddr-b-extraction-pipeline.md](ddr-b-extraction-pipeline.md) | Draft → promote pipeline, scripts |
| C | [ddr-c-search-graph.md](ddr-c-search-graph.md) | Keyword + semantic search, graph, pgvector |
| D | [ddr-d-threshold-engine.md](ddr-d-threshold-engine.md) | Screening logic, DealParameters, tests |
| E | [ddr-e-jurisdiction-verification.md](ddr-e-jurisdiction-verification.md) | Verification tiers, gold deals, sidecars |
| F | [ddr-f-deal-intake-llm.md](ddr-f-deal-intake-llm.md) | Chat intake, parse-financials, knowledge-chat |
| G | [ddr-g-web-frontend.md](ddr-g-web-frontend.md) | Next.js pages, components, API client |
| H | [ddr-h-ci-validation.md](ddr-h-ci-validation.md) | PR CI, pytest, gates, what's not gated |
| I | [ddr-i-infrastructure.md](ddr-i-infrastructure.md) | Docker, Postgres, env, deploy path |

**Template:** each file has a "Before you start" reading list, an agent prompt, and blank DDR sections.

**Status:** fill `Status: draft | accepted` and `Date:` when done. Accepted DDRs are durable reference.
