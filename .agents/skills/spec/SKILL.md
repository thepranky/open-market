---
name: spec
description: Turn a Meridian ROADMAP item into a spec file ready for implementation. Use when the user says "write a spec for", "spec out", "plan this", or names a ROADMAP item ID (like "5.12"). Always surface ambiguities and ask questions BEFORE writing — never spec something unclear. Invoke with /spec <roadmap-item-id-or-description>.
---

# spec

Translate a ROADMAP item into `docs/specs/YYYY-MM-DD-name.md`.

A spec is a contract between the person writing it and the person implementing it (who may be a fresh Claude instance with no context). It must be unambiguous enough that implementation requires no guesswork.

## Process

### Step 1 — Read the ROADMAP item

1. Open `ROADMAP.md` and find the item by ID (e.g. `5.12`) or keyword match
2. Read the full row: What, Files/areas, Why, How columns
3. Follow any cross-references to existing specs (`docs/specs/completed/`) or DDRs (`docs/architecture/decisions/`) mentioned in that row

### Step 2 — Read the code

For every file or area the ROADMAP item mentions, read the current implementation. Understand:
- What the code does today
- What pattern you'd be extending or changing
- What adjacent code might be affected

### Step 3 — Surface ambiguities before writing anything

Identify every unclear point:
- **Scope** — what exactly is in vs out?
- **Approach** — are there multiple valid implementations? Which is simpler?
- **Interface** — what do inputs and outputs look like?
- **Dependencies** — does anything else need to change first?

State these explicitly and ask. Do not pick silently. Do not start writing the spec until you have answers.

### Step 4 — Write the spec

Create `docs/specs/YYYY-MM-DD-name.md` (today's date, kebab-case name matching the ROADMAP item).

```markdown
# Spec: <title> (ROADMAP <id>)

## Goal

One paragraph. What will exist after this change that doesn't exist now, and why it matters.
Include the "before" state to make the problem concrete.

## Out of scope

Explicit list of what this spec does NOT cover. Prevents scope creep during implementation.

## Approach

### <Logical section heading>

Detailed description of the change. For code changes: show the key function signatures,
data flow, and logic. For new files: show the module structure and what goes where.
Be specific enough that implementation requires no guesswork.

**Files to change:**
- `path/to/file.py` — what changes and why (one line each)

## Verification

Concrete commands to run after implementation. These become the checklist for /implement and /ship.

```bash
cd apps/api
.venv/bin/python scripts/...
```

Expected output (or "exits 0 with no errors").
```

### Rules for a good spec

- **Describe what, not how.** No line-by-line code. The approach section describes logic and structure, not an implementation transcript.
- **No progress tracking.** The spec describes the goal state, not steps taken. Status lives in ROADMAP.md only.
- **Non-goals are explicit.** If something is adjacent but out of scope, name it in "Out of scope".
- **Verification is runnable.** "It works" is not a verification step. A command with expected output is.
- **One spec per PR.** If the spec keeps growing, split it into two specs and two PRs.
