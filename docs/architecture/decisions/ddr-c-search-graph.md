# DDR-C: Search, embeddings, and graph


## Before you start

Read/trace:
- `apps/api/app/cases/routers/search.py`, `graph.py`, `graph_entities.py`
- `apps/api/app/cases/services/semantic_search_service.py`, `embedding_service.py`, `graph_service.py`, `graph_entity_service.py`
- `apps/api/migrations/001_create_vector_schema.sql`
- `apps/api/scripts/cases/embeddings/index_embeddings.py`
- `apps/web/src/features/cases/explore/`, `features/cases/graph/`

Optional: `app/shared/core/neo4j_client.py`, `graph/seed_graph.py` (legacy path).

## Agent prompt

> Explain how case search works: keyword (YAML) vs semantic (pgvector). Walk through embedding generation and storage. Explain graph routes — Neo4j vs YAML fallback, and what `/graph/stats` actually counts. Cover indexed-cases vs canonical in search. Why Postgres for embeddings but not jurisdictions? Gaps: eval for search quality, Neo4j future.

---

## What it does

## Why this way

## Alternatives considered

## Gaps
