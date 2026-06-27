# Hard-case merged-draft review

Use this checklist when reviewing a merged draft assembled from multiple extraction
passes on a long decision (typically 400+ pages). Run it **before**
[`promotion-checklist.md`](promotion-checklist.md).

Hard cases require multi-pass extraction: multiple `market_definition` focus passes,
`theories` passes, `unit_assessment` batches, `remedies` passes, and a final
`apps/api/scripts/cases/extract/merge_drafts.py` run. The pipeline was designed for Phase I / short Phase II
decisions; mega-mergers expose batch page caps and embedded market-analysis
structures. See **Multi-focus design** at the end of this doc.

---

## 0 — Pre-flight: understand what was extracted

Before reviewing any field, read the merge report embedded at the top of the draft
or the last `apps/api/scripts/cases/extract/merge_drafts.py` console output. Confirm:

- [ ] Number of input drafts matches expectation (outcome + market + theories +
      remedies + unit_assessments)
- [ ] No input draft was accidentally omitted (check file-count vs. what
      `apps/api/scripts/cases/extract/run_unit_assessment_batch.py` reported as pass/skipped_existing)
- [ ] Deduplication counts are plausible — heavy dedup (>10% of units or passages
      collapsed) often signals overlapping windows and warrants spot-checking
- [ ] Back-ref synthesis ran: each theory entry in `theories_of_harm` should have
      at least one `source_passage_ref` if the corresponding passages have a
      `supports_theories` field

---

## 1 — Metadata and outcome

- [ ] `case_id`, `case_name`, `authority`, `jurisdiction`, `sector` match the
      decision header verbatim
- [ ] `outcome` is one of `cleared`, `cleared_with_conditions`, `prohibited`
- [ ] `decision_date` matches the ISO date at the top of the decision (not the
      notification date or Article 6 opening date)
- [ ] `procedure_stage` is `phase2` for all Article 8(2) decisions; `phase1` for
      Article 6(1)(b) decisions with commitments
- [ ] `source_documents` contains the main decision PDF URL, not a remedies
      follow-up or a press release; confirm the URL resolves to the correct document

---

## 2 — Market definition entries

### 2a — Aggregate vs. specific entries

Multi-pass extraction on long decisions often produces **aggregate draft artifacts**
alongside the specific crop/route/country entries that represent actual defined
markets. Aggregate entries look like:

- "Vegetable seeds" (when the Commission defined markets per crop)
- "Geographic market for vegetable seeds" (when geographics are per crop/country)
- "Crop protection products" (when the Commission defined by crop/pest)

For each market entry:

- [ ] Check whether the Commission formally defined *this specific* market or
      whether it assessed the sector at a more granular level
- [ ] If the entry is aggregate and the Commission's actual definitions are at a
      finer level, set `definition_status: discussed` and add a note explaining
      the aggregate nature; do not `defined`
- [ ] If the Commission explicitly said "left open", use `left_open`; if it said
      "for the purpose of this decision, we consider…", use `considered`

### 2b — Orphaned entries (no source passage refs)

Any market entry with `source_passage_refs: []` is a candidate for removal unless
it is either (a) a recognized aggregate artifact with a clear note, or (b) a market
mentioned in the decision whose passages were not captured in any component draft.

For each orphaned entry:

- [ ] Open the source decision and search for the market name
- [ ] If the Commission discussed it and reached a conclusion, add the passage and
      set the correct `definition_status`
- [ ] If the market is not in the decision, remove the entry

### 2c — `definition_status: unknown` — zero tolerance

No entry should remain at `unknown` after the pre-review cleanup. If any remain:

- [ ] Locate the Commission's actual language in the source decision
- [ ] Apply the mapping table in `promotion-checklist.md` Step 2
- [ ] If the text cannot be found (passage genuinely missing), use `discussed` with
      a note explaining what evidence is absent

---

## 3 — Unit assessment findings

Unit assessments (crops, routes, indications) are the primary output of
`unit_assessment` focus runs. Review them as a block, not one-by-one.

### 3a — Coverage gap check

- [ ] Compare the number of named unit assessment labels against the number of
      section headings in the decision's table of contents
- [ ] Flag any crop/route/country that appears in the ToC but has no
      `unit_assessments` entry
- [ ] For each missing section, check whether: (a) the batch runner reported it
      as `empty` (market definition content, no SIEC findings — acceptable), or
      (b) it was skipped/failed without a retry
- [ ] Empty results on pages that are purely market definition or procedural text
      are correct; empty results on pages containing SIEC tables warrant a retry

### 3b — Boundary contamination

Extraction windows do not align perfectly with crop section boundaries. A window
that starts partway into Section 12 (Leek) may capture findings from Section 13
(Lettuce). Signs of contamination:

- [ ] A unit assessment with two different crop labels in its `unit_label` field
      (e.g., "Leek / Lettuce")
- [ ] A finding whose `segment` belongs to a different crop than the parent
      `unit_label`
- [ ] The merge report shows many `duplicate finding(s) collapsed` for a single
      unit — may indicate two windows covered the same crop

Boundary contamination findings are usually harmless if both the contaminator
and contaminee are correctly labelled, but verify:

- [ ] The finding's `segment` and `geography` are consistent with the stated crop
- [ ] The `conclusion` (siec/no_siec) matches what the decision says for that
      specific segment × geography combination

### 3c — Conclusion distribution sanity check

For decisions involving many affected markets (e.g., merger of two seed majors),
the findings distribution should roughly match what the decision's remedies section
describes.

- [ ] Count of `siec` findings ≈ number of geographic markets listed in the
      Article 8(2) remedies attachment or remedies section
- [ ] Count of `no_siec` findings plausible given the number of crops × segments ×
      countries assessed with no concern
- [ ] Small number of `unknown` findings acceptable (window ended before conclusion)
- [ ] Very high `unknown` count (>5% of total findings) signals missing retry windows

### 3d — Source passage grounding for unit findings

Unit assessment passages are often short table rows or sentence fragments rather
than full paragraphs. Spot-check at least 5 findings from different unit labels:

- [ ] Open the source PDF to the stated `page_number`
- [ ] Verify the quoted text appears verbatim on that page
- [ ] Verify the `segment` and `geography` in the finding match the table row or
      paragraph being cited

---

## 4 — Theories of harm

- [ ] Each theory has at least one `commission_assessment` or `conclusion` passage
- [ ] `theory_outcome` is accurate: `upheld` for SIEC findings, `dismissed` for
      cleared concerns, `remedied` for commitments
- [ ] Innovation theories (R&D competition, pipeline overlap): confirm the decision
      actually named these as theories of harm rather than as market context;
      innovation space analysis in long decisions is often discussed at length
      without being a formal theory of harm
- [ ] Back-refs populated: `source_passage_refs` on each theory should match at
      least one passage's `supports_theories` field (back-ref synthesis fills this
      automatically during merge)

---

## 5 — Commitments and remedies

- [ ] Each commitment/remedy entry corresponds to an actual condition in the
      operative part of the decision (not a proposed remedy that was rejected)
- [ ] `remedy_type` accurately reflects the instrument (divestiture, behavioural
      condition, FRAND commitment, etc.)
- [ ] Source passages cite the decision's Annex or conditions attachment, not
      the Commission's analysis of why the remedy is sufficient
- [ ] If the case has a BASF-type structural divestiture: confirm the buyer is
      named and the scope (what is divested) matches the decision text

---

## 6 — Source passages

### 6a — Deduplication quality

The merge process collapses near-identical passages. After dedup:

- [ ] No two `source_passages` contain substantially identical text (more than 80%
      overlap) — if so, the dedup threshold was not tight enough; flag for manual
      merge
- [ ] `passage_id` sequence is contiguous (sp_1, sp_2, … sp_N with no gaps) after
      the merge — gaps indicate that some cross-refs may be broken

### 6b — Role misuse

The most common role misuse in hard cases:

- Using `commission_assessment` for Notifying Party arguments that the Commission
  is *refuting* — those are `notifying_party_view`, even if the Commission quotes
  them verbatim before dismissing them
- Using `conclusion` for intermediate analysis steps — `conclusion` should only
  apply to the authority's final finding on a market or a theory
- Using `background` for passages that actually contain Commission analysis —
  `background` is for industry descriptions, regulatory context, and third-party
  factual submissions with no Commission assessment attached

---

## 7 — Promotion blockers

Do not proceed to `promotion-checklist.md` until all blockers are resolved:

| Blocker | Resolution |
|---------|-----------|
| Any `definition_status: unknown` | Find source quote; set correct status |
| Any aggregate draft artifact with `definition_status: defined` | Downgrade to `discussed` or `left_open` |
| Unit assessment findings with `conclusion: unknown` > 5% of total | Check for missing windows; retry if needed |
| Source integrity ERROR | Fix passage quote or locator |
| Merged draft has fewer theories of harm than the decision's remedies attachment lists | Check for missed extraction windows in the relevant page range |
| `metadata` field absent | Normal for draft — fill at promotion using seed YAML |
| Back-ref synthesis produced 0 theory refs despite theories being present | Verify `supports_theories` is populated on relevant passages |

---

## 8 — Bayer/Monsanto-specific notes (M.8084, 2018)

These notes are permanent references for this specific case.

**Merged draft location:**
`data/drafts/eu/eu_bayer_monsanto_2018.merged.draft.yaml`

**Component draft counts:** 61 input drafts (1 outcome + 1 market_definition +
10 theories + 4 remedies + 45 unit_assessments including retry windows).

**Unit assessment batch:** 33 windows planned; 25 pass, 4 skipped_existing, 1
correctly empty (broad_acre_crop_traits pp.353-359 = market definition content,
sections 1.4.2-1.4.8, no SIEC findings), 3 failed → resolved by splitting at
section boundaries (the `{}` failure pattern occurs when a window spans multiple
section paths, causing chunk fragmentation; single-section windows reliably succeed).

**Key aggregate artifacts (do not promote as `defined`):**
- `pm_2: Vegetable seeds` — `discussed`; Commission defined markets per crop (pm_1)
- `gm_1: Geographic market for vegetable seeds` — `discussed`; Commission assessed
  geographic scope at crop/segment/country level, never as a single aggregate market

**Clear definition outcomes (source-verified):**
- `pm_3: Microbial crop efficiency products` — `left_open` (recital 2333, p.656)
- `gm_15: Bee health varroa mites` — `defined` as national (recital 2389, p.668)

**Promotion blockers remaining as of 2026-06-03:**
- `unit_assessments` list is not in the canonical `CaseRecord` Pydantic schema;
  schema extension required before promotion
- `metadata` block must be written into the seed file before the promotion pipeline
  runs
- Human legal review of 413 unit_assessment findings not yet done
- `eu_bayer_monsanto_2018.yaml` is a diagnostic seed — do not overwrite it with the
  merged draft until legal review is complete
