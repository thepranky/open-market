# Spec: End-to-end extraction orchestrator (ROADMAP 5.11)

## Goal

One CLI command takes a case index entry and produces a review-ready merged draft
covering all three extraction focuses (market_definition, theories, remedies) plus
conflict reports for each focus. The human then resolves only the inter-model
conflicts, not the full YAML.

Before this spec, extracting a new case requires approximately 60 manual commands:
`ingest_case.py` per focus, dual extraction per focus, per-focus
`merge_drafts.py --from-conflict-report`, multi-focus `merge_drafts.py`, and
`check_review_readiness.py`. After this spec:

```bash
python apps/api/scripts/cases/extract/run_e2e_extraction.py \
  --case-id eu_example_2024 --from-index
```

outputs per-focus Draft A files, Draft B files, conflict reports, any single-pass
metadata draft, a merged draft, and a readiness summary. The human then resolves
conflicts from the dual-focus conflict reports and (if needed) re-merges.

Out of scope:
- Automated conflict resolution or promotion without human sign-off.
- Batch operation over many cases — that remains `run_bulk_extraction.py`.
- Changing the focus list beyond what the pipeline profile declares.
- Handling `--batch-by-section` / `--page-range` at the orchestrator level; those
  flags pass through to `ingest_case.py` but section-level conflict concatenation
  is not orchestrated here.

## Approach

### What the orchestrator does, step by step

**Step 0 — Load index entry and resolve PDF URL**

If `--from-index` is given, pass `--from-index` and optional `--pdf-url` through
to `ingest_case.py`. `ingest_case.py` remains the owner of case-index loading,
PDF URL resolution, and scaffold creation at
`data/drafts/<jur>/<case_id>.scaffold.yaml`. Otherwise, `ingest_case.py` requires
a canonical YAML at `data/cases/**/<case_id>.yaml`.

`pdf_language` stays inside the `ingest_case.py` scaffold path; the orchestrator
does not duplicate non-English handling.

**Step 1 — Select pipeline profile**

Call `pipeline_profile.select_profile(case_id)` to determine which focuses to run.
For EC decisions the profile declares `focus_defaults: [market_definition, theories,
remedies, outcome_metadata]`; for CMA reports and US court opinions the profile
differs. The orchestrator runs the non-`outcome_metadata` focuses with dual
extraction (market_definition, theories, remedies); `outcome_metadata` is always
run as a single-extraction pass (the pp.1–30 range it covers is short enough that
dual extraction adds more noise than signal).

**Step 2 — Per-focus dual extraction (interruptible)**

For each focus in order `[market_definition, theories, remedies]`:

1. Check the state file (`data/drafts/<jur>/<case_id>.e2e_state.yaml`). If the
   focus is already marked `completed`, skip it (resume support).
2. Call `ingest_case.py --dual-extract` via `subprocess.run`, forwarding
   `--from-index`, `--pdf-url`, `--provider`, `--dual-same-model`, `--max-cost`,
   `--batch-by-section`, and `--page-range` if supplied.
3. On success (exit 0), record the focus in state as `completed`.
4. On failure (non-zero exit), record as `failed` with the stderr. Continue to the
   next focus (partial failure must not abort the run — a theories extraction
   failure must not erase a completed market_definition draft).
5. Write state after each focus.

Each focus produces (via the existing ingest_case.py naming convention):
```
data/drafts/<jur>/<case_id>.<focus>.draft_a.yaml
data/drafts/<jur>/<case_id>.<focus>.draft_b.yaml
data/drafts/<jur>/<case_id>.<focus>.conflicts.yaml
data/drafts/<jur>/<case_id>.<focus>.review.md
```

The retired single-draft critic is not part of this orchestrator. Each focus uses
`--dual-extract`, and human review happens from the conflict reports plus merged
readiness packet.

**Step 3 — Optional outcome_metadata single-extraction pass**

If the profile declares `outcome_metadata` in its focus list and no canonical YAML
exists yet, run `ingest_case.py` (single extraction, no `--dual-extract`) for focus
`outcome_metadata` with the default `--page-range 1:30`. This is a fast one-shot
pass for procedural metadata (dates, outcome, parties) that is short and low-risk.
Record it in state as a completed `outcome_metadata` focus.

**Step 4 — Additive merge of completed draft outputs**

Collect each completed focus's merge input: `<case_id>.<focus>.draft_a.yaml` for
dual-extraction focuses and `<case_id>.outcome_metadata.draft.yaml` for the
single-pass metadata focus. Call
`merge_drafts.merge_drafts(draft_paths, case_id_override=case_id)` in process
(not subprocess) and write the result to:

```
data/drafts/<jur>/<case_id>.e2e.merged.draft.yaml
```

The merge is additive because each focus owns a non-overlapping slice of the
CaseRecord:
- `market_definition` → `product_markets_considered`, `geographic_markets_considered`,
  and their supporting `source_passages`.
- `theories` → `theories_of_harm` and their supporting `source_passages`.
- `remedies` → `commitments` and their supporting `source_passages`.

`merge_drafts.merge_drafts()` already handles deduplication of shared passages
(by `quote_snippet`/`page`/`doc_id` key) and ID rewriting, so no new merge logic
is needed.

The merged draft at this stage is a preliminary view derived from Draft A for each
dual focus plus the single-pass metadata draft. Its purpose is to let
`check_review_readiness.py` run and to give the reviewer a holistic draft while
they work through the conflict reports. After the reviewer resolves each
dual-focus conflict report and runs per-focus
`merge_drafts.py --from-conflict-report`, they should re-merge the resulting
`<focus>.merged.draft.yaml` files plus the metadata draft using `merge_drafts.py`
to produce the final pre-promotion draft.

**Step 5 — check_review_readiness**

Call `check_review_readiness.run_checks(draft, plan, draft_paths, profile=profile)`
and `check_review_readiness.write_review_packet(...)` in process. Write the review
packet to:

```
data/drafts/<jur>/<case_id>.e2e.review_packet.md
```

Record result (`PASS` / `WARN` / `FAIL`) in state.

**Step 6 — Summary report**

Write `data/drafts/<jur>/<case_id>.e2e.summary.md` listing:
- Which focuses completed / failed, with draft paths.
- The merged draft path.
- The readiness result (errors and warnings).
- A "next steps" section:
  1. For each focus with conflicts: review and resolve
     `data/drafts/<jur>/<case_id>.<focus>.conflicts.yaml`, then run
     `merge_drafts.py --from-conflict-report`.
  2. Re-merge the three `<focus>.merged.draft.yaml` files with `merge_drafts.py`.
  3. Re-run `check_review_readiness.py --packet`.
  4. Promote via `promote_case_pipeline.py`.

### State file schema

```yaml
# data/drafts/<jur>/<case_id>.e2e_state.yaml
case_id: eu_example_2024
started_at: "2026-06-27T10:00:00Z"
focuses:
  market_definition: completed   # completed | failed | skipped | pending
  theories: completed
  remedies: failed
  outcome_metadata: completed
merged_draft: data/drafts/eu/eu_example_2024.e2e.merged.draft.yaml
readiness_status: WARN           # PASS | WARN | FAIL | null
```

On re-run with `--resume`, the orchestrator reads this file and skips completed
focuses. Without `--resume` (or if state file does not exist), it runs from scratch.
Explicitly passing `--resume` is required to avoid silently reusing stale drafts.

### What is composed from existing scripts vs what is new

| Piece | Existing or new |
|---|---|
| PDF fetch, scaffold build, `--from-index` logic | Existing (`ingest_case.py`) — called via subprocess, not reimplemented |
| Pipeline profile selection | Existing (`pipeline_profile.select_profile`) — imported |
| Per-focus dual extraction | Existing (`ingest_case.py --dual-extract`) — called via subprocess |
| Conflict report generation | Existing (inside `ingest_case.py Stage 2b`) — no new call |
| Additive merge of completed draft files | Existing (`merge_drafts.merge_drafts()`) — imported |
| Review readiness | Existing (`check_review_readiness.run_checks()`) — imported |
| Summary report | New (thin Markdown writer inside orchestrator) |
| State file read/write | New (simple YAML, ~30 lines) |
| Orchestrator CLI | New (`run_e2e_extraction.py`) |

The orchestrator introduces no new extraction, merge, or diff logic. It is a thin
sequencer over existing primitives.

## Files

| File | Change |
|---|---|
| `apps/api/scripts/cases/extract/run_e2e_extraction.py` | New — orchestrator CLI |
| `data/drafts/<jur>/<case_id>.e2e_state.yaml` | New — generated at runtime; not committed |
| `data/drafts/<jur>/<case_id>.e2e.merged.draft.yaml` | New — generated at runtime; not committed |
| `data/drafts/<jur>/<case_id>.e2e.review_packet.md` | New — generated at runtime; not committed |
| `data/drafts/<jur>/<case_id>.e2e.summary.md` | New — generated at runtime; not committed |
| `apps/api/scripts/cases/extract/ingest_case.py` | No change (called via subprocess) |
| `apps/api/scripts/cases/extract/merge_drafts.py` | No change (imported) |
| `apps/api/scripts/cases/review/check_review_readiness.py` | No change (imported) |
| `apps/api/scripts/cases/extract/pipeline_profile.py` | No change (imported) |

### `run_e2e_extraction.py` CLI

```
usage: run_e2e_extraction.py --case-id CASE_ID [options]

  --case-id CASE_ID         Required. Case identifier.
  --from-index              Build scaffold from data/case_index/ entry.
  --pdf-url URL             Decision PDF URL for --from-index (auto-resolved if absent).
  --resume                  Skip focuses already marked completed in state file.
  --max-cost FLOAT          Per-focus cost cap in USD, passed to ingest_case.py (default: 2.00).
  --provider {anthropic,gemini}  Primary extraction provider (default: anthropic).
  --dual-same-model         Use same provider for Draft B (fallback; weakens signal).
  --batch-by-section        Forward to ingest_case.py for large documents.
  --page-range START:END    Forward to ingest_case.py (applied to all focuses).
  --focuses FOCUS[,FOCUS]   Override focus list (default: from pipeline profile).
  --profile PROFILE         Override profile inference.
  --cache-dir PATH          PDF text cache directory passed to ingest_case.py.
  --dry-run                 Print what would run; do not execute or write any files.
```

## Verification

```bash
# 1. Run the orchestrator on a known EU case that is already in data/case_index/
#    and has a pdf_url. eu_sika_mbcc_2023 has a canonical + eval fixture; it
#    makes a fast smoke-test case.
.venv/bin/python apps/api/scripts/cases/extract/run_e2e_extraction.py \
  --case-id eu_sika_mbcc_2023 \
  --max-cost 6.00

# 2. Confirm per-focus artifacts written
ls data/drafts/eu/eu_sika_mbcc_2023.{market_definition,theories,remedies}.draft_{a,b}.yaml
ls data/drafts/eu/eu_sika_mbcc_2023.{market_definition,theories,remedies}.conflicts.yaml

# 3. Confirm merged draft written
ls data/drafts/eu/eu_sika_mbcc_2023.e2e.merged.draft.yaml

# 4. Confirm readiness summary exists
cat data/drafts/eu/eu_sika_mbcc_2023.e2e.summary.md

# 5. Check state file records all three focuses as completed
cat data/drafts/eu/eu_sika_mbcc_2023.e2e_state.yaml

# 6. Simulate a partial failure and confirm resume skips completed focuses.
#    Delete the theories draft and mark it pending in the state file, then re-run
#    with --resume. Only the theories focus should be re-extracted.
rm data/drafts/eu/eu_sika_mbcc_2023.theories.draft_a.yaml
python -c "
import yaml, pathlib
p = pathlib.Path('data/drafts/eu/eu_sika_mbcc_2023.e2e_state.yaml')
s = yaml.safe_load(p.read_text())
s['focuses']['theories'] = 'pending'
p.write_text(yaml.dump(s))
"
.venv/bin/python apps/api/scripts/cases/extract/run_e2e_extraction.py \
  --case-id eu_sika_mbcc_2023 \
  --resume \
  --max-cost 2.00
# Confirm only the theories focus was re-run (market_definition and remedies logs absent).

# 7. Run on a new case via --from-index to confirm scaffold path
.venv/bin/python apps/api/scripts/cases/extract/run_e2e_extraction.py \
  --case-id <any_case_with_index_entry_and_pdf_url> \
  --from-index \
  --max-cost 6.00

# 8. Existing tests pass
.venv/bin/python -m pytest apps/api/tests/ -v
```

Expected result for eu_sika_mbcc_2023: profile-selected focuses complete, dual
focus conflict reports show few or zero unresolved conflicts (the case has a
known-good canonical to converge towards), merged draft has non-empty
`product_markets_considered`, `theories_of_harm`, and `commitments` (if any),
and `check_review_readiness` returns PASS or WARN with no structural errors.
