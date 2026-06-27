# DDR-B: Extraction pipeline


## Before you start

Read/trace:
- `apps/api/scripts/cases/extract/extract_case_from_source.py`, `ingest_case.py`
- `apps/api/scripts/cases/review/review_draft.py`, `promote_case_pipeline.py`
- `docs/operations/ingestion.md`, `promotion-checklist.md`
- `data/pipeline_profiles/` (one example)
- `data/review_learning/` structure

Run (read-only): `promote_case_pipeline.py --dry-run` on a known case if available.

## Agent prompt

> Explain the full case extraction pipeline from PDF URL to canonical YAML. Walk through each script stage, what can fail, and why drafts never auto-promote. Cover `review_draft.py` and the review-learning loop. Explain multi-focus extraction at a high level (`docs/operations/hard-cases.md`). Compare pipeline-in-scripts vs a workflow engine. What's missing for scale to 1000 cases?

---

## What it does

Turns a source PDF into a human-reviewed canonical `CaseRecord`. Machines extract
and gate; a human attests; only then does YAML enter `data/cases/`.

```
scrape_eu_index.py ──▶ data/case_index/    (EU Phase I bulk lane only)
        │                       │
   (manual seed YAML in data/cases/ for Phase II / UK / US)
        │                       │
        └──────────┬────────────┘
                   ▼
        ingest_case.py  ── reads seed/index, fetches+caches PDF, calls LLM
                   ▼
        data/drafts/{jur}/*.draft.yaml          ← never written to data/cases/
                   ▼
   deterministic gates: structural validation + check_source_integrity (quote grounding)
                   ▼
        review_draft.py  (optional LLM triage — skipped in bulk)
                   ▼
        human review (promotion-checklist.md) ── verifies quotes, sets status
                   ▼
        promote_case_pipeline.py --overwrite    ← manual trigger
                   ▼
        data/cases/{jur}/{case_id}.yaml  +  review_learning delta + proposals
```

- **Hard cases (400+ pp):** multiple focus passes (`market_definition`, `theories`,
  `remedies`, `unit_assessment`) → `merge_drafts.py` → one `*.merged.draft.yaml` →
  same gates and human review. See `docs/operations/hard-cases.md`.
- **Stages can fail** at: URL resolution (404/portal/scanned PDF), fetch, extraction
  (cost cap, "no chunks matched", coverage warning, rejected hallucinated quotes),
  integrity (quote not found), validation (bad enums). Any ERROR blocks; promotion
  also blocks on any draft warning.

## Why this way

The pipeline **grew defensively** — each stage was added to stop a specific failure we
actually hit, not designed up front:

- **Drafts ≠ canonical** because a fabricated source URL (`us_microsoft_activision_2023`,
  HTTP 404) shipped into a manual record. Staging + a hard `data/drafts/` boundary makes
  that class of error catchable before it reaches the source of truth.
- **Quote grounding gate** because the LLM hallucinates quotes/pages; `check_source_integrity`
  verifies every `quote_snippet` verbatim against cached text.
- **Manual promotion** because deterministic gates catch *fabrication* but not *misinterpretation*
  (`defined` vs `considered`, complaint→`discussed`, outcome passages linked to markets).
  Those need legal judgment, so a human attests (`spot_checked`/`lawyer_reviewed`).
- **YAML as source of truth** because it is diff-able, reviewable, and git-auditable; Postgres
  is derived. Scripts (not an engine) because volume is low and traceability/local-run matter more
  than orchestration.

## Alternatives considered

- **One-shot LLM → canonical:** rejected — no legal defensibility; fabrication and
  misclassification reach the source of truth.
- **DB-first (Postgres as truth):** rejected — loses git-reviewable diffs; YAML stays canonical.
- **Workflow engine (Temporal/Prefect):** deferred — real value only at sustained high
  throughput / parallel fan-out; today it adds ops burden for no payoff (see Q7).
- **Auto-apply review learnings to prompts:** rejected — unsafe/circular; learnings stay as
  human-approved proposals (see Q5).

## Questions

1. **Dual extraction vs LLM review — replace or keep both?**
   Different jobs. `review_draft.py` (LLM-as-judge) is a *triage accelerator* that prioritises
   human time; dual extraction (`2026-06-25-case-dual-extraction.md`) is a *scalable review model*
   that shrinks the human surface to conflicts only. Dual extraction is the better long-term bet
   and supersedes LLM-as-judge for cases run through it. On spend: dual extraction is ~2× extraction
   cost but removes per-case full review; the judge stage is one extra call. Recommendation: keep the
   optional judge for now (already built), build dual extraction as the scale path, and retire the
   judge once dual extraction proves out. Deferred.

2. **merged_draft vs draft vs case; is bulk EU a separate script?**
   `draft` = one focus pass; `merged.draft` = `merge_drafts.py` output combining many passes for a
   hard case; `case` = promoted canonical record. `run_bulk_extraction.py` *is* a separate, thin
   resumable wrapper that loops `ingest_case.py` over index entries (no review). It should stay a
   wrapper, not be folded into `ingest_case.py`; just document the three artifacts. Now (docs only).

3a. **Is `scripts/cases/` disorganised?**
   Yes, somewhat — discovery (`scrape_*`, `resolve_*`), extraction (`ingest`, `extract`,
   `plan_*`, batch runners), review/promote, and integrity checks are flat in one folder. Worth
   regrouping into subfolders by stage for reviewability, but it is path-churn with no behaviour
   change. Defer to a dedicated restructure spec.

3b. **Should scrape→draft be one trigger?**
   No. Keeping a scraped *bank* of `case_index` records first is correct: it decouples cheap
   scraping from expensive LLM calls, lets you batch and resume extraction, and avoids wasting calls
   when scraping is flaky. The current two-step (scrape, then `run_bulk_extraction.py`) is the right
   shape. Manual final promotion stays. No change.

4. **Is the extraction prompt too big?**
   It is large (`_EXTRACTION_TASK` + `_ACTIVE_RULES_BLOCK` + source-role rules, prepended per call),
   but it is dwarfed by the PDF page text in each request — the prompt is not the dominant input-token
   cost, the document is. It is justified: it carries the grounding rules and is test-guarded against
   rule drift. Not a priority; trim only if a token audit shows it matters. No change.

5. **How robust is the review-learning loop? Auto-apply?**
   It is deterministic and safe but deliberately manual: `create_review_learning_log.py` captures
   draft→canonical deltas, `apply_review_learning.py` aggregates them into *proposals only* — it never
   edits prompts, validators, schemas, or data. Keep it manual: auto-applying LLM-derived corrections
   to the prompt is circular and risks silently degrading extraction. The human-approval checklist +
   eval-benchmark re-run is the right gate. No change (keep checking each time).

6. **Proposals rule candidates look truncated.**
   Confirmed — `apply_review_learning.py._truncate()` cuts the `.md` at 200 chars (`…`). The full,
   untruncated `reusable_rule_candidate` text is already in the sibling
   `review_learning_proposals.yaml`. Fix: either raise/remove the `.md` cap or add a note pointing to
   the YAML. Now (trivial).

7. **When is a workflow engine actually useful? Build it for 1000 cases?**
   Useful when you have sustained high throughput, parallel fan-out (e.g. dozens of hard-case windows
   at once), durable resume across crashes, and central cost/observability. At ~270 cases with a
   human in the loop, scripts win on simplicity and traceability. For 1000 cases the bottleneck is
   *human review*, not orchestration — solve that (dual extraction) before adding an engine. Defer;
   reconsider only if extraction volume, not review, becomes the limit.

8. **Make hard-case orchestration less manual?**
   Today an operator hand-runs ~60 commands (Bayer = 61 component drafts). Incremental wins without a
   full engine: have `plan_extraction_ranges.py` emit a runnable batch plan, let `run_unit_assessment_batch.py`
   cover all focuses (not just `unit_assessment`), and auto-invoke `merge_drafts.py` + `check_review_readiness.py`
   at the end. That gets most of the benefit; a workflow engine is only needed if these runs must be
   parallel and crash-durable. Defer.