# DDR-N: Graph neighborhood projection

**Date:** 2026-06-29

## Decision

Make graph neighborhood projection a first-class module that owns node IDs, edge types, quality labels, provenance, hrefs, deduplication, and canonical-vs-indexed projection. YAML and Neo4j are adapters into that public graph shape; Neo4j does not define the route contract. The implementation spec is `docs/specs/2026-06-29-graph-neighborhood-projection.md`.

## Context

The graph routes currently contain UI-oriented YAML projection, a legacy Neo4j response shape, and duplicated graph schema choices that also appear in `graph/seed_graph.py`. This makes the optional Neo4j path and the YAML fallback look like separate products instead of adapters behind one graph interface.

## Why this way

Graph behavior is user-facing presentation policy, not database policy. The stable interface should be `GraphNeighborhoodResponse`, which can be tested from YAML without running Neo4j. Keeping Neo4j as an adapter preserves optional graph-store work without letting derived infrastructure shape the API.

## Alternatives considered

- Remove Neo4j immediately. Rejected because the safer architectural move is to isolate it first; removal can follow if the adapter remains unused.
- Keep graph construction in the router. Rejected because schema and ID policy are too substantial for HTTP glue.
- Make `graph/seed_graph.py` the schema source. Rejected because seed scripts are derived-store adapters, not the public projection interface.

## Consequences

- Tests can assert graph shape directly without external services.
- Future Neo4j changes must adapt into the same response model.
- The same constants can be reused by projection and seed code, reducing silent graph-schema drift.
