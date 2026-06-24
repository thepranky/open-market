# DDR-F: Deal-intake LLM

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `apps/api/app/routers/jurisdictions.py` — chat, knowledge-chat, parse-financials endpoints
- `apps/web/src/features/screening/components/ChatIntake.tsx` (skim structure: state, API calls)
- `apps/web/src/features/screening/components/JurisdictionChat.tsx`

Use `/screen` in browser; watch network tab for API calls.

## Agent prompt

> Explain the deal-intake LLM surface: `/jurisdictions/chat`, `parse-financials`, `knowledge-chat`. What does the LLM do vs what `threshold_engine` does deterministically? Trace ChatIntake.tsx state flow. Is this agentic? What would tool/contract design look like if we formalised tools? Security/cost gaps for production.

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
