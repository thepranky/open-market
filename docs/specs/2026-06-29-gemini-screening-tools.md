# Spec: Gemini-backed screening tools module (ROADMAP 4.11)

## Goal

Move Gemini-backed screening tools behind explicit modules and a small model adapter interface. Before this change, knowledge chat, conversational deal intake, and financial-document parsing live inside `jurisdictions.py` with prompts, model fallback, JSON recovery, file parsing, and API-key handling inline. After this change, the router maps HTTP to three tool modules, and those modules can be tested with a fake model adapter without calling Gemini.

Out of scope:

- Replacing Gemini or adding multi-provider routing.
- Rewriting prompts for product behavior beyond extracting them from the router.
- Adding auth, rate limiting, request logging, or abuse controls. Roadmap `8.4` still covers production rate limiting.
- Changing frontend UX or request/response contracts.
- Letting LLM output bypass `threshold_engine.py`; deterministic screening remains authoritative.

## Approach

Create a small LLM adapter seam because there are two justified adapters: production Gemini and a fake/in-memory adapter for tests.

```python
class JsonGenerationPort(Protocol):
    def generate_json(
        self,
        *,
        system_instruction: str,
        contents: list[ModelMessage],
        max_output_tokens: int,
        temperature: float,
        model_preferences: list[str],
    ) -> dict[str, Any]: ...
```

Production adapter:

- `GeminiJsonAdapter` reads `settings.google_api_key` / `GOOGLE_API_KEY`.
- Applies model preference fallback.
- Converts app messages to Gemini content objects.
- Strips markdown fences.
- Parses JSON and raises typed errors for unavailable model, invalid JSON, or missing API key.

Tool modules:

- `knowledge_chat_tool.py` owns jurisdiction context construction, citation section IDs, prompt text, and `_KnowledgeChatResponse` projection.
- `deal_intake_tool.py` owns the intake prompt, conversation shaping, ready-state parsing, and `ChatResponse` projection.
- `financial_extraction_tool.py` owns PDF/Excel/CSV text extraction, truncation policy, extraction prompt, and response validation.

File parsing should not be hidden inside the Gemini adapter. Keep it in the financial tool so adapter tests can verify input text and prompt behavior independently.

Router shape:

- `POST /jurisdictions/knowledge-chat`, `/jurisdictions/chat`, and `/jurisdictions/parse-financials` remain public endpoints.
- `routers/jurisdictions.py` constructs the tool with `GeminiJsonAdapter` and delegates.
- HTTP errors are mapped at the router edge from typed tool errors.

Why not one generic "LLM service" for every prompt? The three tools have different contracts and failure modes. The shared depth is model invocation and JSON recovery; the prompts and domain validation should stay with each tool.

## Files

| File | Change |
|------|--------|
| `apps/api/app/screening/llm/gemini_adapter.py` | Production `JsonGenerationPort` adapter with API-key lookup, model fallback, fence stripping, JSON parsing, and typed errors. |
| `apps/api/app/screening/llm/models.py` | Shared `ModelMessage`, adapter protocol, and typed error classes. |
| `apps/api/app/screening/tools/knowledge_chat_tool.py` | Move knowledge-chat prompt, context construction, citation parsing, and response projection here. |
| `apps/api/app/screening/tools/deal_intake_tool.py` | Move conversational intake prompt and response parsing here. |
| `apps/api/app/screening/tools/financial_extraction_tool.py` | Move upload text extraction, truncation, prompt, model call, and response validation here. |
| `apps/api/app/screening/models/screening_tools.py` | Move chat, knowledge-chat, and parse-financials request/response models if that keeps routers and tools clean. |
| `apps/api/app/screening/routers/jurisdictions.py` | Replace inline Gemini code with thin endpoint delegation to tool modules. |
| `apps/web/src/features/screening/api.ts` | No contract change expected; update only if response typing needs additive fields. |
| `apps/api/tests/test_screening_llm_adapter.py` | Unit tests for JSON extraction, fallback ordering, missing-key error, invalid JSON error. |
| `apps/api/tests/test_screening_tools.py` | Tool tests using a fake adapter for knowledge citations, intake ready parsing, and financial document parsing/truncation. |

## Verification

```bash
cd apps/api

.venv/bin/python -m pytest tests/test_screening_llm_adapter.py tests/test_screening_tools.py -v

# Existing deterministic screening tests should not start depending on Gemini.
.venv/bin/python -m pytest tests/test_jurisdiction_regression.py tests/test_jurisdiction_data_service.py -v

# Router smoke with missing API key should still return 503, not an import/runtime error.
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
r = client.post("/jurisdictions/chat", json={"messages": []})
assert r.status_code in {200, 503}
print("chat route import/error mapping: OK", r.status_code)
PY

.venv/bin/ruff check \
  app/screening/llm \
  app/screening/tools \
  app/screening/routers/jurisdictions.py \
  tests/test_screening_llm_adapter.py \
  tests/test_screening_tools.py
```

Expected results: tool tests exercise all Gemini-backed behavior without network calls; route smoke confirms the endpoint still maps missing configuration cleanly.

## Rollback

Move prompt strings and Gemini calls back into `routers/jurisdictions.py`, remove `app/screening/llm/` and `app/screening/tools/`, and delete the new adapter/tool tests. No data migration is involved.
