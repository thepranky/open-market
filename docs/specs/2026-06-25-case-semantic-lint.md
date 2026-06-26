# Case YAML semantic lint (ROADMAP 4.5)

## Goal

Catch **misinterpretations** in canonical case YAML — legal-meaning errors that pass
Pydantic schema validation and even source-integrity (the quote is real and on the
right page) but encode the wrong *legal weight* or wire identifiers incorrectly. These
are "lawyer rules" called out in DDR-A that no current gate enforces.

In scope — a deterministic, rule-based linter over already-extracted fields:

1. **Complaint → not `defined`.** A product/geographic market whose evidence is drawn
   *only* from complaint-type source documents must not be `definition_status: defined`.
   Allegations in a complaint are contested claims, not findings (CLAUDE.md
   non-negotiable; DDR-A §2). Severity **ERROR**.
2. **Dangling `supports_*` references.** Every `market_id` / `theory_id` /
   `commitment_id` named in a passage's `supports_*` list must exist in the record.
   Pydantic validates list-of-str shape but never cross-checks the join. Severity
   **ERROR**.

Out of scope:

- **The "outcome passages must not link to markets" rule (DDR-A §2) is deliberately not
  implemented.** Identifying an outcome passage means reading *quote language* (e.g. "does
  not raise serious doubts", "is hereby declared compatible"), since there is no structural
  tag for it: a corpus audit (2026-06-25) found `section` — the only structural field that
  could stand in — populated on just 9 of 7,566 passages (0.12%), and those few values are
  *theory conclusions* that legitimately link markets/theories. So the rule would have to be
  a phrase heuristic over prose, which carries false positives, and a deterministic gate is
  the wrong place for that judgement. Its home is the Stage 5a critic (`review_draft.py`)
  and human review, and — once it lands — the dual-extraction comparison (ROADMAP 5.9).
  Revisit only if extraction begins emitting a reliable passage-role tag.
- Re-reading source prose to re-derive a definition status or classify a passage.
- Jurisdiction YAML (ROADMAP 4.6); schema/enum checks (`validate_cases.py`); quote/URL
  grounding (`check_source_integrity.py`).

## Approach

**Deterministic, not an LLM call.** The lint is a third validation layer next to the two
in DDR-A §1 (schema, source-integrity): same YAML in → same verdict out, no network, no
model spend, safe on every PR and in promotion.

Why deterministic matters here specifically — the pipeline's misinterpretation defenses
are otherwise LLM-based (Stage 5a critic) or LLM-cross-checked (dual extraction, 5.9).
Both reduce *independent/stochastic* extraction errors but are blind to *correlated*
errors where every pass shares the same blind spot (e.g. LLMs reading complaint
allegations as findings). A hard-coded legal invariant is the one defense that holds
regardless of how many models agree. Rule 1 targets exactly that correlated failure;
rule 2 (referential integrity) is orthogonal to extraction entirely.

How each rule stays label-robust:

- **Rule 1** keys off `source_document.doc_type` matching a complaint pattern
  (`complaint`). This is a low-ambiguity, stable field — far less prone to systematic
  error than `definition_status`. A market is flagged when (a) `definition_status ==
  defined` and (b) every passage supporting it references a complaint document and (c) no
  supporting passage references a non-complaint document. Residual blindness (both the
  doc_type *and* the status wrong) is accepted: it leaves us no worse than today.
- **Rule 2** depends on no LLM label at all — it is pure referential integrity.

Accepted blind spots in Rule 1 (no worse than today, but explicit so callers don't
over-trust the gate): it does **not** flag a `defined` market with *no* supporting
passages, nor one whose passages exist but never name it via `supports_*`. The rule
keys on complaint-only *grounding*; an under-evidenced `defined` market is an
evidence-completeness concern owned by source-integrity and human review, not this lint.

Severity: both rules are **ERROR** (block promotion / fail CI). Rule 1 is a stated
non-negotiable; rule 2 violations are unambiguous data bugs.

Mirror existing script conventions: a standalone CLI with `--cases-dir`, `--case-id`,
`--verbose`, an issue-level summary line, and non-zero exit on ERROR — so it drops into
`promote_case_pipeline.py` and CI like the other gates.

**Forward compatibility with dual extraction (5.9):** the lint logic lives in a pure
module so it can also be run per-draft against *both* cold extractions before the diff —
an invariant violation in one pass becomes a conflict signal for the human's review view
rather than a surprise at promotion. No change to the logic; just an additional caller
later. Out of scope for this spec.

## Files

- **`apps/api/app/cases/loader/semantic_lint.py`** (new) — pure functions:
  `lint_case(record) -> list[Issue]` and `lint_all(cases_dir, case_id=None)`. Logic lives
  here (testable without subprocess), matching how `validator.py` holds `validate_all`.
- **`apps/api/scripts/cases/lint_case_semantics.py`** (new) — thin CLI wrapper
  (argparse + summary print + exit code), mirroring `validate_cases.py`.
- **`apps/api/scripts/cases/promote_case_pipeline.py`** (modify) — insert the lint as a
  new gate immediately after step 3 (canonical schema validation), scoped to the promoted
  record via `--case-id`. Renumber the `[n/8]` step labels to `[n/9]`.
- **`.github/workflows/data-contracts.yml`** (modify) — add a `Semantic lint` step to the
  `validate-cases` job, after `validate_cases.py`, over `../../data/cases`.
- **`apps/api/tests/test_semantic_lint.py`** (new) — unit tests per rule on small
  in-memory `CaseRecord` fixtures (pass + each failure mode).
- **`ROADMAP.md`** (modify) — note narrowed scope on row 4.5; mark done on completion.

## Verification

```bash
cd apps/api
# Unit tests: passing fixture + each failure mode (complaint-only defined; dangling id)
.venv/bin/python -m pytest tests/test_semantic_lint.py -v

# Whole corpus — expect a clean baseline (0 dangling confirmed in audit 2026-06-25)
.venv/bin/python scripts/cases/lint_case_semantics.py --cases-dir ../../data/cases

# Single record, as the promotion pipeline invokes it
.venv/bin/python scripts/cases/lint_case_semantics.py \
    --cases-dir ../../data/cases --case-id jetblue_spirit_2024

# Pipeline still parses / promote path green (dry-run exits after promote, BEFORE the
# lint at step 4 — the gate itself is exercised by the single-record command above and
# in CI; --dry-run does not run it).
.venv/bin/python scripts/cases/promote_case_pipeline.py \
    --case-id eu_siemens_gamesa_2017 --focus market_definition --dry-run

.venv/bin/ruff check .
```

Manual: confirm a deliberately mis-set fixture (a complaint-only market flipped to
`defined`; a dangling `supports_markets` id) each produces the expected ERROR and a
non-zero exit code.

## Rollback

Self-contained: delete the two new files and the test, revert the
`promote_case_pipeline.py` step insertion and the `data-contracts.yml` step. No data or
schema migration — the linter only reads YAML.
