# Spec: Jurisdiction screening application module (ROADMAP 4.1)

## Goal

Create a jurisdiction screening application module so HTTP routes no longer own catalog loading, deal adaptation, screening orchestration, verification metadata joins, and response projection. Before this change, `jurisdictions.py` is a god-router: it loads YAML, adapts per-country domestic revenue/assets, calls `threshold_engine.py`, joins verification sidecars, builds API responses, and also hosts LLM tools. After this change, deterministic screening behavior sits behind one testable application interface, while `threshold_engine.py` remains focused on threshold evaluation.

Out of scope:

- Splitting `threshold_engine.py` merely because it is large. Its `screen_jurisdiction()` interface is already the right deep module for threshold evaluation.
- Moving Gemini-backed chat/intake/parse-financials endpoints; those are covered by `docs/specs/2026-06-29-gemini-screening-tools.md`.
- Changing threshold semantics, confidence labels, verification tier meanings, or YAML schemas.
- Changing frontend request/response shapes.
- Adding auth or rate limiting.

## Approach

Create `app/screening/services/screening_application.py` with a narrow interface:

```python
class ScreeningApplication:
    def list_jurisdictions(self) -> list[JurisdictionSummary]: ...
    def get_jurisdiction(self, jurisdiction_id: str) -> JurisdictionDetail: ...
    def get_passages(self, jurisdiction_id: str) -> list[dict]: ...
    def screen_all(self, request: ScreeningRequest) -> list[ScreeningResultResponse]: ...
    def screen_one(self, jurisdiction_id: str, request: ScreeningRequest) -> ScreeningResultResponse: ...
```

The module owns application-level policy:

- Loading rules and sidecars through `jurisdiction_data_service`.
- Mapping `ScreeningRequest` into `DealParameters`.
- Per-jurisdiction domestic revenue fallback from `by_country`.
- Per-jurisdiction asset overrides from `*_assets_by_country`.
- Calling `screen_jurisdiction()` for one or many rules.
- Joining verification metadata onto screening responses.
- Projecting `JurisdictionScreeningResult` into stable API response models.

Move API request/response models out of the router into `app/screening/models/screening_api.py`, or keep them in the router only if that avoids a shallow pass-through. The important rule is that tests can exercise the application module without FastAPI.

Refactor route shape:

- `routers/jurisdictions.py` keeps `APIRouter`, HTTP status mapping, and dependency construction.
- Deterministic endpoints (`GET /`, `GET /{id}`, `GET /{id}/passages`, `POST /screen`, `POST /screen/{id}`) delegate to `ScreeningApplication`.
- LLM endpoints remain temporarily in the router until the Gemini tools spec lands; do not mix them into this deterministic module.

Why not split by endpoint first? Endpoint splits alone keep the same policy scattered across smaller files. The deeper seam is the application interface that can be tested once and called by any router layout.

## Files

| File | Change |
|------|--------|
| `apps/api/app/screening/services/screening_application.py` | New module for deterministic jurisdiction catalog, deal adaptation, screening orchestration, verification join, and response projection. |
| `apps/api/app/screening/models/screening_api.py` | Move or define `ScreeningRequest`, `RevenueByScopeInput`, response models, and summary/detail response models if that makes the application testable. |
| `apps/api/app/screening/routers/jurisdictions.py` | Thin deterministic endpoints to call `ScreeningApplication`; keep HTTP exception mapping. |
| `apps/api/app/screening/services/jurisdiction_data_service.py` | Continue to own bundle/sidecar loading; adjust helper names only if the application needs clearer calls. |
| `apps/api/app/screening/services/threshold_engine.py` | No behavioral split; imported by the application module. |
| `apps/api/tests/test_screening_application.py` | New direct tests for per-country domestic fallback, asset override, verification metadata projection, one-vs-all screening, and not-found behavior. |
| Existing screening tests | Keep jurisdiction regression, data service, and threshold tests green. |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest tests/test_screening_application.py -v
.venv/bin/python -m pytest \
  tests/test_jurisdiction_data_service.py \
  tests/test_jurisdiction_regression.py \
  tests/test_jurisdiction_completeness.py \
  tests/test_jurisdiction_verification_model.py \
  -v

# Public deterministic screening route still works.
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
payload = {
    "acquirer": {"worldwide": 10000, "by_country": {"de": 1000}},
    "target": {"worldwide": 1000, "by_country": {"de": 100}},
    "revenue_currency": "EUR",
}
r = client.post("/jurisdictions/screen/de", json=payload)
r.raise_for_status()
data = r.json()
assert data["jurisdiction_id"] == "de"
assert "source_verification_tier" in data
print("screening route: OK")
PY

.venv/bin/ruff check \
  app/screening/services/screening_application.py \
  app/screening/models/screening_api.py \
  app/screening/routers/jurisdictions.py \
  tests/test_screening_application.py
```

Expected results: the application tests cover the policy formerly embedded in the router; public endpoint shapes remain stable.

## Rollback

Move request/response models and helper functions back into `routers/jurisdictions.py`, remove `screening_application.py`, and delete the direct application tests. No data changes are involved.
