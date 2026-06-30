# Spec: Graph neighborhood projection module (ROADMAP 4.4)

## Goal

Move graph node/edge schema, IDs, quality labels, hrefs, and canonical-vs-indexed projection rules into one graph projection module. Before this change, `/graph/neighborhood` builds UI graph responses in the router, `/graph/case` has a legacy Neo4j/YAML response shape, and `graph/seed_graph.py` repeats graph naming rules. After this change, YAML-derived graph responses and any Neo4j-backed graph responses adapt into the same projection contract.

Out of scope:

- Removing Neo4j entirely. The decision is to stop letting Neo4j define the public graph shape; retirement can happen later if the adapter remains unused.
- Redesigning the frontend graph UI.
- Adding automated `similar_cases` scoring.
- Changing graph data stored in YAML case records.
- Expanding graph depth beyond the current supported public behavior.

## Approach

Create `app/cases/services/graph_projection.py` as the module that owns public graph semantics:

```python
class GraphProjection:
    def neighborhood_for_record(
        self,
        record: CaseRecord | CaseIndexEntry,
        *,
        depth: int = 1,
        include_indexed: bool = True,
    ) -> GraphNeighborhoodResponse: ...
```

The projection module owns:

- Node ID construction (`case:<id>`, `authority:<name>`, `product_market:<id>`, etc.).
- Edge type constants (`DECIDED_BY`, `INVOLVES_PARTY`, `REFERENCES_CONCEPT`, etc.).
- `data_layer`, `record_status`, `quality_level`, `provenance`, and `href` policy.
- Deduplication of nodes and edges.
- Canonical and indexed record projection differences.
- A compatibility mapper from legacy Neo4j rows into `GraphNeighborhoodResponse` if `/graph/case` keeps attempting Neo4j first.

Refactor shape:

1. Move `_neighborhood_canonical()` and `_neighborhood_indexed()` out of `routers/graph.py`.
2. Make `/graph/neighborhood/{case_id}` look up the record through the case catalog, then call `GraphProjection`.
3. Either make `/graph/case/{case_id}` return the same `GraphNeighborhoodResponse` shape or keep its legacy response model behind an explicitly named compatibility function. Do not leave a second unlabeled graph schema in the router.
4. Move graph constants into a shared module used by both `graph_projection.py` and `graph/seed_graph.py`.
5. Keep `graph_service.py` as the Neo4j query adapter if Neo4j remains. It should return adapter-neutral data or be wrapped before response projection.
6. Keep `graph_entity_service.py` for aggregate entity endpoints unless projection constants remove duplicated labels there too.

Why not make Neo4j the source of truth? Case YAML and case-index YAML remain the reviewed source of truth; Neo4j is a derived optional store. The public graph interface should be testable without a running Neo4j container.

## Files

| File | Change |
|------|--------|
| `apps/api/app/cases/services/graph_projection.py` | New module for graph schema constants, node/edge builders, deduplication, and neighborhood projection. |
| `apps/api/app/cases/routers/graph.py` | Delegate neighborhood and legacy graph response construction to the projection module; keep HTTP errors in the router. |
| `apps/api/app/cases/services/graph_service.py` | Treat Neo4j as an adapter, not the response-shape owner. |
| `apps/api/app/cases/services/graph_entity_service.py` | Reuse graph constants where it emits graph-facing labels. |
| `apps/api/app/cases/models/api_responses.py` | Keep `GraphNode`, `GraphEdge`, and `GraphNeighborhoodResponse` as the public response models; add only backwards-compatible fields. |
| `graph/seed_graph.py` | Reuse graph constants/naming helpers so seed data and API projection cannot drift. |
| `apps/api/tests/test_graph_projection.py` | New direct tests for canonical projection, indexed projection, deduplication, hrefs, edge IDs, and quality labels. |
| `apps/api/tests/test_graph_neighborhood_api.py` | Keep endpoint-level coverage through public routes. |
| `apps/api/tests/test_graph_seed_models.py` | Update expected constants if graph seed helpers move. |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest tests/test_graph_projection.py -v
.venv/bin/python -m pytest tests/test_graph_neighborhood_api.py tests/test_graph_seed_models.py -v

# Public endpoint still serves a typed neighborhood without Neo4j.
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
r = client.get("/graph/neighborhood/eu_google_fitbit_2020")
if r.status_code != 404:
    r.raise_for_status()
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert data["source"] in {"yaml", "neo4j"}
print("graph neighborhood route: OK")
PY

.venv/bin/ruff check \
  app/cases/services/graph_projection.py \
  app/cases/routers/graph.py \
  app/cases/services/graph_service.py \
  graph/seed_graph.py \
  tests/test_graph_projection.py
```

Expected results: projection tests exercise the graph schema without Neo4j; endpoint tests remain green; graph seed still emits compatible node and relationship labels.

## Rollback

Move projection helpers back into `routers/graph.py`, restore `graph/seed_graph.py` local constants, and remove `graph_projection.py` plus its direct tests. No data migration is involved.
