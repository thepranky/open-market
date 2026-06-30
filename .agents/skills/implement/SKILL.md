---
name: implement
description: Implement a Meridian spec end-to-end: read the spec, clarify any ambiguities, implement surgically, run integrity and verification gates, then open a PR ready for /ship. Use when the user says "implement this spec", "build this", "do it", or points to a spec file. Invoke with /implement <spec-file-or-name>.
---

# implement

Take a spec from `docs/specs/` and implement it. Produce a PR that is ready for `/ship`.

## Process

### Step 1 — Read the spec and the code

1. Find and read the full spec file (search `docs/specs/` by name or keyword)
2. Read every file listed in the spec's `Files` section — understand the current code before touching it
3. Read any DDRs cross-referenced in the spec
4. Read nearby tests, docs, scripts, and callers needed to understand the contract being changed

### Step 2 — Sanity-review the spec before coding

Before editing, challenge the spec against live code:
- Does it still match the current implementation and roadmap state?
- Does it reuse the existing owner module/helper/service instead of duplicating logic?
- Does it preserve the repo's product boundaries and source-of-truth rules?
- Are required callers, tests, docs, CLI wrappers, or compatibility surfaces missing from `Files`?
- Are the verification commands sufficient for the touched areas?
- If the change affects module boundaries, source grounding, pipeline orchestration, data contracts, or shared abstractions, is the DDR present or updated?

If the spec is stale, incomplete, or points at the wrong design, stop and ask with the smallest correction you recommend. Do not silently implement a different plan.

### Step 3 — Clarify before coding

If anything in the spec is ambiguous after reading the code, stop and ask:
- State the ambiguity precisely
- Give your interpretation and ask whether it's correct
- Wait for confirmation before proceeding

Do not implement around ambiguity. Do not make silent judgment calls. The spec is the contract — if it's unclear, surface it.

### Step 4 — Implement

Follow the spec exactly. Apply the CLAUDE.md surgical-changes rules:
- Touch only what the spec requires — every changed line should trace back to the spec
- Match the style of surrounding code; no reformatting of untouched lines
- No unrequested features, abstractions for single-use code, or "while I'm here" improvements
- If you notice something adjacent that should change, flag it as a separate ROADMAP item — do not fold it into this PR

### Step 5 — Run gates

Run every gate that matches the files touched, then run the spec's own verification commands. Record actual output for the PR body.

Keep broad gate output compact. Use verbose output for targeted tests when it is useful, but run full suites with quiet output or redirect the full log to a temp file and include only the final summary/tail in the PR body. Avoid streaming thousands of passing test lines into context.

**If `data/cases/` was touched — run full integrity check (`/integrity`):**
```bash
cd apps/api
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/lint_case_semantics.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/check_source_links.py
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir ../../data/cases
```

**If `data/case_index/` was touched:**
```bash
cd apps/api
.venv/bin/python scripts/cases/discovery/validate_case_index.py --index-dir ../../data/case_index
```

**If `data/jurisdictions/` or screening verification logic was touched:**
```bash
cd apps/api
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
```

**If `apps/api/` code was touched:**
```bash
cd apps/api
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -q
```

**If `apps/web/` code was touched:**
```bash
cd apps/web
npm run lint
npm run build
```

For mixed changes, run each relevant block. If a command cannot run because of the local environment, record the exact failure and say whether it blocks the PR.

**Always — run the verification commands from the spec itself.**

### Step 6 — Open a draft PR

Stage and commit:
```bash
git add <specific files — never git add -A or git add .>
git commit -m "<type>(<scope>): <what changed>"
git push -u origin <branch-name>
```

Open the PR:
```bash
gh pr create --draft --title "<concise title under 70 chars>" --body "$(cat <<'EOF'
## What

<one sentence: what this PR does>

Spec: docs/specs/<filename>.md (ROADMAP <id>)

## Verification run

<paste the actual output of each verification command>

## Notes for reviewer

<any tradeoffs, deferred items, or things to pay attention to>
EOF
)"
```

## What this does NOT do

- Write the spec — that's /spec
- Review, clean up ROADMAP, or merge — that's /ship
- Run overnight bulk data jobs — those need caffeinate + nohup (see project memory)
