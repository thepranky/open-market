# Case YAML semantic lint (ROADMAP 4.5)

## Goal

Catch **misinterpretations** in canonical case YAML — legal-meaning errors that pass
Pydantic schema validation and even source-integrity (the quote is real and on the
right page) but encode the wrong *legal weight*. These are the "lawyer rules" called
out in DDR-A that no current gate enforces.

In scope — a deterministic, rule-based linter over already-extracted fields:

1. **Complaint → `discussed`.** A product/geographic market whose evidence is drawn
   *only* from complaint-type source documents must not be `definition_status: defined`.
   Allegations in a complaint are contested claims, not findings (CLAUDE.md
   non-negotiable; DDR-A §2).
2. **Outcome passages must not link to markets.** A passage that records the *decision
   outcome* (cleared / blocked / operative part / conclusion) must leave
   `supports_markets` and `supports_geographic_markets` empty — outcome is not market
   evidence (DDR-A §2 "outcome passages must not link to markets").
3. **Dangling `supports_*` references.** Every `market_id` / `theory_id` /
   `commitment_id` named in a passage's `supports_*` list must exist in the record.
   Pydantic validates list-of-str shape but never cross-checks the join.

Out of scope:

- Re-reading source prose to *re-derive* a definition status or *classify* a passage
  from its text. That semantic judgement stays upstream in extraction and the Stage 5a
  LLM critic (`review_draft.py`), not in a promotion gate (see Approach).
- Jurisdiction YAML (covered by ROADMAP 4.6).
- Schema/type/enum checks (already in `validate_cases.py`) and quote/URL grounding
  (already in `check_source_integrity.py`).

## Approach

**Deterministic, not an LLM call.** The lint is a new third validation layer next to
the two in DDR-A §1 (schema, source-integrity). All three are reproducible gates: same
YAML in → same verdict out, no network, no model spend, safe to run on every PR and in
the promotion pipeline. An LLM in a gate would be non-deterministic, costly per case,
and would re-introduce the very misinterpretation risk we are trying to catch.

The rules are expressed as cross-field invariants over structured fields that the
*upstream* LLM stages already populated (`definition_status`, `doc_type`, `section`,
`supports_*`). Where a rule needs to know "is this an outcome passage?" or "is this a
complaint?", we key off **structured signals already in the record**, not free text:

- *complaint* = the passage's `source_document.doc_type` matches a complaint pattern
  (`complaint`, `administrative complaint`, `redacted complaint`). US FTC/DOJ records
  carry this; the extraction profile sets it.
- *outcome* = the passage's `section` matches an outcome pattern (`conclusion`,
  `decision`, `outcome`, `operative part`, `disposition`) **and** the passage carries
  market links. This is a heuristic on the `section` label, not on the quote prose.

If a record lacks the structured signal (e.g. a complaint with `doc_type: report`), the
linter cannot and should not guess from prose — that is precisely the judgement we leave
to the human reviewer and the Stage 5a critic. The linter's contract is: *given the
structured fields are right, the legal-weight wiring is consistent.* Misclassification of
`doc_type`/`section` itself is an extraction-quality problem, surfaced upstream.

Severity mirrors `check_source_integrity.py`: **ERROR** blocks promotion (rules 1 and 3),
**WARNING** needs human triage (rule 2 — the `section` heuristic can have edge cases, so
it should not hard-block a promotion until the heuristic is proven on the corpus).

Mirror the existing script conventions: a standalone CLI with `--cases-dir`, `--case-id`,
`--verbose`, an issue-level summary line, and non-zero exit on ERROR — so it drops into
`promote_case_pipeline.py` and CI the same way the other gates do.

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
- **`ROADMAP.md`** (modify) — mark 4.5 done.

## Verification

```bash
cd apps/api
# Unit tests: one passing fixture + one failing fixture per rule
.venv/bin/python -m pytest tests/test_semantic_lint.py -v

# Whole corpus — expect a clean baseline (triage any pre-existing hits before merge)
.venv/bin/python scripts/cases/lint_case_semantics.py --cases-dir ../../data/cases

# Single record, as the promotion pipeline invokes it
.venv/bin/python scripts/cases/lint_case_semantics.py \
    --cases-dir ../../data/cases --case-id us_<a_complaint_case>

# Full pipeline still green end to end (dry run on an already-promoted case)
.venv/bin/python scripts/cases/promote_case_pipeline.py \
    --case-id eu_siemens_gamesa_2017 --focus market_definition --dry-run

.venv/bin/ruff check .
```

Manual: confirm a deliberately mis-set fixture (a complaint-only market flipped to
`defined`, a dangling `supports_markets` id, a `conclusion` passage linking a market) each
produces the expected ERROR/WARNING and the right exit code.

## Rollback

Self-contained: delete the two new files and the test, revert the
`promote_case_pipeline.py` step insertion and the `data-contracts.yml` step. No data or
schema migration — the linter only reads YAML.
