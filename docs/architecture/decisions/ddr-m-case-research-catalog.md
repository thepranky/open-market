# DDR-M: Case research catalog

**Date:** 2026-06-29

## Decision

Put canonical and indexed case discovery behind a case research catalog module. The catalog owns list/filter/search policy, canonical-vs-indexed status labels, route targets, and search-hit projection, while `CaseRecord` and `CaseIndexEntry` remain separate data contracts. The implementation spec is `docs/specs/2026-06-29-case-research-catalog-module.md`.

## Context

Meridian exposes two case layers: canonical reviewed records in `data/cases/` and indexed metadata in `data/case_index/`. The public API and frontend need to search and navigate both, but the policy is currently scattered across loader services, routers, search helper functions, and frontend route assumptions.

## Why this way

The useful interface is not a persistence repository. YAML remains the source of truth and there is no second storage adapter to justify that seam. The useful interface is a product catalog: callers ask for case research records and get consistent data-layer labels, filters, route targets, and projections without relearning canonical-vs-indexed rules at every call site.

## Alternatives considered

- Merge canonical and indexed models. Rejected because indexed records are intentionally metadata-only and must not look source-grounded.
- Keep projection helpers in routers. Rejected because search, detail, graph, and frontend behavior can drift.
- Move all case data to Postgres first. Rejected because it changes the source-of-truth decision without solving the projection policy.

## Consequences

- Search and graph routes can share one interpretation of canonical and indexed records.
- The frontend can rely on stable `data_layer`, `record_status`, and optional `href` policy.
- Catalog tests become the main guard for user-visible case-layer behavior.
