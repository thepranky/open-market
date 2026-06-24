# DDR-G: Web frontend

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `apps/web/src/app/` — page routes (thin wrappers)
- `apps/web/src/features/cases/`, `features/screening/` — product UI + `api.ts`
- `apps/web/src/lib/api-client.ts`, `types.ts`
- `apps/web/src/components/NavBar.tsx`
- Key components: `Evidence.tsx`, `SemanticCaseCard.tsx`, `VerificationBadges.tsx`

Run: `npm run dev`; click through all nav routes.

## Agent prompt

> Map the Next.js frontend: every route, what API it calls, shared vs product-specific components. Explain `features/*/api.ts` and `lib/api-client.ts` type sharing. How do case research and screening appear in nav/UX? Compare feature-folder split vs prior flat layout. What's missing for production UX (loading, errors, auth shell)?

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
