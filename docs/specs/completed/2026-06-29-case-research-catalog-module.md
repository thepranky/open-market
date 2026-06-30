# Spec: Case research catalog module (ROADMAP 5.2)

## Goal

Put canonical case records and indexed case records behind one case-research catalog module that owns list/search/filter policy, record-status labels, route targets, and search-hit projection. Before this change, canonical and indexed behavior is split across `case_service.py`, `index_case_service.py`, routers, search projection helpers, and frontend assumptions. After this change, routers and frontend calls keep the same public endpoints, but the canonical-vs-indexed policy lives in one testable module.

Out of scope:

- Merging `CaseRecord` and `CaseIndexEntry` into one Pydantic model.
- Moving YAML source of truth into Postgres.
- Changing semantic embedding generation or pgvector schema.
- Changing the visible frontend routes other than consuming unchanged response shapes from a cleaner backend.
- Automating `similar_cases`; that remains separate graph/search quality work.

## Approach

Create `app/cases/services/case_catalog.py` as the external seam for case-research discovery. It should hide loader choice and projection details behind a small interface:

```python
class CaseCatalog:
    def list(self, query: CatalogListQuery) -> list[CatalogRecord]: ...
    def get(self, case_id: str, *, include_indexed: bool = True) -> CatalogRecord | None: ...
    def search(self, query: CatalogSearchQuery) -> list[CaseSearchHit]: ...
    def project_hit(self, record: CatalogRecord) -> CaseSearchHit: ...
    def href_for(self, record: CatalogRecord) -> str: ...
```

`CatalogRecord` can be a small wrapper around either a `CaseRecord` or a `CaseIndexEntry`; it should not copy every field into a third domain model. The wrapper owns the shared metadata that route/search projection needs:

- `data_layer`: `canonical` or `indexed`
- `record_status`: `canonical_reviewed` or `indexed_metadata`
- canonical route target: `/cases/<id>`
- indexed route target: `/indexed-cases/<id>`
- common searchable text
- list/filter fields
- quality counts for canonical records

Refactor consumers in this order:

1. Move duplicate jurisdiction/sector/outcome/year filtering out of `cases.py` and `indexed_cases.py` into `CatalogListQuery`.
2. Move `_canonical_to_hit()` and `_indexed_to_hit()` out of `search.py` into the catalog.
3. Make `/search/all` call `CaseCatalog.search()` for keyword search across selected scopes.
4. Make `/search/semantic` keep using pgvector for ranking, then use the catalog to project rows into `CaseSearchHit`.
5. Keep `case_service.py` and `index_case_service.py` as loaders/cache helpers or fold their internals into the catalog if that removes duplication without growing the public interface.
6. Keep `apps/web/src/features/cases/api.ts` response types stable; frontend changes should be limited to using any newly returned `href` field only if the backend adds it.

Why not a repository abstraction? There is no second persistence adapter today. The useful seam is the product policy seam: what a record means to routes, search, and users when it is canonical versus indexed.

## Files

| File | Change |
|------|--------|
| `apps/api/app/cases/services/case_catalog.py` | New deep module for listing, filtering, record lookup, keyword search, hit projection, and href/status policy. |
| `apps/api/app/cases/services/case_service.py` | Keep as canonical loader/cache helper or reduce to catalog internals. Public behavior remains available if tests import it. |
| `apps/api/app/cases/services/index_case_service.py` | Keep as indexed loader/cache helper or reduce to catalog internals. Public behavior remains available if tests import it. |
| `apps/api/app/cases/routers/cases.py` | Delegate list/detail filtering and 404 lookup to the catalog. |
| `apps/api/app/cases/routers/indexed_cases.py` | Delegate list/detail filtering and detail projection to the catalog. |
| `apps/api/app/cases/routers/search.py` | Remove local hit projection helpers; use catalog keyword and projection methods. |
| `apps/api/app/cases/models/api_responses.py` | Add optional `href` to `CaseSearchHit` only if useful to remove frontend route guessing; keep existing fields stable. |
| `apps/web/src/features/cases/api.ts` | Keep endpoint wrappers stable; optionally use backend `href` in search callers if added. |
| `apps/web/src/lib/types.ts` | Mirror any additive `CaseSearchHit.href` field. |
| `apps/api/tests/test_case_catalog.py` | New direct tests for canonical/indexed filtering, duplicate case IDs, route targets, and hit projection. |
| Existing API tests | Keep `test_indexed_cases_api.py` and search-related tests green through public endpoints. |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest tests/test_case_catalog.py -v
.venv/bin/python -m pytest tests/test_indexed_cases_api.py -v
.venv/bin/python -m pytest tests/test_graph_neighborhood_api.py -v

# Public search contract still returns both layers with stable labels.
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
r = client.get("/search/all", params={"q": "google", "scope": "all"})
r.raise_for_status()
for hit in r.json()[:5]:
    assert hit["data_layer"] in {"canonical", "indexed"}
    assert "record_status" in hit
print("search/all catalog projection: OK")
PY

.venv/bin/ruff check \
  app/cases/services/case_catalog.py \
  app/cases/routers/cases.py \
  app/cases/routers/indexed_cases.py \
  app/cases/routers/search.py \
  tests/test_case_catalog.py
```

Expected results: endpoint response shapes remain backward compatible; new catalog tests cover the policy that was previously scattered across routers and services.

## Rollback

Restore router-local filtering and search projection helpers, remove `case_catalog.py`, and remove the catalog tests. Because endpoint shapes are preserved, rollback should not require frontend or data changes.
