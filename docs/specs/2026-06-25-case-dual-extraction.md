# Spec: Dual extraction for case ingestion

## Goal

Replace per-case human promotion review with a comparison-driven workflow: two
independent LLM extractions of the same source document are aligned and diffed; a
human reviews only the fields where the two disagree. Fields that both extractions
agree on are treated as high-confidence and skip full human review.

This reduces the human bottleneck from "read every field of every case" to "resolve
conflicts and spot-check a sample." At scale (hundreds to thousands of cases) it
is the only model that remains feasible.

Out of scope:
- Changing the quote-grounding gate (`check_source_integrity.py`) — that already
  runs and catches fabricated quotes; this spec sits on top of it.
- Automated YAML promotion without human sign-off — a human still approves the
  final merge, but from a much smaller conflict surface.
- Changing the existing single-extraction path in `ingest_case.py` — dual
  extraction is a new flag/mode, not a replacement, so existing single-pass runs
  still work.

## Premise and its validity condition

The workflow rests on one assumption: **agreement between the two extractions
predicts correctness.** That holds only when the two extractions' errors are
*uncorrelated*. Two calls to the same model with the same prompt and the same
source produce *correlated* errors — when the model misreads a market the same way
twice, both drafts agree on the wrong value and it passes as "high-confidence."
Shared model bias is precisely the failure mode that independent errors would
catch.

Two consequences, both load-bearing for the rest of the spec:

1. **Heterogeneous models are the default, not an option** (see "Extraction
   independence"). Same-model dual extraction is a fallback only.
2. **The premise must be calibrated before the workflow is trusted at scale** (see
   "Calibration gate"). We measure, on gold cases, whether agreed fields are
   actually correct — if they are not, the design does not ship.

## Approach

### Why two cold extractions rather than one extraction + LLM review

An LLM reviewing another LLM's output is circular: the reviewer is influenced by
the first agent's confident framing, and both may share the same model biases.
True independence requires the second agent to read the source document with no
knowledge of what the first agent produced. The comparison step is then structural
— field A says X, field B says Y — not interpretive.

**Relationship to the existing Stage 5a critic (`review_draft.py`).** Stage 5a is a
single-draft critic that triages one extraction. Dual extraction supersedes it for
cases run in `--dual-extract` mode: the conflict surface is a strictly better
review signal than a self-critique of one draft, and running both is redundant
cost. Stage 5a remains available for single-extraction runs. When `--dual-extract`
is set, Stage 5a is skipped.

### Extraction independence constraints

- Extraction B is a fresh API call that reads the same source text but has **no
  access to Draft A's output**.
- **Model heterogeneity (default).** Draft A is extracted with one model, Draft B
  with a different one. The existing `LLMClient` abstraction already supports
  `anthropic` and `gemini` providers (`ingest_case.py`), so this is a flag, not new
  architecture. Default pairing: A = `anthropic` (`claude-sonnet-4-6`),
  B = `gemini` (`gemini-2.5-flash`). `--dual-same-model` forces both to the primary
  provider as a fallback (e.g. when one provider is rate-limited or unavailable);
  this weakens the agreement signal and is recorded in the conflict report header.
- **Variance when same-model.** The Anthropic API has no seed parameter, and the
  current extraction path does not set `temperature` (defaults to 1.0). Same-model
  mode therefore relies on default sampling variance only, which for tool-use
  structured output can be low — another reason heterogeneous models are the
  default. When `--dual-same-model` is used, Draft B is issued with `temperature`
  raised (0.7 → 1.0 spread) to induce variation; this is documented in the report
  header so a reviewer knows the agreement signal is weaker.
- The source text feed (PDF page cache) is **shared** — both extractions read the
  same cached page text; re-fetching the PDF is waste.

### Record alignment (the core step)

Two independent extractions will **not** emit markets/theories in the same order,
will **not** share `market_id`s, and one may find an entry the other misses. A
field-path diff that assumes `product_markets[0]` in A is the same market as
`product_markets[0]` in B is therefore wrong. **Alignment — matching A's entries to
B's entries by semantic name — is the core of this feature**, and the single most
important signal it produces is "A found a market that B did not."

Alignment **reuses the existing reconciliation machinery** rather than inventing a
new matcher:

- `_reconcile(draft, baseline_record, focus=...)`
  (`extract_case_from_source.py:3288`) already aligns a draft against a baseline
  record using domain synonym expansion (`_MARKET_SYNONYM_MAP`), token Jaccard with
  market/geo stop-word stripping, and device-context conflict detection
  (`_DEVICE_CONTEXTS`, `_CONFLICTING_DEVICE_PAIRS`).
- `compare_extractions.py` treats **Draft B as the baseline** and reconciles Draft A
  against it. `_group_reconciliation` (line 3888) partitions the result into the
  four groups already used elsewhere:
  - `matched` → aligned pair; diff their fields (next section).
  - `likely_rename` → aligned pair whose names differ; this is a candidate
    qualitative conflict on the name field.
  - `candidate_addition` → present in A, absent in B → **A-only conflict** (a market
    one model found and the other missed).
  - `out_of_scope` → present in B, absent in A → **B-only conflict** (symmetric).
- A-only and B-only entries are the highest-value conflicts and are always surfaced
  to the human; they are never auto-resolved.

### Comparison (diff) step — two layers

Once entries are aligned, the diff is two-layered:

**Deterministic layer (no LLM call).** For aligned pairs, compare scalar/enum/
numeric fields by value: `definition_status`, `outcome`, deal value, market shares,
page numbers, doc ids. These are unambiguous; a mismatch is a genuine conflict, a
match is agreement. This layer also produces the `agreed_fields` list.

**LLM layer (scoped to two jobs only).** A third agent is used for, and only for:
1. **Alignment adjudication** — confirming/splitting the `likely_rename` group
   (is "Ready-mix concrete — Germany" the same market as "— DE", or two different
   markets?), and resolving ambiguous many-to-one matches the fuzzy matcher flags.
2. **Qualitative equivalence** — deciding whether two differently-phrased values of
   the same aligned field (market names, theory-of-harm labels) are *equivalent*
   (suppress as non-conflict) or *genuinely different* (raise as conflict), reading
   the source excerpt.

**The third agent classifies and normalizes; it does not resolve.** It never picks
the "right" value for a genuine conflict — that would re-introduce the circularity
this design rejects and would remove the human gate, which is the point. The only
values it may auto-resolve are a narrow whitelist of trivial normalizations
(country-name abbreviations e.g. `DE`↔`Germany`, whitespace, token ordering), and
**every auto-resolution is logged in the report** with `resolved_by: auto` so the
human can spot-check. Everything else gets `resolution: null` for the human.

The third agent reads Draft A and Draft B (and source excerpts) but **cannot
introduce new claims about the source** — its output is restricted to {equivalent,
conflict, alignment-correction, whitelisted-normalization}, never free-form field
values.

### ConflictReport schema

```yaml
conflict_report:
  case_id: eu_sika_mbcc_2023
  focus: market_definition
  models:
    draft_a: anthropic/claude-sonnet-4-6
    draft_b: gemini/gemini-2.5-flash
    same_model: false          # true when --dual-same-model; weakens agreement signal
  agreed_fields: [...]         # both extractions matched, deterministic or equivalence-confirmed
  conflicts:
    - field: product_markets/<aligned-key>/definition_status
      kind: value_mismatch     # deterministic-layer disagreement
      draft_a: defined
      draft_b: discussed
      source_excerpt: "the Commission considers..."
      resolution: null         # filled by human
    - field: product_markets/<aligned-key>/market_name
      kind: rename_candidate    # LLM judged genuinely different, not equivalent
      draft_a: "Ready-mix concrete — Germany"
      draft_b: "Cement — Germany"
      source_excerpt: null
      resolution: null
    - field: product_markets
      kind: a_only             # A found it, B missed it
      draft_a: "Mortar additives — EEA"
      draft_b: null
      source_excerpt: "..."
      resolution: null
  auto_resolved:               # whitelisted normalizations, for spot-check
    - field: geographic_markets/<aligned-key>/market_name
      draft_a: "Germany"
      draft_b: "DE"
      resolved_to: "Germany"
      resolved_by: auto
```

Aligned entries are keyed by a stable alignment key (derived from the normalized
matched name), **not** by positional index, so the report survives re-runs and the
two drafts' differing orderings.

### Apply-resolutions → merged record

The ConflictReport with human-filled `resolution` fields must be turned into a
single canonical-candidate draft. This is an explicit stage, not an implicit one:

- `merge_drafts.py` (already exists; `merge_drafts()` at line 815) gains a
  `--from-conflict-report` mode: it takes Draft A, Draft B, and the resolved
  ConflictReport, and emits the merged draft by applying — for each aligned entry —
  the agreed value, the human resolution, or the auto-resolved normalization.
- A guard rejects the merge if any conflict still has `resolution: null` (unresolved
  conflicts must block, not silently drop a field).
- The merged draft then enters the **existing** promotion gates unchanged
  (`check_source_integrity.py`, `validate_cases.py`, `promote_case_pipeline.py`).

### Human review surface

A human sees the `ConflictReport`, not the full YAML. For each conflict:
- the source excerpt is shown,
- Draft A and Draft B values are shown side by side,
- the human picks one, edits, or leaves a note (writing `resolution`).

`auto_resolved` entries are shown collapsed for optional spot-check.

### When to skip dual extraction

- Cases with a very small source document (< 10 pages): single extraction + human
  review of the full record is faster.
- Re-runs of cases already in `data/cases/` where only a specific focus (e.g.
  `theories_of_harm`) is being added: diff the new extraction against the existing
  canonical record (reuse the same `_reconcile`-based alignment, with the canonical
  as baseline) rather than running a full second extraction.
- Large cases run with `--batch-by-section` / `--page-range`: dual extraction
  multiplies both the API calls and the alignment work across batches. For the first
  iteration, dual extraction operates **per page-range/section group** (drafts and
  conflict reports carry the same suffix as single-pass runs), and the per-section
  conflict reports are concatenated. Whole-document cross-section alignment is a
  non-goal for v1.

## Calibration gate (acceptance criterion — must pass before scale use)

Before this workflow is used to skip human review on real cases, run it on the
gold eval fixtures (the full-gold cases currently at 5/5 PASS / F1=1.000) and
measure, **on fields where Draft A and Draft B agreed**, the fraction that match
gold:

- **Agreement precision** = (agreed fields that match gold) / (agreed fields).
  This is the number that justifies skipping human review. Target ≥ 0.98; if agreed
  fields are wrong more than ~2% of the time, agreement does not predict
  correctness and the design must change (e.g. require a third extraction, or fall
  back to full review).
- **Conflict recall** = (gold-mismatched fields that were raised as conflicts) /
  (all fields where at least one draft was wrong). A field both drafts got wrong in
  the same way is invisible — this metric quantifies that blind spot.
- Run the gate **both** heterogeneous (default) and `--dual-same-model`, to confirm
  the heterogeneous pairing materially improves conflict recall (the justification
  for defaulting to two models).

This gate is a one-time validation script over existing golds, reported in the PR;
it is the real proof the feature works, distinct from the convergence smoke test
below.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/cases/extract/ingest_case.py` | Add `--dual-extract` and `--dual-same-model` flags; when set, run extraction twice (A primary provider, B secondary provider by default) and write both drafts; skip Stage 5a in dual mode |
| `apps/api/scripts/cases/extract/compare_extractions.py` | New — aligns Draft A↔B via `_reconcile`/`_group_reconciliation`, runs deterministic + LLM diff layers, writes `ConflictReport` YAML |
| `apps/api/scripts/cases/extract/merge_drafts.py` | Add `--from-conflict-report` mode: apply agreed values + human resolutions + auto-normalizations → single merged draft; block on any unresolved conflict |
| `apps/api/scripts/cases/promote/promote_case_pipeline.py` | Add optional `--conflict-report` flag; when present, require a fully-resolved report (no `resolution: null`) before promotion |
| `apps/api/scripts/cases/extract/calibrate_dual_extraction.py` | New — runs dual extraction over gold fixtures, reports agreement-precision / conflict-recall (the calibration gate) |
| `data/drafts/<jur>/<case_id>.<focus>[.<suffix>].draft_a.yaml` | Draft A output (dual-extract mode); filename keeps focus + page-range suffix to match existing convention |
| `data/drafts/<jur>/<case_id>.<focus>[.<suffix>].draft_b.yaml` | Draft B output (dual-extract mode) |
| `data/drafts/<jur>/<case_id>.<focus>[.<suffix>].conflicts.yaml` | ConflictReport (generated by `compare_extractions.py`) |
| `apps/api/tests/test_compare_extractions.py` | New — unit tests for alignment + conflict detection; fixture pair of diverging drafts incl. an A-only market and an equivalent-but-reworded name |

## Verification

```bash
# 1. Run dual extraction on a known case (default = heterogeneous models)
.venv/bin/python apps/api/scripts/cases/extract/ingest_case.py \
  --case-id eu_sika_mbcc_2023 \
  --focus market_definition \
  --dual-extract \
  --max-cost 3.00

# 2. Confirm both drafts written (focus + convention preserved in name)
ls data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_{a,b}.yaml

# 3. Run comparison (alignment + two-layer diff → conflict report)
.venv/bin/python apps/api/scripts/cases/extract/compare_extractions.py \
  --case-id eu_sika_mbcc_2023 \
  --draft-a data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_a.yaml \
  --draft-b data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_b.yaml

# 4. Inspect conflict report
cat data/drafts/eu/eu_sika_mbcc_2023.market_definition.conflicts.yaml

# 5. (after human fills resolutions) merge → single draft
.venv/bin/python apps/api/scripts/cases/extract/merge_drafts.py \
  --from-conflict-report data/drafts/eu/eu_sika_mbcc_2023.market_definition.conflicts.yaml \
  --draft-a data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_a.yaml \
  --draft-b data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_b.yaml

# 6. Calibration gate over gold fixtures (the real proof)
.venv/bin/python apps/api/scripts/cases/extract/calibrate_dual_extraction.py --golds

# 7. Existing tests still pass
.venv/bin/python -m pytest tests/ -v -k "not indexed_cases and not ingest_case"
```

Expected (smoke test): the conflict report for `eu_sika_mbcc_2023` (a well-covered
case with a verified canonical) should show zero or very few conflicts, validating
that two cold extractions converge on a known-good record. Expected (calibration
gate): agreement precision ≥ 0.98 across golds, with heterogeneous models showing
higher conflict recall than `--dual-same-model`.

## Cost note

Dual extraction adds: a second extraction (different model) + one comparison agent
call. PDF fetch and text extraction are shared (single fetch). At ~$0.50–1.00 per
extraction, each case costs roughly: extraction A + extraction B + small comparison
call ≈ $1.50–2.50 total. (Note: the per-run cost figure printed by the pipeline is
known to over-state Sonnet cost; treat displayed costs as upper bounds.) The human
time saved on full-record review at scale far exceeds the API cost at any plausible
volume — break-even is roughly 5 minutes of lawyer attention per case avoided.

## Rollback

`--dual-extract` is an additive flag; removing it reverts to the existing
single-extraction path (Stage 5a critic still available there). No schema changes to
`data/cases/` are required — `draft_a`, `draft_b`, and `conflicts` files are
intermediate artifacts that can be deleted. `merge_drafts.py --from-conflict-report`
is additive to the existing merge entrypoint.
