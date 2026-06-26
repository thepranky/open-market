# Meridian ingestion pipeline

Design and operational reference for the AI-assisted case extraction pipeline
implemented in `apps/api/scripts/`. Drafts are written to `data/drafts/` only;
promotion to `data/cases/` requires passing the gates documented here and in
[`promotion-checklist.md`](promotion-checklist.md).

---

## Why this document exists

The current case records (`data/cases/**/*.yaml`) were authored manually. During
the manual authoring of `us_microsoft_activision_2023`, a source document was
added with a plausible-looking title ("FTC ALJ Initial Decision") and a
fabricated URL. The PDF URL returned HTTP 404 — no such ALJ decision was ever
issued in that matter. The `check_source_integrity.py` script was built to make
this class of error detectable; this document ensures the future ingestion
pipeline is designed to prevent it.

---

## Required pipeline stages

Every AI-generated YAML record must pass through the following stages before
being written to `data/cases/`. Stages must run in order; a failure at any
stage must halt the pipeline and produce an actionable error, not silently
continue.

### Stage 1 — Candidate source discovery

The model proposes one or more source documents for the case (complaint, court
opinion, agency decision, etc.). At this stage the model outputs metadata only:
title, document type (`doc_type`), authority, expected URL or search query.

**Do not write to YAML yet.** Proposals are unverified assertions.

### Stage 2 — Fetch and classify

For each proposed source document:

1. Resolve a URL (from the model's proposal, a known authority URL pattern, or
   a search/scrape of the authority's case registry).
2. Perform an HTTP GET. Record status code, content-type, and final URL after
   redirects.
3. Classify the response:
   - `ok_pdf` — HTTP 200, `application/pdf`
   - `ok_html` — HTTP 200, `text/html`
   - `broken` — 4xx or 5xx
   - `timeout` — no response within threshold
   - `portal` — HTTP 200 HTML but URL is a landing page / search portal, not
     the specific document

Treat `broken`, `timeout`, and `portal` as **blocking errors** — do not proceed
to extraction for that document. Log the failure and either discard the document
or flag it for human review.

### Stage 3 — Extract and structure

For documents that passed Stage 2:

- **PDF**: extract text with `pypdf` (available in the venv). Note page
  numbers; store page number with each extracted passage.
- **HTML**: strip script/style blocks; extract visible text.
- **Scanned PDFs** (image-only; `pypdf` returns empty text): do not attempt
  extraction. Flag as `retrieval_status: fallback` and require human review
  before any quote is committed.

### Stage 4 — Quote extraction and validation

The model proposes `source_passages` with `quote_snippet` values. Before
writing each passage:

1. Run `quote_found_in_text(quote, extracted_text)` from
   `scripts/cases/integrity/check_source_integrity.py`.
2. If the quote is **not found**: do not write the passage. Log a WARNING.
   The model may have hallucinated the quote or cited the wrong page.
3. If the quote **is found**: record the page number and section heading if
   available, set `extraction_method: ai_extracted`, and set
   `review_status: unreviewed`.

A passage that fails quote validation must not appear in the committed YAML.
A market definition finding or theory of harm that has no passing passage
should have `definition_status: discussed` (not `defined`) and should carry
an explicit `SOURCE NEEDED` note.

### Stage 5 — Integrity gate

Run `check_source_integrity.py` against the candidate YAML. The pipeline must
exit non-zero (and must not commit) if any **ERROR**-level issues remain:

```bash
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir <draft_dir>
```

Warnings may be reviewed and accepted by a human; errors must be resolved.

### Stage 5a — LLM review / promotion triage (optional)

After Stage 5 (integrity gate) passes, an optional LLM critic stage evaluates the
draft semantically before human promotion.

**Script:** `apps/api/scripts/cases/review/review_draft.py`

**What it checks:**
- Whether each quote actually supports the proposition it is linked to
- Whether `definition_status` values appear correct (`defined` vs. `left_open` vs. `discussed`)
- Whether `source_role` labels are accurate (Commission finding vs. party submission vs. precedent)
- Whether outcome / clearance passages are being misused as market-definition support (general rule: any outcome passage linked to `supports_markets` or `supports_geographic_markets` is a violation)
- Whether geographic markets are missing from the record
- Whether theories of harm are missing or improperly linked
- Whether important market-definition sections appear absent

**Outputs:**
- `data/drafts/{jurisdiction}/{case_id}.{focus}.llm_review.json` — machine-readable
- `data/drafts/{jurisdiction}/{case_id}.{focus}.llm_review.md` — human-readable

**Triage statuses:**
- `auto_verified_candidate` — all passages strong, all statuses correct, no gaps
- `needs_light_review` — minor issues a non-lawyer can check against the source
- `needs_legal_review` — status misclassification or gaps requiring legal judgment
- `blocked` — passages contradict propositions or fundamental structural problems

**What this stage must never do:**
- Write to or modify `data/cases/`
- Mark any passage or record as `lawyer_reviewed`
- Substitute for human or legal review
- Invent new propositions not supported by passages already in the draft

Run standalone or via `ingest_case.py --llm-review`:
```bash
python apps/api/scripts/cases/review/review_draft.py \\
    --case-id eu_sika_dry_mix_2019 \\
    --focus market_definition \\
    --max-cost 0.50
```

---

### Stage 6 — Schema validation

Run `validate_cases.py` against the candidate YAML:

```bash
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir <draft_dir>
```

This validates Pydantic types, enum values, required fields, and referential
consistency between passages and source documents.

### Stage 7 — Human review and commit

The output of Stages 1–6 is a draft YAML file with:
- all source documents verified (HTTP 200, correct content-type)
- all quote snippets confirmed present in extracted text
- `review_status: unreviewed` on every passage and event
- `overall_confidence` ≤ 0.70 until a human sets it higher

A human reviewer changes `review_status` to `spot_checked` or `lawyer_reviewed`
after verifying passages against the source, then commits.

---

## What the pipeline must never do

- **Never write a source document without a verified URL.** A plausible title
  is not evidence that a document exists. A URL must return HTTP 200 with
  appropriate content-type before the document is recorded.

- **Never write a quote snippet that was not found in the extracted text.**
  If the model proposes a quote and `quote_found_in_text` returns False, the
  quote is discarded. Do not adjust the quote to make it pass; locate the
  actual text in the document or omit the passage.

- **Never characterise complaint allegations as adjudicated findings.**
  If the only available source is a complaint, `definition_status` must be
  `discussed` and any proposition notes must make clear that the text reflects
  allegations, not a court or authority finding.

- **Never infer a document exists from the case name or docket number alone.**
  Some proceedings end without a final decision (PI denied, deal abandoned,
  administrative case withdrawn). Check the authority's case registry before
  asserting a document exists.

- **Never link outcome/clearance passages to market entries** (general rule).
  Passages containing language such as "does not raise serious doubts",
  "compatible with the internal market", "cleared", or "authorised" are outcome
  conclusions about the merger result — not market definition findings.
  They must not appear in `supports_markets` or `supports_geographic_markets`.
  They may be retained as unlinked source passages or as evidence for the overall
  outcome. Reason: market definition and merger outcome are related but distinct;
  a clearance conclusion does not prove that a particular product or geographic
  market was defined or considered.
  Stage 3 of the pipeline emits a deterministic warning when this rule is violated.

---

## Source integrity script

`apps/api/scripts/cases/integrity/check_source_integrity.py` is the enforcement point for
Stages 5. It can be run at any time against any directory of YAML files:

```bash
cd apps/api
.venv/bin/python scripts/cases/integrity/check_source_integrity.py --cases-dir ../../data/cases
```

**ERROR** issues block ingestion. **WARNING** issues require human judgment.
The script is also runnable in CI as a pre-merge gate.

---

---

## Central rule registry

`data/pipeline_rules/market_definition_rules.yaml` is the authoritative registry of
market-definition rules that govern both extraction and LLM review.

Each rule entry records:
- `id` — stable slug (e.g. `mdr_001_outcome_no_market_link`)
- `status` — `active` | `deprecated` | `draft`
- `severity` — `error` | `warning` | `info`
- `short_rule` — one-sentence version used in compact prompt sections
- `applies_to` — `extractor` | `reviewer` | `both`
- `deterministic_enforcement` — `true` if `check_source_integrity.py` also enforces it
- `llm_guidance` — fuller explanation included in LLM system prompts
- `examples` — illustrative good/bad cases

**How the registry feeds prompts:**

The `review_draft.py` script maintains an `_ACTIVE_RULES_BLOCK` constant that mirrors
active registry rules in compact form and is appended to `_REVIEW_SYSTEM_PROMPT`.
The `extract_case_from_source.py` script includes `_EXTRACTION_TASK` guidance derived
from the registry (especially mdr_009 for quote cleanliness).

**Tests:**

`apps/api/tests/test_review_draft.py` includes tests that fail if key active rule IDs
(mdr_001 through mdr_010) are absent from `_ACTIVE_RULES_BLOCK` or from the system
prompt. This prevents silent rule drift when the registry is updated.

**Update discipline:**

When adding or modifying a rule: (1) update the YAML registry first, (2) update
`_ACTIVE_RULES_BLOCK` in `review_draft.py` and any relevant prompt text in
`extract_case_from_source.py`, (3) run the tests to confirm coverage.

---

## Section selection and coverage sanity check

### How `--batch-by-section` selects pages

For `focus=market_definition`, the selector first tries **section-path matching** —
chunks whose section heading path contains terms from `_FOCUS_TERMS["market_definition"]`
("relevant market", "market definition", "product market", "geographic market").

If section-path selection returns too few pages, a **neutral page-text fallback** runs:
every non-TOC page is scored by occurrences of neutral EU market-definition signals
(e.g. "left open", "demand-side substitut", "plausible market definition"); high-scoring
pages and their adjacent neighbours are bundled into fallback chunks.

**Supplemental fallback thresholds** — both conditions trigger the fallback independently:
- Absolute: section-path yields < 8 pages (handles short docs where headings were garbled).
- Relative: section-path yields < 25% of the document's non-TOC pages AND the doc has ≥ 30
  non-TOC pages (handles long pharma/tech decisions where market-definition content is
  embedded inside therapeutic-area or competitive-assessment sub-sections that lack
  "market definition" in their heading).

When the relative threshold fires, the fallback chunk cap is doubled (from 8 to 16 groups)
so that scattered sections (e.g. `4.3.3 Other Overlaps`) are not cut off.

### Coverage warning

After selection, `ingest_case.py` computes:
```
coverage_ratio = selected_pages / total_non_toc_pages
```
If `coverage_ratio < 0.25` for a decision with ≥ 30 non-TOC pages, the review report
shows **Status: PASS (coverage warning)** and the console prints:
```
WARN Coverage:  N/M pages (X%) — re-run with --full-market-definition-pass
```

### `--full-market-definition-pass`

Adds this flag to `ingest_case.py`. When set, the page-text fallback is always merged
with section-path results regardless of thresholds, up to `_MAX_FALLBACK_PAGES` additional
pages. Use for long decisions where the relative threshold may still miss sections, or
to get maximum coverage for an unfamiliar document structure.

### Motivation: BMS/Celgene (M.9294)

M.9294 is a 68-page pharma Phase I decision. Market definition is analysed per therapeutic
area under sections named "4.1 Autoimmune diseases", "4.2 Fibrotic diseases", etc.
Only the sub-sections explicitly labelled "4.x.x.1 Market definition" matched the
section-path focus terms, giving 10/65 = 15% coverage. The relative threshold (< 25%)
now triggers supplemental fallback, raising coverage to ≈ 84% of non-TOC pages.

---

## Draft and canonical artifacts

- `data/drafts/{jurisdiction}/{case_id}.{focus}.draft.yaml` — output of a single focus pass via `ingest_case.py`.
- `data/drafts/{jurisdiction}/{case_id}.merged.draft.yaml` — output of `merge_drafts.py`, combining multiple focus passes for a hard case.
- `data/cases/{jurisdiction}/{case_id}.yaml` — the promoted, human-reviewed canonical record.

**Bulk EU Phase I lane** (separate from the single-case path): `scrape_eu_index.py` populates `data/case_index/`; `run_bulk_extraction.py` is a thin, resumable wrapper that loops `ingest_case.py` over index entries with no LLM review. It stays a wrapper by design.

---

## File locations

| Path | Purpose |
|------|---------|
| `ingestion/` | Reserved for future ingestion pipeline code |
| `data/pipeline_rules/market_definition_rules.yaml` | Central rule registry |
| `apps/api/scripts/cases/integrity/check_source_integrity.py` | Source validation gate |
| `apps/api/scripts/cases/integrity/check_source_links.py` | Lightweight HTTP link checker |
| `apps/api/scripts/cases/integrity/validate_cases.py` | Pydantic schema validator |
| `apps/api/tests/test_source_integrity.py` | Unit tests for the gate |
| `data/cases/**/*.yaml` | Canonical case records (human-reviewed) |
| `docs/operations/hard-cases.md` | Multi-pass extraction review + diagnostics |

---

## Multi-focus extraction

Beyond `market_definition`, the pipeline supports `theories`, `remedies`, and
`case_history` focus modes (see `_FOCUS_TERMS` in `extract_case_from_source.py`).

For mega Phase II decisions (800+ pages), a single focus pass covers only a fraction
of the document. The recommended approach for these cases is **section-group iteration**:
run the relevant focus mode over specific page ranges (e.g. `--page-range 64:309`)
and merge results. See `docs/operations/hard-cases.md` for the full design and
the M.8084 Bayer/Monsanto diagnostic that motivated it.
