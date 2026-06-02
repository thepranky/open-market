# Hard-case diagnostics and multi-focus extraction design

This document records diagnostic runs on complex EC decisions that stress-test
the CompMap ingestion pipeline, and captures the design decisions that follow.

---

## Why this document exists

The initial pipeline was designed and validated on Phase I / short Phase II decisions
(100–400 pages). Hard cases — Phase II remedies decisions, innovation-harm cases, and
mega-mergers — expose structural limits: batch page caps, focus-mode coverage gaps, and
document structures where market analysis is embedded inside competitive-assessment
sections rather than in dedicated "Market Definition" headings.

---

## Diagnostic run 1 — M.8084 Bayer / Monsanto (2026-06-02)

### Document facts

| Field | Value |
|-------|-------|
| Case | M.8084 — Bayer / Monsanto |
| Decision type | Article 8(2), conditional clearance (Phase II) |
| Decision date | 2018-03-21 |
| PDF URL | `https://ec.europa.eu/competition/mergers/cases1/202150/M_8084_8063752_13335_9.pdf` |
| Pages | **1,006** |
| Approx tokens | ~627K |
| Seed | `eu_bayer_monsanto_2018` |

**URL discovery note**: The legacy `ec.europa.eu/competition/mergers/cases/decisions/m8084_*.pdf`
pattern issues a 301 → EC case-search SPA homepage for 2018+ decisions. The working path
is `cases1/{batch}/M_{num}_{docSeq}_{pageCount}_{ver}.pdf`. Two other files at the same
`cases1/202150/` batch are remedies follow-ups only (69 pages: modification of commitments;
27 pages: purchaser approval).

### Pipeline run

```
Command: python apps/api/scripts/ingest_case.py \
    --case-id eu_bayer_monsanto_2018 \
    --focus market_definition \
    --batch-by-section \
    --full-market-definition-pass \
    --max-cost 3.00

Stage 1: PASS — 1006 pages cached
Stage 2: 20 batches, 65/978 pages (7%), 44 product markets, 15 geo markets, 249 passages
Stage 3: PASS — structural validation
Stage 4: PASS — 0 errors, 0 warnings
Stage 5: Review written
RESULT: PASS (coverage warning) — 65/978 pages selected
Promotion plan: 0 ready, 42 hold_pending_source_check, 14 context_only, 2 manual_review
```

### Document structure and coverage

| Section | Pages | Content | Pages matched |
|---------|-------|---------|---------------|
| I–IV | 1–49 | Procedure, parties, notified operation, EC jurisdiction | 0 |
| V | 50–63 | Vegetable seeds: general market definition | 6 |
| VIII | 64–309 | 16 vegetable crops (carrot, cucumber, eggplant, garden bean, hot pepper, leek, lettuce, melon, onion, pea, spinach, squash, sweet pepper, tomato, watermelon, + pumpkin) | 6 of 260 |
| IX | 310–341 | Broad-acre seeds (OSR, cotton, wheat) | ~10 |
| X | 342–447 | Traits: HT traits, IR traits, stacks, innovation markets | ~7 |
| XI | 448–674 | Crop protection: herbicides, seed treatment, fungicides, insecticides, bee health | ~22 |
| XII | 675–747 | Digital agriculture market definition + competitive assessment | ~5 |
| XIII–XV | 748–829 | Digital/PPO analysis, non-competition concerns | ~0 |
| XVI | 830–1006 | Commitments / remedies / BASF divestiture (177 pages) | 0 |

### What the extraction got right

- General vegetable seeds market segmentation: per-crop product markets, national geographic scope
- OSR seeds upstream/downstream; cotton seed licensing; wheat seeds
- NSH herbicides: agricultural perennial, all-crops, IVM sub-segments, turf/ornamentals
- HT Systems (combined HT trait + NSH herbicides)
- Seed treatment: nematicidal, insecticidal, treated seeds downstream
- Foliar fungicides (crop/disease basis); foliar insecticides (crop/pest basis)
- Bee health (varroa mites market); microbial crop efficiency
- Digital agriculture / precision farming market definition (national geographic scope)
- Innovation spaces concept (correctly identified as a non-market analytical tool, not a product market)
- Full trait licensing structure: single traits (per crop/functionality), stacks (per crop)

### Critical pipeline gaps

**Gap 1 — Crop-by-crop structure (254 of 260 Section VIII pages missed)**

Each of the 16 vegetable crop sections (carrot, cucumber, eggplant, etc.) uses
the heading "Competitive Assessment > Relevant Segments", not "Market Definition."
The section-path selector finds only the 6-page general vegetable seeds intro.
Each crop alone contains per-country geographic scope findings across 19 EEA member
states, representing potentially 300+ granular market findings.

**Gap 2 — Innovation/R&D markets (163 pages missed)**

Section X (pp.342–447) contains the innovation competition theory — elimination of
R&D competition between Bayer LibertyLink and Monsanto RoundupReady traits. This
is the central theory for traits. All 163 pages of innovation analysis are in
"Competitive Assessment > Innovation" sections with no "market definition" keyword
in the heading.

**Gap 3 — Theories of harm: 0 extracted**

None of the 700+ pages of competitive assessment were covered. The `theories` focus
mode has the correct keywords but still hits the 80-page cap when applied to sections
of this scale.

**Gap 4 — Outcome: unknown**

The Article 8(2) conditional clearance operative paragraph is in the preamble/procedural
sections (pp.1–22), not in any market-definition section.

**Gap 5 — Remedies: 0 extracted**

Section XVI (177 pages) contains the BASF divestiture package, commitments schedule,
and clearance conditions. The `remedies` focus mode exists but was not run.

---

## Multi-focus extraction design

### What already exists

The `_FOCUS_TERMS` dict in `extract_case_from_source.py` already defines four focus modes:
`market_definition`, `theories`, `remedies`, `case_history`. The extraction machinery
(section-path matching, batch-by-section, supplemental fallback) is shared.

**The primary gap is not missing focus modes — it is the 80-page-per-call cap and
the mismatch between focus-term headings and Bayer/Monsanto's embedded section structure.**

### Focus pass 1 — `outcome_metadata`

**Objective**: Extract `outcome`, `procedure_stage`, `decision_date`, `authority_reference`,
and the operative clearance paragraph.

**Implementation**: Re-use existing `case_history` focus mode (`procedure`, `procedural`,
`background`, `notification`, etc.). These terms reliably match the preamble sections.

**New requirement**: A small targeted call over pp.1–30 (the procedural and operative
sections of any EC decision) that maps Article language to existing `Outcome` enum values:

| Article language | Enum value |
|-----------------|------------|
| Article 6(1)(b) | `cleared` |
| Article 6(1)(b) + commitments | `cleared_with_conditions` |
| Article 8(1) | `cleared` |
| Article 8(2) + commitments | `cleared_with_conditions` |
| Article 8(3) | `blocked` |
| Referral / withdrawn | `pending` or `unknown` |

**Page budget**: 30 pages maximum; one Claude call. Cost: < $0.05 per case.

**Output fields added to draft**: `outcome`, `procedure_stage`, `decision_date`,
`authority_reference`, plus a source passage containing the operative paragraph.

**When to run**: As a pre-extraction sub-stage before the main focus pass, or
as a standalone repair script for seeds with `outcome: unknown`.

### Focus pass 2 — `theories_of_harm`

**Objective**: Extract theory name, affected market(s), theory type, Commission conclusion,
and source passages for competitive assessment findings.

**Implementation**: Use existing `theories` focus mode. The keywords already work for
typical decisions. For Bayer/Monsanto, they correctly identify Sections XI–XII competitive
assessment headings.

**Current blocker**: `_MAX_INPUT_PAGES = 80` truncates large competitive assessment sections.
For a 260-page Section VIII or 160-page Section X, the selector finds only the first batch
of matching pages.

**Proposed solution — section-group iteration**:

Instead of one pass over the whole document, iterate through major section prefixes
and run a separate `theories` extraction per section group. For Bayer/Monsanto:

```
Pass A: Section VIII (pp.64–309) — vegetable seeds competitive assessment
Pass B: Section X (pp.342–447) — traits + innovation competitive assessment
Pass C: Section XI (pp.448–674) — crop protection competitive assessment
Pass D: Section XII–XIII (pp.675–772) — digital agriculture competitive assessment
```

Each pass stays within 80-page batches. Results are merged. This is page-range
iteration, not a structural change to the extraction engine — it can be implemented
as a wrapper in `ingest_case.py` using `--page-range start:end` (to be added).

**Extraction schema additions** (already in `_DEFAULT_EXTRACTION_ENVELOPE`):
`theories_of_harm` list, each item:
```yaml
theory_name: string
theory_type: horizontal_unilateral | vertical_foreclosure | innovation | coordinated
affected_markets: [list of market_id refs]
commission_finding: string
source_passage_ids: [list]
```

**Source-role discipline**: Passages from theories extraction must use:
- `commission_assessment` — Commission's own competitive assessment conclusion
- `notifying_party_view` — parties' submissions
- `market_investigation` — third-party responses
- `conclusion` — formal finding operative language

**When to run**: After `market_definition` pass, using the draft's product/geo market IDs
as context to link `affected_markets` references correctly.

### Focus pass 3 — `remedies`

**Objective**: Extract remedy type, divested assets, buyer approval requirements,
behavioural/structural nature, and source passages.

**Implementation**: Use existing `remedies` focus mode (`commitment`, `divestiture`,
`divestment`, `condition`, `behavioural`, `structural`, `remedy`, `remedies`).
These terms reliably match Section XVI in EC Phase II decisions.

**Page budget**: Section XVI in M.8084 is 177 pages, fitting within 3 × 80-page batches.
For most Phase II decisions, the remedies section is 50–200 pages.

**Additional source documents**: For cases with separate remedies follow-up PDFs
(modification of commitments, purchaser approval), those should be registered in
`source_documents` as separate entries with `doc_type: commitments_decision` and
their own `pdf_url`. For M.8084, these are:
- `M_8084_8063748_12985_9.pdf` (69 pages) — modification of commitments
- `M_8084_8063669_13738_3.pdf` (27 pages) — purchaser approval

**Extraction schema** (already in `_DEFAULT_EXTRACTION_ENVELOPE`):
`remedies` list, each item:
```yaml
remedy_type: divestiture | licence | behavioural | hold_separate | access
assets_divested: string
buyer_requirements: string
approval_status: string
source_passage_ids: [list]
```

**When to run**: After `market_definition` and `theories_of_harm` passes, using market IDs
to link which remedy addresses which theory of harm.

### Hard-case page-cap strategy

**Current architecture**: `_MAX_INPUT_PAGES = 80` is a hard cap per Claude API call.
For `batch_by_section`, sections exceeding 80 pages are split at chunk boundaries, but
the selection step only pulls matching pages up to the cap — so large matching sections
get truncated.

**Proposed addition — `--page-range START:END`** flag for `ingest_case.py`:

Restricts extraction to a specific page range within the document before applying
focus-mode selection. This allows section-group iteration without changing the core
extraction engine:

```bash
# Vegetable seeds competitive assessment
python ingest_case.py --case-id eu_bayer_monsanto_2018 \
    --focus theories --page-range 64:309 \
    --output-suffix section_viii

# Traits competitive assessment
python ingest_case.py --case-id eu_bayer_monsanto_2018 \
    --focus theories --page-range 342:447 \
    --output-suffix section_x
```

Draft outputs from section-group passes would go to
`data/drafts/eu/eu_bayer_monsanto_2018.theories.section_viii.draft.yaml` etc.,
and a merge step (new `merge_drafts.py`) would combine them into a single
`eu_bayer_monsanto_2018.theories.draft.yaml`.

**Alternative (simpler, no new flags)**: Run `ingest_case.py` with `--focus theories`
and accept partial coverage for each run, then run again with different seeds.
Not recommended for mega-decisions — too much overlap and noise.

### Crop-loop mode — deferred

For the 16 vegetable seed crops in Section VIII, each crop requires per-country geographic
scope extraction (19 EEA member states × 16 crops × N segments). This would produce
~300+ market entries — an order of magnitude beyond any current case.

Deferring this because:
1. It is Bayer/Monsanto-specific — no other case in the current pipeline has this structure
2. It requires domain-specific crop names hardcoded as iteration keys
3. The current schema does not yet handle per-crop × per-country matrix results well
4. It is better implemented after the general section-group iteration infrastructure exists

When this is built, the right approach is a crop-loop wrapper that iterates through a
list of `(section_prefix, crop_name)` pairs (e.g., `("7", "CARROT")`) and runs one
mini-extraction per crop, then merges results. This is a separate script, not a change
to `extract_case_from_source.py`.

---

## Recommended implementation order

### Slice 1 — `outcome_metadata` targeted pass (low risk, high value)

Estimated effort: ~1 day. No changes to core extraction engine.

1. Add `--focus case_history --page-range 1:30` to `ingest_case.py` (adds `--page-range` flag).
2. Add outcome mapping logic in `ingest_case.py` post-extraction: scan for Article 6/8 language
   in the extracted text, map to `Outcome` enum, write to seed YAML `outcome` field.
3. Run on eu_bayer_monsanto_2018 as first test case.

This immediately resolves Gap 4 (outcome: unknown) for all seeds.

### Slice 2 — `--page-range` flag (enabler for all hard-case passes)

Estimated effort: ~0.5 days. Changes only `ingest_case.py` argument parsing and the
call to `extract_case_from_source.extract_case()`.

1. Add `--page-range START:END` to `ingest_case.py`.
2. Pass `page_range=(start, end)` to `extract_case()`.
3. In `extract_case_from_source._build_chunks()`, skip pages outside the range before
   section-path matching.
4. Output suffix derived from `--output-suffix` arg.

### Slice 3 — `theories` pass on eu_bayer_monsanto_2018

Uses Slices 1+2. Four runs (Sections VIII, X, XI, XII–XIII). Validate that theories of
harm are correctly extracted and linked to product markets from the `market_definition` draft.

### Slice 4 — `remedies` pass on eu_bayer_monsanto_2018

One run covering Section XVI (pp.830–1006). Register the two remedies follow-up PDFs
as additional `source_documents` in the seed. Validate that remedy entries link to
theory-of-harm findings from Slice 3.

### Slice 5 — `merge_drafts.py` utility

Merges multiple section-group draft YAMLs into one. Required before any section-group
case can be promoted. Write only when Slices 3–4 confirm the merge requirements.

---

## Repository hygiene for this case

Generated artifacts for eu_bayer_monsanto_2018 that must NOT be committed:

| File | Reason |
|------|--------|
| `data/drafts/eu/eu_bayer_monsanto_2018.market_definition.draft.yaml` | Generated artifact |
| `data/drafts/eu/eu_bayer_monsanto_2018.market_definition.review.md` | Generated artifact |
| `data/source_text/eu_bayer_monsanto_decision.json` | PDF cache (2.5MB) |
| `data/source_text/debug/eu_bayer_monsanto_2018_section_*.json` | Per-batch debug files |

The seed file `data/cases/eu/eu_bayer_monsanto_2018.yaml` is commit-eligible as the
authoritative case record, but should not be promoted to canonical until at least
the `outcome_metadata` and `theories_of_harm` passes have run successfully.

---

## Adding future hard-case diagnostics

Each new hard case added to this document should record:
- Document facts (URL, pages, tokens, sector)
- Pipeline run command and per-stage result
- Section structure table with pages matched
- Critical gaps identified
- Recommended focus pass sequence
