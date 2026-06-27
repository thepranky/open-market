# DDR-J: Dual extraction for case ingestion

## Before you start

Read/trace:
- `apps/api/scripts/cases/extract/compare_extractions.py` (alignment + diff)
- `apps/api/scripts/cases/extract/ingest_case.py` (`stage_dual_extract`, the `--dual-extract` flags)
- `apps/api/scripts/cases/extract/merge_drafts.py` (`merge_from_conflict_report`)
- `apps/api/scripts/cases/promote/promote_case_pipeline.py` (`unresolved_conflicts` gate)
- `apps/api/scripts/cases/extract/calibrate_dual_extraction.py` (the calibration gate)
- `docs/specs/completed/2026-06-25-case-dual-extraction.md` (the *how*)
- DDR-B (the pipeline this sits inside) and DDR-A (source-integrity gate it relies on)

## Agent prompt

> Explain how dual extraction shrinks the human review surface from "read every
> field of every case" to "resolve conflicts only". Walk the data flow: two cold
> extractions → alignment → two-layer diff → ConflictReport → human resolution →
> merge → existing promotion gates. Explain why agreement is only trustworthy when
> the two extractions' errors are uncorrelated, and how the calibration gate proves
> that on golds before the workflow is trusted at scale. What does the third
> (adjudicator) agent do and, critically, what is it forbidden from doing?

---

## Context

Manual promotion (DDR-B) does not scale: a human reads every field of every
promoted case. At hundreds-to-thousands of cases that is the binding constraint.
The deterministic gates catch *fabrication* (quote grounding) but not
*misinterpretation* (`defined` vs `discussed`, a missed market), which is exactly
what the human is for.

Dual extraction replaces "review everything" with "review only where two
**independent** extractions disagree." Fields both extractions agree on are treated
as high-confidence and skip full review.

## Decision

Run the same source through two cold extractions, align their markets/theories by
*name* (not position), diff the aligned pairs, and emit a `ConflictReport` listing
only disagreements. A human resolves conflicts; the resolved report is merged into
one canonical-candidate draft that enters the **existing** promotion gates unchanged.

Five load-bearing decisions:

1. **Agreement is trusted only under uncorrelated errors.** Two calls to the *same*
   model with the same prompt produce *correlated* errors — both misread a market
   the same way and "agree" on the wrong value. So **heterogeneous models are the
   default** (A = `anthropic/claude-sonnet-4-6`, B = `gemini/gemini-2.5-flash`).
   `--dual-same-model` is a rate-limit fallback only; it raises Draft B's
   temperature to induce variation and records `same_model: true` in the report so a
   reviewer knows the signal is weaker.

2. **Two cold extractions, not one extraction + an LLM reviewer.** A reviewer LLM is
   anchored by the first agent's confident framing and shares its model bias — the
   circularity this design exists to avoid. The second agent reads the source with
   no knowledge of Draft A. This supersedes the Stage 5a critic (`review_draft.py`)
   for cases run in dual mode; Stage 5a is skipped there.

3. **Alignment reuses the existing reconciliation machinery.** `_reconcile` /
   `_group_reconciliation` (from `extract_case_from_source.py`) already align a draft
   against a baseline by domain-synonym expansion + token Jaccard with market/geo
   stop-word stripping. `compare_extractions` treats Draft B as the baseline and
   reconciles A against it. The four reconciliation groups map directly:
   `matched`/`likely_rename` → aligned pair; `candidate_addition` → A-only;
   `out_of_scope` → B-only. **"A found a market B missed" (and vice versa) is the
   single highest-value signal** and is never auto-resolved.

4. **The diff is two layers; the third agent classifies but never resolves.** A
   deterministic layer compares scalar/enum fields by value (a mismatch is a real
   conflict, a match is agreement) and produces the `agreed_fields` list with no LLM
   call. An optional, injectable LLM adjudicator only decides whether two
   differently-phrased values are *equivalent* (suppress) or *genuinely different*
   (raise). It may auto-resolve a narrow whitelist of trivial normalizations
   (country abbreviations, whitespace, token order), each logged `resolved_by: auto`
   for spot-check. **It never picks the right value for a genuine conflict** — that
   would re-introduce the circularity and remove the human gate, which is the point.

5. **The premise is calibrated before it is trusted.** `calibrate_dual_extraction.py`
   runs over the gold fixtures and measures, on fields where A and B *agreed*, the
   fraction that match gold (**agreement precision**, target ≥ 0.98), and the
   fraction of wrong fields that were actually raised (**conflict recall**, which
   quantifies the blind spot: a field both drafts get wrong the same way agrees, is
   skipped, and is invisible). If agreement does not predict correctness, the design
   does not ship as-is.

## Why this way

- **Uncorrelated error is the whole premise.** Agreement only means "high
  confidence" if the two extractions could have failed independently. That is why
  heterogeneous models are the default rather than an option, and why the
  calibration gate measures conflict recall *both* heterogeneous and same-model — to
  confirm two models recall more conflicts than temperature variation alone.

- **Name alignment, not positional diff, is the core feature.** Two cold extractions
  emit markets in different orders, with different ids, and one may find an entry the
  other misses. A `product_markets[0]`-vs-`product_markets[0]` diff is simply wrong.
  Reusing the existing reconciliation matcher means the alignment is the same one the
  rest of the pipeline already trusts, not a second, divergent matcher.

- **Structural comparison beats interpretive review.** Once aligned, "field A says X,
  field B says Y" is a structural fact. The human sees a small conflict surface with
  the source excerpt and both values side by side — not a full YAML to re-read.

- **The human gate is preserved deliberately.** Every genuine conflict gets
  `resolution: null` for a human. The merge step *blocks* if any conflict is still
  unresolved, so a skipped field can never silently drop. Promotion is unchanged
  downstream: source-integrity grounding (DDR-A) and `validate_cases.py` still run.

- **Calibration is the real proof, separate from a smoke test.** "Two cold
  extractions of a known-good case converge" (few conflicts) is a sanity smoke test.
  "Agreed fields are actually correct ≥ 98% of the time on golds" is the acceptance
  criterion that justifies skipping human review. They are different claims; the DDR
  rests on the second.

## Alternatives considered

- **One extraction + LLM-as-judge (keep only Stage 5a):** rejected as the *scale*
  model — circular and shares model bias. Stage 5a survives as a triage accelerator
  for single-extraction runs, but dual extraction supersedes it for cases run through
  it (DDR-B Q1).
- **Same-model dual extraction as default:** rejected — correlated errors manufacture
  false high-confidence agreement. Kept only as an availability fallback, flagged in
  the report.
- **Positional / field-path diff:** rejected — wrong by construction once the two
  drafts differ in order or ids; misses the "A found a market B didn't" signal
  entirely.
- **Let the third agent resolve conflicts (auto-merge):** rejected — removes the
  human gate and re-introduces the circularity. The adjudicator is restricted to
  {equivalent, conflict, alignment-correction, whitelisted-normalization} and may
  never emit a free-form field value.
- **Whole-document cross-section alignment for batched large cases:** deferred —
  v1 runs dual extraction per page-range/section group and concatenates the per-group
  conflict reports.

## Consequences

- **Cost:** ~2× extraction + one small comparison call per case (PDF fetch and page
  text are shared, fetched once). Break-even is roughly five minutes of lawyer
  attention per case avoided — favourable at any plausible volume.
- **Residual blind spot:** errors both drafts make *the same way* agree and are never
  surfaced. This is intrinsic, not a bug; conflict recall measures its size, and
  heterogeneous models are the lever that shrinks it. It is the reason agreement
  buys "skip full review," not "skip review entirely" — a sample spot-check of agreed
  fields remains prudent.
- **Same-model runs are weaker** and must be read as such; the `same_model` flag in
  the report header exists so a reviewer is never misled about the signal's strength.
- **Additive and reversible:** `--dual-extract` is a flag; removing it reverts to the
  single-extraction path. `draft_a` / `draft_b` / `conflicts` are intermediate
  artifacts with no `data/cases/` schema change.

## Gaps

- **The calibration gate needs two live heterogeneous extractions per gold to
  produce real numbers** (both provider API keys). The scoring is pure and tested
  offline; the agreement-precision / conflict-recall figures themselves must be run
  and recorded before the workflow is trusted to skip review on real cases at scale.
- **Calibration aligns each draft against gold** (gold defines "correct"), whereas
  the live workflow aligns Draft A against Draft B. Same matcher and equivalence
  rules, different baseline — a deliberate approximation noted in the script.
- **Per-section conflict reports are concatenated, not cross-aligned** for batched
  large cases (v1 scope).
