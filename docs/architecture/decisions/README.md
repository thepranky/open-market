# Design decision records

Short DDRs documenting **why** the system is built this way. Fill one per deep-dive session (~1 day each).

| Session | File | Topic |
|---------|------|-------|
| 0 | [ddr-0-repo-layout.md](ddr-0-repo-layout.md) | Monorepo + cases/screening packages |
| A | [ddr-a-data-contracts.md](ddr-a-data-contracts.md) | Pydantic models, YAML layout, source integrity |
| B | [ddr-b-extraction-pipeline.md](ddr-b-extraction-pipeline.md) | Draft → promote pipeline, scripts |
| C | [ddr-c-search-graph.md](ddr-c-search-graph.md) | Keyword + semantic search, graph, pgvector |
| D | [ddr-d-threshold-engine.md](ddr-d-threshold-engine.md) | Screening logic, DealParameters, tests |
| E | [ddr-e-jurisdiction-verification.md](ddr-e-jurisdiction-verification.md) | Verification tiers, gold deals, sidecars |
| F | [ddr-f-deal-intake-llm.md](ddr-f-deal-intake-llm.md) | Chat intake, parse-financials, knowledge-chat |
| G | [ddr-g-web-frontend.md](ddr-g-web-frontend.md) | Next.js pages, components, API client |
| H | [ddr-h-ci-validation.md](ddr-h-ci-validation.md) | PR CI, pytest, gates, what's not gated |
| I | [ddr-i-infrastructure.md](ddr-i-infrastructure.md) | Docker, Postgres, env, deploy path |
| J | [ddr-j-dual-extraction.md](ddr-j-dual-extraction.md) | Dual extraction: align/diff two cold extractions, calibration gate |

## Conventions

**Progress lives in [`ROADMAP.md`](../../ROADMAP.md).** Do not duplicate status, “next steps”, or completion dates in DDRs or specs.

**DDRs record decisions only:**

- Context and the decision taken
- Why this way (not just what)
- Alternatives considered
- Consequences (trade-offs, risks)
- Optional: **Gaps** discovered during the deep-dive (add follow-up rows to ROADMAP when you act on them)

**Do not put in DDRs:** implementation checklists, PR history, “verified” test counts, doc-sync tables, or session completion status. Link to a dated spec under `docs/specs/` when the *how* matters.

**Templates (A–I):** each file has a “Before you start” reading list, an agent prompt, and blank decision sections to fill after the session.

**Specs vs DDRs:**

| | Spec (`docs/specs/`) | DDR (`docs/architecture/decisions/`) |
|--|----------------------|--------------------------------------|
| Question | What to build / move? | Why this shape? |
| Updates when | At planning time; archive when done | Rarely — only if the decision changes |
