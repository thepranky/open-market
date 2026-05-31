# CompMap — Human Promotion Checklist

Use this checklist when promoting a draft from `data/drafts/` to `data/cases/`.

**What this checklist is not:** It is not legal advice and does not replace professional legal review. `spot_checked` means you have verified the quote and locator. `lawyer_reviewed` means a qualified lawyer has reviewed the passage. These are different things.

---

## Prerequisites — must all be true before opening the draft

- [ ] Deterministic review report exists and shows `**Status: PASS**`  
      `data/drafts/{jurisdiction}/{case_id}.{focus}.review.md`
- [ ] Source integrity check passed (0 errors):  
      `apps/api/.venv/bin/python apps/api/scripts/check_source_integrity.py --cases-dir data/drafts --no-cache`
- [ ] LLM review report read and triage understood:  
      `data/drafts/{jurisdiction}/{case_id}.{focus}.llm_review.md`
- [ ] Source PDF open and accessible for passage verification

---

## Step 1 — Verify source passages

For each `source_passage` in the draft, open the source PDF to the stated `page` and confirm:

- [ ] `quote_snippet` is verbatim — exact characters, including hyphenation and punctuation
- [ ] `page` matches the printed folio (not PDF reader's page counter)
- [ ] `paragraph` or `recital` number matches if present
- [ ] `source_role` correctly identifies who is speaking (see guidance below)
- [ ] `supports_markets` / `supports_geographic_markets` / `supports_theories` links are accurate

If all four are correct, set `review_status: spot_checked`.  
If a quote is wrong or cannot be located, do not promote — fix it first.

### source_role guidance

| Role | When to use |
|---|---|
| `commission_assessment` | The authority is actively analysing a market or competitive effect |
| `conclusion` | The authority's explicit conclusion on a market definition or outcome |
| `precedent` | A reference to a prior decision used as evidence — not a finding in this case |
| `market_investigation` | Evidence from third-party responses, market testing, or surveys |
| `notifying_party_view` | A statement by the merging parties or their advisers |
| `background` | Factual background, industry description, or procedural context |

**Key rule:** Only `commission_assessment` and `conclusion` passages justify formal market definitions. A market entry supported only by `notifying_party_view` or `market_investigation` passages needs a Commission assessment passage or must be downgraded.

### Outcome / clearance passages — general rule

Passages that say "does not raise serious doubts", "compatible with the internal market", "the transaction is cleared", "authorised", or any similar clearance language are `source_role: conclusion` passages about the **outcome** of the competitive assessment.

**They must not appear in `supports_markets` or `supports_geographic_markets` for any entry.** Market definition and merger outcome are related but distinct: a clearance conclusion does not prove that a particular product or geographic market was defined or considered.

- Do **not** link outcome passages to `supports_markets` or `supports_geographic_markets`
- They may be retained in the record as unlinked source passages (no `supports_markets` / `supports_geographic_markets`), or as context for the overall outcome
- They may remain as competitive assessment context, theory/remedy evidence, or unlinked passages with a reviewer note
- A market entry whose **only** support passages are outcome conclusions is under-evidenced; a market entry that has **any** outcome passage in its support list violates this rule
- The deterministic validation in Stage 3 emits a warning when a `source_role: conclusion` passage is linked to a market, or when outcome language is detected in a passage linked to a market

---

## Step 2 — Verify market and geographic market entries

For each product and geographic market entry:

- [ ] `name` matches the terminology used in the decision (not a paraphrase)
- [ ] `definition_status` correctly reflects what the authority actually said (see guidance below)
- [ ] `notes` describe the Commission's reasoning, not the competitive outcome
- [ ] `market_importance` is set and accurate

### definition_status mapping guidance

| What the decision says | definition_status |
|---|---|
| Authority conclusively defines the market scope | `defined` |
| "The exact scope of the market can be left open" / "it is not necessary to conclude on the exact market" | `left_open` |
| "For the purpose of this decision, it will consider the market to be X" or "for assessing the transaction" | `considered` |
| Authority examined the question but did not reach a final ruling | `discussed` |
| Segmentation was analysed but not definitively resolved | `possible_segmentation` |
| Referenced from prior cases only; not assessed in this decision | `precedent_only` |
| Conclusion expected but absent from supplied passages | `unknown` |

**`defined` vs `left_open`:** If the text says the definition was "left open", "not necessary to conclude", or "inconclusive", the status must be `left_open` or `discussed` — not `defined`. "For the purpose of this decision, it will consider X" is a working assumption: use `considered`.

**Geographic markets:** EC phrases like "for the purpose of this decision, it will consider the relevant geographic market national in scope" are working assumptions for the competitive assessment. Use `considered`, not `defined`, unless the Commission explicitly adopts the market as formally defined.

---

## Step 3 — Verify theories of harm

For each theory of harm entry:

- [ ] At least one `commission_assessment` or `conclusion` passage supports it
- [ ] `theory_outcome` accurately reflects the decision (upheld / dismissed / remedied)
- [ ] Any supporting passages are correctly linked in `supports_theories`

---

## Step 4 — Review LLM triage findings

Read the LLM review report and for each flagged item decide:

- **`definition_status_flags`** — check the flagged passage against the source; correct or add a review note
- **`role_misuse_flags`** — verify the passage text; correct `source_role` or document why the current role is right
- **`gap_findings` with confidence `source_backed`** — verify the cited passage; add the missing entry or document why it is not needed
- **`gap_findings` with confidence `speculative`** — exercise legal judgment; the LLM may be wrong
- **`outcome_passage_misuse`** — remove the mislinked passage from product/geographic market support

You do not have to act on every LLM suggestion. Document your decision for items you disagree with in the market's `notes` field.

---

## Step 5 — Set confidence scores and review status

- `review_status: spot_checked` — quote, locator, source_role, and support linkage all independently verified
- `review_status: lawyer_reviewed` — only after a qualified lawyer has reviewed the passage for legal accuracy
- `overall_confidence` on `CaseMetadata` — set to ≤ 0.70 until at least `spot_checked` on all passages; higher only after legal review

Do **not** set `review_status: lawyer_reviewed` on any passage unless a lawyer has reviewed it. The LLM review stage does not count.

---

## Step 6 — Structural checks before promotion

Run these in order. Both must pass cleanly before promoting.

```bash
# From repo root

# 1. Structural validation against draft (enum values, referential integrity)
apps/api/.venv/bin/python apps/api/scripts/ingest_case.py \
    --case-id {case_id} --focus market_definition --no-claude

# 2. Source integrity gate (no errors permitted)
apps/api/.venv/bin/python apps/api/scripts/check_source_integrity.py \
    --cases-dir data/drafts --no-cache
```

If either produces errors, fix them before proceeding.

---

## Step 7 — Promote the draft

Copy the draft to `data/cases/` in the correct jurisdiction subdirectory:

```bash
# Example
cp data/drafts/eu/eu_sika_dry_mix_2019.market_definition.draft.yaml \
   data/cases/eu/eu_sika_dry_mix_2019.yaml
```

Then edit the promoted file:
- Remove the `_draft_note` header line
- Add required canonical fields missing from the draft: `metadata` (with `procedure_stage`, `overall_confidence`), `outcome` if known

---

## Step 8 — Post-promotion validation

Run the full canonical validation after promoting:

```bash
# 1. Pydantic schema validation on canonical records
apps/api/.venv/bin/python apps/api/scripts/validate_cases.py

# 2. Source integrity on canonical records (live URL check)
apps/api/.venv/bin/python apps/api/scripts/check_source_integrity.py \
    --cases-dir data/cases

# 3. Run tests
apps/api/.venv/bin/python -m pytest apps/api/tests/ -q
```

All three must pass before committing.

---

## Step 9 — Commit checklist

- [ ] No files modified under `data/drafts/` in this commit (drafts stay as-is for audit trail)
- [ ] No `review_status: lawyer_reviewed` set unless a lawyer reviewed the passage
- [ ] `overall_confidence` is ≤ 0.70 if only `spot_checked` passages (no legal review)
- [ ] `_draft_note` line removed from the promoted YAML
- [ ] `validate_cases.py` passes cleanly
- [ ] `check_source_integrity.py --cases-dir data/cases` passes cleanly (0 errors)
- [ ] Tests pass
- [ ] Commit message references the case ID and notes what was promoted

---

## Quick reference: what blocks promotion

| Condition | Action required |
|---|---|
| Any `review_status: unreviewed` passage that supports a market or theory entry | Verify and set to `spot_checked`, or remove the passage |
| Any `source_role` not set | Set it |
| Any outcome/clearance passage in `supports_markets` or `supports_geographic_markets` | Remove the linkage |
| Any market entry with `definition_status: unknown` | Find the supporting passage or remove the entry |
| Source integrity ERROR-level issue | Fix before promoting |
| Missing `commission_assessment` or `conclusion` passage for a `defined` market | Add the passage or downgrade the status |
