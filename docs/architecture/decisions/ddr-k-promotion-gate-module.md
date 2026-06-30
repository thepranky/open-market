# DDR-K: Promotion gate module

**Date:** 2026-06-29

## Decision

Promotion should be a deep module with CLI adapters, not two independent scripts that each remember part of the draft-to-canonical safety policy. The single-case runner and bulk runner should both use the same promotion gate implementation for canonical candidate construction, schema validation, source-link checks, source-integrity checks, semantic lint, conflict-report checks, and result reporting. The implementation spec is `docs/specs/2026-06-29-grounding-gates-bulk-promote-lane.md`.

## Context

Single-case promotion already runs deterministic safety gates before writing canonical YAML. The bulk lane currently discovers reviewed drafts and calls the lower-level transformer directly, so batch promotion can miss the safety envelope that protects one-off promotion. That split becomes riskier as Phase 5 moves from individual curated promotions to full-depth backlog promotion.

## Why this way

The deletion test is clear: if the promotion gate module is removed, draft eligibility, warning policy, conflict handling, canonical validation, quote grounding, semantic lint, and graph seeding rules reappear across multiple CLIs. Keeping those rules behind one interface gives callers leverage and keeps future gate changes local.

The lower-level `promote_draft_to_canonical.py` remains a transformer. It should not become the orchestration module because it should not need to know batch state, graph seeding, source-integrity policy, or conflict-report policy.

## Alternatives considered

- Keep single-case and bulk promotion separate. Rejected because the safety policy has already drifted.
- Route every bulk item through the single-case CLI. Rejected because batch promotion needs candidate temp roots, per-case artifacts, and one batch graph seed rather than per-case graph reseeding.
- Put all helpers in the bulk runner. Rejected because it would deepen only the bulk path and leave the single-case path with parallel policy.

## Consequences

- Promotion policy changes become easier to audit and test through one interface.
- CLI names can become thin adapters, with deprecated wrappers preserving old command paths.
- The module must distinguish product policy from operator policy: dry-run behavior, batch artifacts, and graph seeding stay explicit instead of hidden in the transformer.
