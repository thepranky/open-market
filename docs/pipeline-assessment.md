# Pipeline Assessment — Pre-Scale Checklist

*Written June 2026. Complete this before running the EC registry scraper on more than ~20 cases.*

The goal: identify gaps in extraction quality, case page UX, and pipeline logic that would compound badly at scale. Fix the high-impact items before corpus expansion; defer cosmetic items.

---

## Known issues (already identified)

### 1. Citation noise — consecutive passages (HIGH)
**What:** A single legal proposition often gets 4–6 source passages that are consecutive paragraphs from the same section. The frontend renders each as a separate source chip, which creates visual noise and doesn't help the researcher (they want the strongest 1–2 citations, not an exhaustive list).

**Root cause:** The extraction prompt doesn't cap passage count per market/theory, and consecutive paragraphs from the same source all pass quote validation independently.

**Fix options:**
- (a) Post-processing: after extraction, merge consecutive passages from the same doc/section into a single passage with a combined quote or range (e.g. "pp. 12–14"). Add a `merge_consecutive_passages()` step to `check_source_integrity.py` or `ingest_case.py`.
- (b) Prompt-level: add instruction "for each market, select the 2–3 passages that most directly state the market definition; do not include supporting context passages unless they add materially different legal content".
- (c) Schema-level: add a `max_passages_per_market: 3` guard in the draft builder.

**Recommended:** (b) + (a) as fallback. Prompt change is reversible; post-processing handles legacy drafts.

---

### 2. `definition_status` misclassification (HIGH)
**What:** LLM sometimes marks a market as `defined` when the authority only `discussed` it or `left_open` a sub-segmentation question. This is the most legally consequential error.

**Observed in:** `eu_sika_dry_mix_2019` (outcome-passage misuse), several Phase I clearances where the authority says "we can leave the exact boundary open".

**Fix:** Add explicit prompt instruction: "If the authority says 'the exact product market definition can be left open' or 'it is not necessary to conclude', the status is `left_open`, not `defined`." This rule already exists in `data/pipeline_rules/market_definition_rules.yaml` — verify it's being injected into the extraction prompt and not just the review prompt.

---

### 3. Geographic market coverage gaps (MEDIUM)
**What:** Geographic markets are frequently extracted incompletely, especially when the decision addresses each product market's geography separately (common in EC Phase I decisions).

**Observed in:** Multiple cases during controlled expansion.

**Fix:** The `geographic_markets` focus pass should explicitly look for patterns like "The geographic market for X is national/EEA-wide/global" across all product market sections, not just the dedicated geographic market section.

---

### 4. Theory outcome labeling (MEDIUM)
**What:** `theory_outcome` field (`dismissed` / `upheld` / `remedied` / `unclear`) is often set to `unclear` when the decision clearly states the theory was dismissed. Also: `remedied` is sometimes set when the theory was actually upheld and then remedied — the distinction matters.

**Fix:** Add to extraction prompt: "A theory is `remedied` only if the authority found competitive harm AND accepted commitments to address it. If the authority found no competitive harm, the outcome is `dismissed` even if the parties offered commitments proactively."

---

### 5. Passage `source_role` misclassification (MEDIUM)
**What:** Passages are sometimes tagged `commission_assessment` when they're actually `party_submission` or vice versa. This affects the legal weight users should give to a passage.

**Fix:** The pipeline profiles already define source roles. Verify that the source-role mapping from `data/pipeline_profiles/*.yaml` is being injected correctly into extraction prompts for all three jurisdiction profiles.

---

### 6. Remedies not linked to individual commitments (LOW-MEDIUM)
**What:** The current case detail page shows remedies as a plain text list with a "source passages not yet linked" notice. Source passages for remedies exist in `source_passages[]` but `supports_commitments` cross-references are often empty.

**Fix:** Extend `_build_extraction_prompt` for the `remedies` focus to explicitly ask the model to link each passage to a specific commitment by ID.

---

### 7. `ai_summary` quality (LOW)
**What:** The AI summary field is generated at extraction time and sometimes just paraphrases the first few passages rather than capturing the legal significance (what was actually decided, what markets were at issue, what outcome).

**Fix:** Add a dedicated summary generation step that runs after all focus passes are merged, with a prompt like: "Write a 3-sentence summary of this merger case for a competition lawyer: (1) what transaction was reviewed, (2) what the main competitive concerns were, (3) what the outcome was and why."

---

### 8. Long Phase II decisions: unit_assessment coverage (LOW)
**What:** The `unit_assessment` focus was designed for crop-by-crop / route-by-route decisions (Bayer/Monsanto style). It works but the output format (flat list of unit findings) doesn't yet surface well in the frontend.

**Fix:** Add a `Unit assessments` section to the case detail page similar to how theories of harm are displayed.

---

## Assessment before next corpus batch

Before running the scraper on a new batch of EC cases, verify:

- [ ] Citation count per market: median ≤ 3, max ≤ 5 (check across 5 recent canonical cases)
- [ ] `definition_status` accuracy: spot-check 3 `left_open` cases against source PDF — confirm authority actually left it open
- [ ] Geographic market completeness: every canonical case with a product market also has at least one geographic market entry
- [ ] `theory_outcome` not defaulting to `unclear` for Phase I cleared cases (most theories in Phase I are `dismissed`)
- [ ] Source passages have `source_role` set (not empty/null) on at least 80% of passages

---

## What to fix before scaling vs. what to fix after

**Fix before scaling to 50+ cases:**
- Citation noise (item 1) — compounds badly; every case gets worse
- `definition_status` prompt rule injection (item 2) — silent legal error
- Geographic market coverage (item 3) — systematic gap that makes cross-case search misleading

**Fix after first 50 cases (can monitor, not block):**
- Theory outcome labeling (item 4)
- Source role classification (item 5)
- Remedies linkage (item 6)
- AI summary quality (item 7)
- Unit assessment frontend display (item 8)

---

*This document should be updated as issues are resolved. Link fixes back to the commit that addressed them.*
