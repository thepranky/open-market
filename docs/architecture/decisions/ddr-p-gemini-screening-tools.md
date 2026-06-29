# DDR-P: Gemini-backed screening tools

**Date:** 2026-06-29

## Decision

Move Gemini-backed screening tools behind tool modules and a small JSON-generation adapter. Knowledge chat, conversational deal intake, and financial-document parsing remain separate tools; they share only model invocation, fallback, JSON recovery, and typed error handling. The implementation spec is `docs/specs/2026-06-29-gemini-screening-tools.md`.

## Context

The screening router currently contains long prompts, Gemini model fallback loops, markdown-fence stripping, JSON parsing, file parsing, API-key lookup, and response projection. That makes the LLM behavior hard to test without network calls and keeps cost/error handling embedded in HTTP route functions.

## Why this way

There is a real adapter seam: production calls Gemini, tests use a fake generator. The deep module should not be a generic prompt bucket; each tool has its own domain contract and validation needs. Sharing only the model adapter keeps the interface small while making the behavior testable.

## Alternatives considered

- Keep LLM logic inline in routes. Rejected because prompts and parsing are substantial behavior, not transport glue.
- Build one generic LLM service that owns every prompt. Rejected because it would hide domain contracts and turn tool-specific validation into caller burden.
- Let LLM tools call the threshold engine directly or bypass it. Rejected because deterministic screening remains authoritative.

## Consequences

- LLM tool tests can run with fake model responses and no API key.
- Router code becomes smaller and error mapping becomes explicit.
- Production concerns such as rate limiting and auth remain separate roadmap items rather than being mixed into the module extraction.
