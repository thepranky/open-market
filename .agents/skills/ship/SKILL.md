---
name: ship
description: Safely close out a Meridian PR: spawn a cold independent sub-agent reviewer on a different model, triage findings, fix blockers, update ROADMAP, archive the spec, then merge. Use when the user says "ship", "merge", "close this out", "review and merge", or "ship PR #N". Invoke with /ship [PR-number].
---

# ship

Close out a PR safely. The full sequence: independent review → triage → fix blockers → ROADMAP update → spec archive → merge.

This is the last step in the workflow chain: /spec → /implement → **ship**.

## Process

### Step 1 — Find the PR

If a PR number is given, use it. Otherwise detect the open PR on the current branch:
```bash
gh pr view --json number,title,headRefName,baseRefName,body
```

Read the full diff:
```bash
gh pr diff <number>
```

Also read the linked spec file (usually referenced in the PR body).

### Step 2 — Independent sub-agent review

Spawn a **fresh sub-agent** on a different model. The sub-agent must be cold — no context from this session — so its review is uncorrelated with the implementation decisions already made.

Use `haiku` model for speed on small-to-medium PRs; use `sonnet` for large diffs or changes to core pipeline logic.

The sub-agent prompt must be self-contained:

```
You are reviewing a PR for the Meridian project (open-market repo).
Meridian is a merger-case research tool for competition lawyers.
Core invariants: YAML is source of truth; drafts never auto-promote to data/cases/;
quote_snippet must be verbatim text at the stated page in the PDF.

Spec this PR implements: <paste spec Goal + Approach sections>
PR diff: <paste full diff>

Review for:
1. Correctness bugs — wrong logic, off-by-one, broken edge cases
2. Contract violations — the three invariants above
3. Scope creep — anything beyond what the spec requires
4. Missing verification — do the stated test/check commands actually exercise the change?

For each finding: state file+line, describe the problem, and classify as:
- BLOCKER (must fix before merge)
- ADVISORY (valid but optional; small enough to fix now or worth noting for later)
- NOTED (informational only)
```

### Step 3 — Triage findings

For each finding from the sub-agent, decide and record your call:

| Finding | Decision | Reason |
|---|---|---|
| <finding> | Accept blocker / Accept advisory / Reject | <why> |

Report the triage to the user before making any changes: what you'll fix, what you'll defer, what you rejected and why.

### Step 4 — Fix blockers

Apply accepted blocker fixes to the branch. Keep fixes minimal — do not refactor or improve adjacent code.

```bash
git add <specific files>
git commit -m "fix: <brief description of what the review found>"
git push
```

Wait for CI to pass:
```bash
gh pr checks <number> --watch
```

### Step 5 — ROADMAP update and spec archive

1. Find the ROADMAP row this PR closes (match on spec title or ROADMAP item ID from the PR)
2. Mark it done and record the PR number:
   ```
   | ✅ 5.X | <What> | <Files> | <Why> | ✅ Done (#N) — <one-line summary of what was built> |
   ```
3. Move the spec to the completed folder:
   ```bash
   mv docs/specs/<spec-filename>.md docs/specs/completed/<spec-filename>.md
   ```
4. Commit:
   ```bash
   git add ROADMAP.md docs/specs/
   git commit -m "docs(<scope>): mark ROADMAP <id> done; archive spec (#N)"
   git push
   ```

### Step 6 — Merge

Confirm with the user if anything unexpected came up during review.

```bash
gh pr merge <number> --squash --delete-branch
```

Use `--squash` to keep main history as one commit per feature.

## What this does NOT do

- Implement the feature — that's /implement
- Write the spec — that's /spec
- Run integrity checks independently — those run inside /implement pre-PR; if you're shipping a PR opened manually without /implement, run /integrity first
