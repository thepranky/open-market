# Review Learning Proposals

Generated: 2026-05-31T18:06:07Z  
Cases reviewed: 1  |  Total corrections: 4  |  Patterns identified: 4

---

## Summary

- **Cases reviewed:** `eu_sika_dry_mix_2019`
- **Total corrections captured:** 4
- **Distinct patterns:** 4
- **Priority breakdown:** 4 low patterns

## High-Priority Proposed Pipeline Changes

> No high-priority pipeline changes in the current corpus.  
> The corrections found are mostly metadata completion and note cleanup — low-risk artefacts of the promotion workflow rather than substantive extraction failures.

## Eval Fixture Candidates

> No eval fixture candidates in the current corpus.

## LLM Review Insights

**Case `eu_sika_dry_mix_2019`** — triage status: `needs_legal_review`

> Multiple product markets carry definition_status "defined" but the Commission's language consistently uses "should be considered as a separate product market for assessing the Transaction" — a working assumption formula that CompMap maps to "considered", not "defined". Additionally, sp_19 is a mixed passage (geographic left-open language combined with an outcome sentence) that warrants reviewer attention, and the UK overlap mentioned in sp_21 context suggests a possible missing geographic market entry for structural reinforcing/strengthening in the United Kingdom.

**Implied proposals (require human judgement before acting):**
- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption language in the LLM review prompt.
- `extraction_prompt_update`: Flag mixed passages (outcome + definition language in the same quote snippet) as a known difficult pattern.

## Low-Priority / No-Action Items

- **`metadata_completion`** (1x, priority: low) → `validator_rule_candidate`  
  Rule: outcome: unknown is a promotion blocker — always resolve against the conclusion section before promoting to data/cases/.

- **`metadata_completion`** (1x, priority: low) → `docs_update`  
  Rule: procedure_stage, case_type, and authority_reference must always be explicitly resolved during the promotion checklist review.

- **`metadata_completion`** (1x, priority: low) → `docs_update`  
  Rule: The metadata block is a required canonical section. It must be added during promotion; its absence from drafts is expected.

- **`note_cleanup`** (1x, priority: low) → `extraction_prompt_update`  
  Rule: Draft-specific language (e.g. 'in this draft') should be avoided in extraction notes so they need no cleanup at promotion time.

## Human Approval Checklist

Review and approve before applying any change to pipeline code or prompts:

- [ ] Review LLM review prompt for `considered` vs `defined` mapping lesson
- [ ] Implement and test validator rules for approved candidates
- [ ] Apply approved docs / promotion checklist updates
- [ ] Consider low-priority extraction prompt updates (note cleanup patterns)
- [ ] Re-run review learning log after any prompt changes
- [ ] Verify eval benchmark scores do not regress after changes
