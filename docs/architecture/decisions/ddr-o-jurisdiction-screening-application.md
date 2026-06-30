# DDR-O: Jurisdiction screening application

**Date:** 2026-06-29

## Decision

Create a jurisdiction screening application module for deterministic screening workflows. The router should map HTTP to this module; the module should own catalog loading, request-to-deal adaptation, per-jurisdiction domestic fallback, threshold-engine orchestration, verification metadata joins, and response projection. `threshold_engine.py` remains the deep module for threshold evaluation itself. The implementation spec is `docs/specs/2026-06-29-jurisdiction-screening-application.md`.

## Context

`jurisdictions.py` mixes unrelated levels of abstraction: FastAPI routing, YAML loading, request adaptation, deterministic screening, verification sidecar joins, response projection, and Gemini-backed tools. Splitting files by endpoint would reduce file length but would not create a clear test surface for screening behavior.

## Why this way

The deep seam is the screening application interface. It gives tests and routers one place to exercise application behavior while preserving `screen_jurisdiction()` as the threshold-evaluation engine. The router becomes transport glue rather than the owner of screening policy.

## Alternatives considered

- Split `threshold_engine.py`. Rejected because the engine already hides substantial threshold logic behind a useful interface.
- Split `jurisdictions.py` into many routers only. Rejected because it preserves scattered application policy.
- Fold Gemini tools into the screening application. Rejected because LLM intake and deterministic threshold evaluation have different reliability and test contracts.

## Consequences

- Screening behavior can be tested without FastAPI.
- The deterministic path is separated from LLM tools, making production hardening easier.
- Existing endpoint contracts can stay stable while the internal module shape changes.
