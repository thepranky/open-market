# Spec: Grounding gates on the bulk promote lane (ROADMAP 5.17)

## Goal

Bulk promotion must not write canonical case YAML until the promoted candidate has
passed the same batch-safe data gates that the single-case promotion path runs today.
Before this change, `bulk_promote_pass.py` scans reviewed market-definition drafts
and calls `promote_draft_to_canonical.py` directly; a draft with a real-looking but
unfindable quote can be promoted at volume. After this change, the bulk lane first
builds a canonical candidate in a temporary cases tree, runs case-scoped schema,
link, grounding, semantic, and conflict checks against that candidate, blocks on
any data-gate failure, records the per-case outcome in `data/batch_runs/`, and only
then writes the real canonical YAML.

Out of scope:
- Changing `check_source_integrity.py` issue levels or global exit-code behavior.
  The bulk lane parses its summary and treats warnings as blocking locally.
- Routing bulk promotion through the single-case pipeline. The bulk runner needs
  case-scoped candidate gates and batch-level state, not per-case graph reseeding.
- Repairing bad quotes, URLs, pages, support references, or review packets.
- Automating conflict resolution or human sign-off for dual-extraction reports.
- Running extraction or review-readiness checks during promotion.

## Approach

### Keep bulk promotion as the batch driver

`run_bulk_promotion.py` remains the queue runner. It owns jurisdiction filtering,
`--max`, `--overwrite`, `--min-markets`, dry-run behavior, skip counters, and the
per-case batch artifact. This is deliberately different from `run_case_promotion.py`,
which is a single-case orchestration command.

The batch script should still use `promote_draft_to_canonical.py` for canonicalization;
it must not duplicate draft-to-canonical transformation logic.

Bulk promotion should have the same data-safety envelope as single-case promotion,
but not the same execution shape:

- Candidate schema, source links, source integrity, semantic lint, and resolved-conflict
  gates run per case against a temporary cases tree before the real write.
- Graph seeding runs once after the batch if at least one real canonical file was
  written, because per-case graph reseeding would be slow and redundant.
- Review-readiness and extraction are not promotion gates; they remain upstream human
  sign-off/extraction concerns.

### Candidate discovery supports market-definition and full-depth drafts

Add a `--draft-kind` option:

```
--draft-kind {market-definition,full-depth,all}
```

Default: `market-definition`, preserving current behavior.

Discovery rules:

- `market-definition` scans `data/drafts/<jur>/*.market_definition.draft.yaml`.
  The review artifact is `<case_id>.market_definition.review.md`; existing
  `review_status()` parsing remains valid.
- `full-depth` scans both `*.e2e.merged.draft.yaml` and `*.merged.draft.yaml`.
  The review artifact is `<case_id>.e2e.review_packet.md` if present, otherwise
  `<case_id>.review_packet.md`. Parse `## Readiness: PASS|WARN|FAIL`.
- `all` includes both sets. If the same `case_id` appears in both sets, prefer the
  full-depth merged draft and suppress the market-definition candidate.

Promotable review states:

- Market-definition drafts: existing `PASS`, `WARNINGS`, and `PASS ...` statuses.
- Full-depth drafts: `PASS` and `WARN`.

Missing or non-promotable review artifacts are skipped before any gate work and
recorded as `skipped_status`.

The existing `--min-markets` filter still applies to the selected draft path. It is
valid for full-depth drafts because they include the market-definition slice.

### Gate against a temporary canonical candidate

For each promotable candidate:

1. If the real canonical record already exists and `--overwrite` is not set, record
   `skipped_exists` and do not build or gate a candidate.
2. Create a temporary cases root with the same jurisdiction layout:

   ```
   <tmp>/cases/<jur>/<case_id>.yaml
   ```

3. Run `promote_draft_to_canonical.py` once with `--output` pointing at that temporary
   YAML:

   ```
   <python> apps/api/scripts/cases/promote/promote_draft_to_canonical.py \
     --case-id <case_id> \
     --draft <draft_path> \
     --output <tmp>/cases/<jur>/<case_id>.yaml
   ```

   If `--overwrite` is set on the bulk command, it affects only the later real write;
   the temporary output is new and does not need `--overwrite`.

4. Run canonical schema validation against the temporary cases root:

   ```
   <python> apps/api/scripts/cases/integrity/validate_cases.py \
     --cases-dir <tmp>/cases
   ```

   `promote_draft_to_canonical.py` already validates the candidate before writing it,
   but keeping this explicit gate preserves parity with the single-case path and makes
   the batch artifact complete.

5. Run source-link liveness against the temporary cases root, scoped to the case:

   ```
   <python> apps/api/scripts/cases/integrity/check_source_links.py \
     --cases-dir <tmp>/cases \
     --case-id <case_id>
   ```

   Add `--cases-dir` and `--case-id` to `check_source_links.py`. Defaults preserve
   current behavior (`data/cases`, all cases). The existing court-opinion case-page
   warning remains non-blocking; broken authoritative links block.

6. Run source integrity against the temporary cases root, scoped to the case:

   ```
   <python> apps/api/scripts/cases/integrity/check_source_integrity.py \
     --cases-dir <tmp>/cases \
     --case-id <case_id> \
     --no-cache
   ```

   Parse the final `Total: ... <N> error(s), <M> warning(s)` line. Any error or
   warning blocks promotion. This mirrors `run_case_promotion.check_draft_integrity()`
   and is intentional because quote-not-found, wrong-page, and possible hallucination
   outcomes are warnings today.

7. Run semantic lint against the temporary cases root, scoped to the case:

   ```
   <python> apps/api/scripts/cases/integrity/lint_case_semantics.py \
     --cases-dir <tmp>/cases \
     --case-id <case_id>
   ```

   Any non-zero exit blocks promotion.

8. Run the dual-extraction conflict gate where conflict reports exist.

   Reuse `run_case_promotion.unresolved_conflicts(report_path)`. For each adjacent
   conflict report matching `<case_id>.*.conflicts.yaml`, require every conflict to
   have a non-empty `resolution`. If no conflict reports exist, record the gate as
   `skipped_no_reports` rather than blocking; legacy market-definition drafts and
   manually merged drafts must not break. For the full-depth promotion drives, the
   batch artifact will make missing conflict reports visible.

9. If all gates pass, copy the already-gated temporary canonical YAML to the real
   output path:

   ```
   data/cases/<jur>/<case_id>.yaml
   ```

   Copying the gated candidate avoids running canonicalization twice and guarantees
   the written record is exactly what passed the gates.

Failure categories:

- `candidate_error` — temp canonicalization failed.
- `blocked_schema` — candidate schema validation failed.
- `blocked_source_links` — source-link liveness failed.
- `blocked_source_integrity` — source integrity returned errors, warnings, or an
  unparsable non-zero result.
- `blocked_semantic_lint` — semantic lint returned non-zero.
- `blocked_conflicts` — at least one adjacent conflict report has unresolved conflicts.
- `promotion_error` — the final real write failed.
- `promoted` — candidate passed gates and real canonical YAML was written.

After the loop, if at least one case was promoted, run graph seeding once:

```
<python> graph/seed_graph.py
```

Add `--skip-graph-seed` for offline/test runs. If graph seeding fails, do not roll back
written YAML. Record `graph_seed.status=failed`, return non-zero, and print the last
meaningful failure line so the operator can rerun seeding after fixing Neo4j.

`--dry-run` remains queue-only: it reports candidates that would be gated/promoted but
does not create temporary candidates, run network integrity checks, write canonical
YAML, or write a batch-run artifact.

### Record per-case grounding outcome

Add `--run-id`; default is `bulk_promote_<YYYYMMDD_HHMMSS>`. Non-dry runs write after
each candidate to:

```
data/batch_runs/<run_id>.json
```

Schema:

```json
{
  "run_id": "bulk_promote_20260629_120000",
  "created_at": "2026-06-29 19:00 UTC",
  "last_updated": "2026-06-29 19:04 UTC",
  "command": "...",
  "jurisdiction": "eu",
  "draft_kind": "full-depth",
  "cases": {
    "eu_example_2024": {
      "status": "promoted",
      "draft_path": "data/drafts/eu/eu_example_2024.e2e.merged.draft.yaml",
      "draft_kind": "full-depth",
      "review_status": "PASS",
      "source_integrity": {
        "status": "pass",
        "errors": 0,
        "warnings": 0
      },
      "source_links": {
        "status": "pass"
      },
      "semantic_lint": {
        "status": "pass"
      },
      "conflict_gate": {
        "status": "pass",
        "reports_checked": 3
      },
      "output_path": "data/cases/eu/eu_example_2024.yaml",
      "timestamp": "2026-06-29 19:04 UTC",
      "message": "promoted after grounding gates"
    }
  }
}
```

For skipped cases, gate objects are omitted or marked `skipped`; `message` explains
the skip reason. For blocked cases, include the last meaningful stderr/stdout line and
the source-integrity counts when available.

The terminal summary should add the new categories while preserving existing counters:

```
Done. promoted=12  skipped_status=3  skipped_exists=4  skipped_markets=1
      blocked_schema=0  blocked_source_links=1  blocked_source_integrity=2
      blocked_semantic_lint=1  blocked_conflicts=1  errors=0
Graph seed: PASS
Batch artifact: data/batch_runs/bulk_promote_20260629_120000.json
```

### Rename promotion runner scripts with compatibility wrappers

Rename the orchestration scripts to consistent verb-noun `run_*` names:

| Current path | New path | Compatibility behavior |
|---|---|---|
| `apps/api/scripts/cases/promote/promote_case_pipeline.py` | `apps/api/scripts/cases/promote/run_case_promotion.py` | Old file remains as a thin wrapper that prints a deprecation warning to stderr and delegates to `run_case_promotion.main()`. It re-exports public helpers such as `check_draft_integrity`, `find_merged_draft`, and `unresolved_conflicts` so existing tests/imports keep working. |
| `apps/api/scripts/cases/promote/bulk_promote_pass.py` | `apps/api/scripts/cases/promote/run_bulk_promotion.py` | Old file remains as a thin wrapper that prints a deprecation warning to stderr and delegates to `run_bulk_promotion.main()`. It re-exports public helpers such as `review_status`, candidate discovery, and gate parsers. |

Do not rename `promote_draft_to_canonical.py` in this spec. It is a lower-level
transformer rather than a runner, and the name is already precise enough to avoid
confusion.

Update active command references to the new names:

- `docs/operations/promotion-checklist.md`
- `docs/architecture/overview.md`
- `docs/architecture/case-research.md`
- `docs/architecture/decisions/ddr-b-extraction-pipeline.md`
- `docs/architecture/decisions/ddr-j-dual-extraction.md`
- `apps/api/scripts/cases/extract/run_e2e_extraction.py` summary text
- `apps/api/scripts/cases/review/check_review_readiness.py` promotion recommendation
- `apps/api/scripts/cases/extract/run_controlled_case.py` printed promotion commands

Completed specs under `docs/specs/completed/` are historical and do not need bulk
rewrites. If a live grep check is added during implementation, it should exclude
completed specs or only require active docs/runtime messages to use the new names.

### Testable helpers

Factor small helpers inside `run_bulk_promotion.py` so tests can cover the behavior
without shelling out to real network checks:

- `discover_candidates(drafts_dir, jurisdiction, draft_kind) -> list[Candidate]`
- `parse_full_depth_readiness(packet_path) -> str`
- `parse_source_integrity_counts(output) -> tuple[int, int] | None`
- `build_temp_candidate(candidate, temp_cases_dir, ...) -> Path`
- `run_grounding_gates(case_id, temp_cases_dir) -> GateResult`
- `run_conflict_gate(candidate) -> GateResult`
- `write_batch_state(state, runs_dir, run_id) -> Path`

Also add optional `--drafts-dir`, `--cases-dir`, and `--batch-runs-dir` arguments with
current repo defaults. These keep integration tests isolated in `tmp_path` and do not
change normal CLI usage.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/cases/promote/run_bulk_promotion.py` | New primary bulk runner: candidate discovery for full-depth drafts, temp-canonical gate flow, schema/source-link/source-integrity/semantic/conflict gates, batch artifact writing, one final graph seed, and testable helpers. |
| `apps/api/scripts/cases/promote/bulk_promote_pass.py` | Compatibility wrapper for the old command/import path; prints deprecation warning and delegates to `run_bulk_promotion.py`. |
| `apps/api/scripts/cases/promote/run_case_promotion.py` | New primary single-case runner, moved from `promote_case_pipeline.py` with imports and subprocess references updated to new names. |
| `apps/api/scripts/cases/promote/promote_case_pipeline.py` | Compatibility wrapper for the old command/import path; prints deprecation warning and delegates to `run_case_promotion.py`. |
| `apps/api/scripts/cases/integrity/check_source_links.py` | Add `--cases-dir` and `--case-id` while preserving existing default all-cases behavior. |
| `apps/api/tests/test_run_bulk_promotion.py` | New/renamed tests for discovery modes, full-depth readiness parsing, duplicate full-depth preference, all blocking gates, no real write on gate failure, dry-run no gates, graph seeding once, and batch artifact contents. |
| `apps/api/tests/test_run_case_promotion.py` | Renamed single-case promotion tests importing the new module name. |
| `apps/api/tests/test_promotion_script_compat.py` | New smoke tests that old script paths and old import paths still delegate and emit deprecation warnings. |
| Active docs/runtime messages listed above | Replace `promote_case_pipeline.py` and `bulk_promote_pass.py` command examples with `run_case_promotion.py` and `run_bulk_promotion.py`; mention old names as deprecated aliases only where helpful. |
| `data/batch_runs/<run_id>.json` | Runtime artifact only; generated by non-dry bulk runs, not required in the implementation PR unless an intentional smoke artifact is added. |

## Verification

```bash
cd apps/api

# New focused tests for the batch lane.
.venv/bin/python -m pytest tests/test_run_bulk_promotion.py -v

# Existing single-case promotion tests should remain green.
.venv/bin/python -m pytest tests/test_run_case_promotion.py -v

# Backwards-compatible old names still work.
.venv/bin/python -m pytest tests/test_promotion_script_compat.py -v

# Source-integrity parser behavior should still match the current CLI output,
# and source-link checks should support --cases-dir / --case-id.
.venv/bin/python -m pytest tests/test_source_integrity.py -v
.venv/bin/python -m pytest tests/test_check_source_links.py -v

# Dry-run over the current full-depth candidates: no canonical writes, no network gates.
.venv/bin/python scripts/cases/promote/run_bulk_promotion.py \
  --jurisdiction us \
  --draft-kind full-depth \
  --dry-run \
  --max 5

# Deprecated old command still delegates without changing behavior.
.venv/bin/python scripts/cases/promote/bulk_promote_pass.py \
  --jurisdiction us \
  --draft-kind full-depth \
  --dry-run \
  --max 1

# Whole API lint/test smoke for touched script surfaces.
.venv/bin/ruff check \
  scripts/cases/promote/run_bulk_promotion.py \
  scripts/cases/promote/bulk_promote_pass.py \
  scripts/cases/promote/run_case_promotion.py \
  scripts/cases/promote/promote_case_pipeline.py \
  scripts/cases/integrity/check_source_links.py \
  tests/test_run_bulk_promotion.py \
  tests/test_run_case_promotion.py \
  tests/test_promotion_script_compat.py
```

Expected results: pytest commands exit 0; dry-run prints full-depth candidates without
creating or changing `data/cases/**` or `data/batch_runs/**`; deprecated old commands
print a warning and otherwise behave the same; ruff exits 0.

## Rollback

Revert the renamed runner files and compatibility wrappers, restore old docs/runtime
messages, and delete the new/renamed tests. Remove any generated
`data/batch_runs/bulk_promote_*.json` artifacts from the failed run. No schema or data
migration is involved.
