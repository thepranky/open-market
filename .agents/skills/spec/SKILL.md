---
name: spec
description: Turn a Meridian ROADMAP item into a spec file ready for implementation. Use when the user says "write a spec for", "spec out", "plan this", or names a ROADMAP item ID (like "5.12"). Always surface ambiguities and ask questions BEFORE writing — never spec something unclear. Invoke with /spec <roadmap-item-id-or-description>.
---

# spec

Translate a ROADMAP item into `docs/specs/YYYY-MM-DD-name.md` and, when the design decision itself matters, a DDR under `docs/architecture/decisions/`.

A spec is a contract between the person writing it and the person implementing it (who may be a fresh Claude instance with no context). It must be unambiguous enough that implementation requires no guesswork.

## Process

### Step 1 — Read the ROADMAP item

1. Open `ROADMAP.md` and find the item by ID (e.g. `5.12`) or keyword match
2. Read the full row: What, Files/areas, Why, How columns
3. Follow any cross-references to existing specs (`docs/specs/completed/`) or DDRs (`docs/architecture/decisions/`) mentioned in that row
4. Read `docs/specs/_template.md`; every new spec must follow that template exactly

### Step 2 — Read the code and surrounding docs

For every file or area the ROADMAP item mentions, read the current implementation. Understand:
- What the code does today
- What pattern you'd be extending or changing
- What adjacent code might be affected
- Which tests, docs, scripts, and callers define the current contract

### Step 3 — Do a design-fit review

Before writing the spec, check whether the proposed change fits the repo's current shape:
- Which existing module, helper, service, or script should own the behavior?
- What shared pattern should be reused instead of duplicating logic?
- What data flow or public contract changes, if any?
- What obvious alternative did you reject, and why is the chosen path simpler?
- What scope boundary keeps this to one coherent PR?

If multiple approaches are plausible, surface the tradeoff and ask before choosing.

### Step 4 — Decide whether a DDR is needed

Create or update a DDR at spec time when the change affects module boundaries, data contracts, source grounding, extraction/promotion pipeline behavior, orchestration, or shared abstractions.

Use `docs/architecture/decisions/README.md` conventions. A DDR records context, decision, alternatives, consequences, and enough of the current system map to explain why the repository works this way. It must not duplicate progress tracking, PR history, or verification logs. Reference the DDR from the spec when one is created or updated.

### Step 5 — Surface ambiguities before writing anything

Identify every unclear point:
- **Scope** — what exactly is in vs out?
- **Approach** — are there multiple valid implementations? Which is simpler?
- **Interface** — what do inputs and outputs look like?
- **Dependencies** — does anything else need to change first?
- **Decision record** — does this need a DDR, or does an existing DDR need to change?

State these explicitly and ask. Do not pick silently. Do not start writing the spec until you have answers.

### Step 6 — Write the spec

Copy `docs/specs/_template.md` to `docs/specs/YYYY-MM-DD-name.md` (today's date, kebab-case name matching the ROADMAP item). Keep the template sections exactly:

- `## Goal` — describe the before state, the goal state, why it matters, and what is explicitly out of scope.
- `## Approach` — describe the chosen design, why not the obvious alternative, key data flow, APIs, module ownership, and DDR link if applicable. Do not write a line-by-line implementation transcript.
- `## Files` — list files to create or modify with one-line purpose notes.
- `## Verification` — exact commands and manual checks that prove the spec is done, including expected output or "exits 0 with no errors".
- `## Rollback` — explain how to revert if wrong, unless rollback is obvious.

### Rules for a good spec

- **Describe what, not how.** No line-by-line code. The approach section describes logic and structure, not an implementation transcript.
- **No progress tracking.** The spec describes the goal state, not steps taken. Status lives in ROADMAP.md only.
- **Non-goals are explicit.** If something is adjacent but out of scope, name it in the `Goal` section as the template instructs.
- **Verification is runnable.** "It works" is not a verification step. A command with expected output is.
- **One spec per PR.** If the spec keeps growing, split it into two specs and two PRs.
