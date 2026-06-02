# Review Learning Proposals

Generated: 2026-06-02T01:18:04Z  
Cases reviewed: 5  |  Total corrections: 13  |  Patterns identified: 4

---

## Summary

- **Cases reviewed:** `eu_apple_shazam_2018`, `eu_coca_cola_costa_2018`, `eu_daimler_geely_smart_2020`, `eu_facebook_whatsapp_2014`, `eu_sika_dry_mix_2019`
- **Total corrections captured:** 13
- **Distinct patterns:** 4
- **Priority breakdown:** 2 low, 2 medium patterns

## High-Priority Proposed Pipeline Changes

> No high-priority pipeline changes in the current corpus.  
> The corrections found are mostly metadata completion and note cleanup — low-risk artefacts of the promotion workflow rather than substantive extraction failures.

## Eval Fixture Candidates

> No eval fixture candidates in the current corpus.

## LLM Review Insights

**Case `eu_apple_shazam_2018`** — triage status: `needs_legal_review`

> Multiple issues require legal judgment: (1) all five product markets are missing geographic market counterparts despite the decision's text referencing EEA-wide or global geographic assessments for each market; (2) sp_3 and sp_9 and sp_12 are pure "left-open because no competitive harm" outcome passages yet are linked to market entries; (3) source_role is "not_set" for all 13 passages, requiring assessment; (4) definition_status for pm_2 ("considered") may be too weak given the Commission's explicit framing of the "narrowest relevant product market."

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

**Case `eu_coca_cola_costa_2018`** — triage status: `needs_legal_review`

> Multiple outcome/clearance passages (sp_2, sp_7, sp_10, sp_14, sp_27, sp_29, sp_31) are linked as primary support for product markets and theories of harm; several geographic markets (gm_2, gm_3) reference passage IDs not supplied in this batch (sp_37–sp_41); theory entries carry no supporting passages; and role misuse is present where conclusion passages are labelled commission_assessment. These issues require legal judgment to resolve.

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

**Case `eu_daimler_geely_smart_2020`** — triage status: `needs_legal_review`

> Multiple structural issues: sp_1 and sp_2 are introductory overlap-identification passages with no substantive market definition analysis; sp_6 and sp_9 are mixed left-open/outcome passages linked to markets without source_role set; no geographic markets are captured despite clear geographic analysis in the decision (EEA-wide vs national, Sweden affected market); pm_1 and pm_2 have unknown definition_status and incomplete_source flags requiring legal judgment; duplicate content across sp_1/sp_2 and sp_6/sp_9 needs review.

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

**Case `eu_facebook_whatsapp_2014`** — triage status: `needs_legal_review`

> Several passages require legal judgment: sp_4 and sp_11 contain pure or near-pure outcome/clearance language linked to market entries; sp_9 is a mixed left-open/outcome passage with a clearance rationale; the definition_status of pm_1 as "considered" is borderline given the Commission's explicit conclusion wording; and sp_25 appears to be a copy-paste of a gm_1 passage repurposed for gm_2 without a distinct source. Additionally, sp_29 is misplaced (geographic advertising market evidence appearing in a consumer communications apps context passage), and there are no theories of harm drafted despite the decision assessing effects.

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

**Case `eu_sika_dry_mix_2019`** — triage status: `needs_legal_review`

> Multiple product markets carry definition_status "defined" but the Commission's language consistently uses "should be considered as a separate product market for assessing the Transaction" — a working assumption formula that CompMap maps to "considered", not "defined". Additionally, sp_19 is a mixed passage (geographic left-open language combined with an outcome sentence) that warrants reviewer attention, and the UK overlap mentioned in sp_21 context suggests a possible missing geographic market entry for structural reinforcing/strengthening in the United Kingdom.

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

## Low-Priority / No-Action Items

- **`metadata_completion`** (5x, priority: medium) → `docs_update`  
  Rule: procedure_stage, case_type, and authority_reference must always be explicitly resolved during the promotion checklist review.

- **`metadata_completion`** (5x, priority: medium) → `docs_update`  
  Rule: The metadata block is a required canonical section. It must be added during promotion; its absence from drafts is expected.

- **`note_cleanup`** (2x, priority: low) → `extraction_prompt_update`  
  Rule: Draft-specific language (e.g. 'in this draft') should be avoided in extraction notes so they need no cleanup at promotion time.

- **`metadata_completion`** (1x, priority: low) → `validator_rule_candidate`  
  Rule: outcome: unknown is a promotion blocker — always resolve against the conclusion section before promoting to data/cases/.

## Human Approval Checklist

Review and approve before applying any change to pipeline code or prompts:

- [ ] Review LLM review prompt for `considered` vs `defined` mapping lesson
- [ ] Implement and test validator rules for approved candidates
- [ ] Apply approved docs / promotion checklist updates
- [ ] Consider low-priority extraction prompt updates (note cleanup patterns)
- [ ] Re-run review learning log after any prompt changes
- [ ] Verify eval benchmark scores do not regress after changes
