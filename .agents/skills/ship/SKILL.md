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

### Step 2 — Independent review

Spawn a **fresh reviewer in an isolated worktree/session**. Prefer the other agent family when available (Claude Sonnet reviewing Codex work, or Codex reviewing Claude work). The reviewer must be cold — no context from this session — so its judgment is uncorrelated with the implementation decisions already made.

Use a high-effort review for small/focused changes. Use max/deep effort for multi-file changes, schema changes, data changes, source grounding, or core extraction/promotion/screening logic.

The sub-agent prompt must be self-contained:

```
You are doing a code review for a Meridian PR. Meridian is a merger-case research tool
for competition lawyers in the open-market repo.

Core invariants:
- YAML is source of truth; Postgres is derived
- Drafts never auto-promote to data/cases/
- quote_snippet must be verbatim text at the stated page in the PDF

Steps:
1. Check out PR <number> in an isolated worktree/session.
2. Read the linked spec and any linked DDR.
3. Review the full PR diff against the spec.
4. Check for correctness bugs, invariant violations, scope creep, missing tests,
   missing docs/callers/compatibility surfaces, and weak verification.
5. Return all findings classified as:
   - BLOCKER (must fix before merge)
   - ADVISORY (valid but optional)
   - NOTED (informational only)

For each finding, include file+line and the reason it matters.

Spec scope reference:
<paste spec Goal + Approach sections>
```

If an independent review cannot run, stop and report that shipping is blocked. Do not substitute your own review as the independent review.

### Step 3 — Triage findings

For each finding from the sub-agent, decide and record your call:

| Finding | Decision | Reason |
|---|---|---|
| <finding> | Accept blocker / Accept advisory / Reject | <why> |

Report the triage to the user before making any changes: what you'll fix, what you'll defer, what you rejected and why.

### Step 4 — Fix blockers

Apply accepted blocker fixes to the branch. Keep fixes minimal — do not refactor or improve adjacent code. Fix advisories only when they are small, clearly valid, and do not broaden the PR.

```bash
git add <specific files>
git commit -m "fix: <brief description of what the review found>"
git push
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
4. If the spec references a DDR, confirm the DDR still matches the final implementation. If the implementation changed the decision, update the DDR before merging.
5. Commit:
   ```bash
   git add ROADMAP.md docs/specs/ docs/architecture/decisions/
   git commit -m "docs(<scope>): mark ROADMAP <id> done; archive spec (#N)"
   git push
   ```

### Step 6 — Final verification

Always verify the final PR state after all blocker fixes, ROADMAP edits, spec archive moves, and DDR edits:

```bash
git status --short --branch
gh pr view <number> --json isDraft,mergeStateStatus,mergeable,statusCheckRollup,headRefName,baseRefName,headRefOid
gh pr checks <number> --watch
gh pr diff <number>
```

Merge only if CI is green, the working tree is clean except for no intended local changes, the final diff is still scoped to the spec, and the independent review has no accepted unresolved blockers.

### Step 7 — Merge

Confirm with the user if anything unexpected came up during review.

```bash
gh pr ready <number>   # only if the PR is still a draft and all gates are green
gh pr merge <number> --squash --delete-branch
gh pr view <number> --json state,mergedAt,mergeCommit
git status --short --branch
git log --oneline -1
```

Use `--squash` to keep main history as one commit per feature.

## What this does NOT do

- Implement the feature — that's /implement
- Write the spec — that's /spec
- Run integrity checks independently — those run inside /implement pre-PR; if you're shipping a PR opened manually without /implement, run /integrity first
