# Spec: Non-English decision extraction

## Goal

Enable extraction from non-English EU merger decisions without weakening source
grounding.

The product-facing structured fields remain English: market names, theory names,
commitment summaries, notes, and summaries should be usable in the existing
English case-research UI. Source evidence must stay faithful to the document:
`quote_snippet` remains verbatim in the PDF language, each passage records that
language, and an optional English translation can be stored for reviewer/UI
convenience without becoming the authoritative quote.

This covers the 168 EU index entries with `pdf_language` values other than
English (`deu`, `fra`, `ita`, `nld`, `spa`, `ces`) that were recovered by the EU
Cellar language fallback. It is not a bulk promotion drive and does not attempt
to translate or re-extract already promoted English cases.

Out of scope:

- Machine-translating whole PDFs or storing translated source documents.
- Adding translation fields to product markets, geographic markets, theories, or
  commitments; only source passages need bilingual evidence metadata.
- Changing the canonical language of the product from English.
- Running the non-English backlog. The implementation should make the lane safe;
  backlog execution follows after `extraction_status` is backfilled and the
  substantive queue is known.
- Treating translations as legal authority. Verbatim source-language snippets
  remain the only grounding input for integrity checks.

## Approach

Use the already persisted `CaseIndexEntry.pdf_language` as the routing signal.
Do not add heuristic language detection to the extraction path; resolver metadata
is cheaper, deterministic, and already tied to the selected PDF manifestation.

Add language metadata at the evidence layer:

- `SourcePassage.source_language`: optional ISO 639-2 language code for the
  verbatim `quote_snippet`.
- `SourcePassage.quote_translation`: optional English translation of
  `quote_snippet`.
- `SourceDocument.language`: optional ISO 639-2 language code for the selected
  source document.

Keep `quote_translation` optional because English PDFs and legacy records do not
need it, and because a missing translation is a review inconvenience rather than
an integrity failure. For non-English passages produced by the extractor, the
prompt and schema should request it, and validation should warn when it is absent.

### Extraction prompt and tool schema

Extend the passage item schema used by `extract_case_from_source.py` with
`source_language` and `quote_translation`. The prompt should make the language
contract explicit:

1. Extract analytical fields in English.
2. Copy `quote` verbatim from the supplied source text in its original language.
3. If the source language is not English, set `source_language` to the document
   language and provide a concise English `quote_translation`.
4. Do not translate `quote`; only `quote_translation` may be translated.

Thread the document language into the prompt context when known. For
`ingest_case.py --from-index`, `_build_scaffold_from_index` should copy
`pdf_language` from the index entry onto the scaffold source document. For
canonical/seed-based extraction, use `source_documents[].language` when present;
otherwise default to English-compatible behavior.

The LLM should not decide the source language from scratch when the scaffold
already knows it. If a user passes an explicit `--pdf-url` for a non-index run,
language can remain omitted unless the seed document provides it.

### Validation and grounding

Quote validation remains unchanged in principle: validate `quote_snippet` against
the original cached PDF text, never against the translation. The existing
normalised quote matching already folds accents for approximate matching, so it
should continue to work for Latin-script EU languages.

Add deterministic validation around the new fields:

- `source_language` must be a lowercase ISO 639-2 code when present.
- A non-English source document should produce passages with matching
  `source_language`.
- A non-English passage without `quote_translation` should warn, not block.
- `quote_translation` must not replace or mutate `quote_snippet`.
- Integrity checks should display translation context only as supporting review
  information; quote-not-found decisions must use `quote_snippet`.

### Merge and promotion

Preserve language metadata through merged drafts and canonical promotion.
`merge_drafts.py` deduplicates source passages by quote/page/document; that key
should remain unchanged. When duplicate passages are merged, keep
`source_language` if any duplicate has it and keep the first non-empty
`quote_translation`.

`promote_draft_to_canonical.py` currently strips draft-only `source_role`; the new
language and translation fields are canonical evidence metadata and must not be
stripped. Existing canonical YAML remains valid because the new fields are
optional.

### Queueing

The non-English lane should not create another bulk path. Reuse
`run_bulk_extraction.py` / `ingest_case.py --from-index`, but make the queue able
to select or report by language once `extraction_status` exists:

- Skip `not_applicable` before language handling.
- Treat `pending` + non-English `pdf_language` as runnable after this spec lands.
- Add dry-run reporting that shows language counts, so operators can run a small
  non-English sample before starting a full backlog pass.

This keeps `extraction_status` as the candidate/substantive gate and
`pdf_language` as the prompt/schema routing signal.

### Why not translate first, then extract from English text

Whole-document translation would make extraction easier for the model but breaks
the grounding model: page references and quote snippets would point at translated
text that does not exist in the authority PDF. Extracting from the original text
and storing only passage-level translations preserves the invariant that every
`quote_snippet` can be found in the cached source.

### Why not store translations beside every structured field

The structured record is already English-facing. Duplicating every extracted
field into source-language and English variants would expand the schema without a
clear consumer. The only place where source-language fidelity matters is
evidence, so the bilingual contract belongs on `SourcePassage`.

## Files

| File | Change |
|------|--------|
| `apps/api/app/cases/models/case.py` | Add optional `SourceDocument.language`, `SourcePassage.source_language`, and `SourcePassage.quote_translation` |
| `apps/api/scripts/cases/extract/ingest_case.py` | Copy `pdf_language` from index entries into scaffold `source_documents[].language`; include language in review output where useful |
| `apps/api/scripts/cases/extract/extract_case_from_source.py` | Add language fields to passage tool schema/dataclass/validation/draft emission; pass document language into extraction and unit-assessment prompts; require English structured analysis with verbatim source-language quotes |
| `apps/api/scripts/cases/extract/merge_drafts.py` | Preserve passage language/translation metadata while deduplicating passages |
| `apps/api/scripts/cases/promote/promote_draft_to_canonical.py` | Keep language/translation fields during draft promotion; add warnings for non-English passages missing translations |
| `apps/api/scripts/cases/integrity/check_source_integrity.py` | Keep grounding checks on `quote_snippet`; optionally include `quote_translation` in verbose/report context |
| `apps/api/scripts/cases/extract/run_bulk_extraction.py` | Honor `extraction_status` before language handling and add dry-run language bucket reporting for pending entries |
| `apps/api/tests/test_extract_case_from_source.py` | Cover non-English prompt contract, passage validation, and draft emission |
| `apps/api/tests/test_ingest_case.py` / `apps/api/tests/test_ingest_case_from_index_resolution.py` | Cover scaffold propagation of `pdf_language` to `source_documents[].language` |
| `apps/api/tests/test_merge_drafts.py` | Cover preservation of `source_language` and `quote_translation` through passage dedupe |
| `apps/api/tests/test_promote_draft_to_canonical.py` | Cover canonical preservation and non-English missing-translation warning |
| `apps/api/tests/test_source_integrity.py` | Cover quote validation using verbatim non-English snippets, not translations |
| `apps/api/tests/test_run_bulk_extraction.py` | Cover language/status queue behavior and dry-run language counts if this test module exists in the implementation branch |
| `docs/operations/ingestion.md` | Document the non-English extraction contract and review expectations |

## Verification

```bash
cd apps/api

# Focused unit coverage
.venv/bin/python -m pytest \
  tests/test_extract_case_from_source.py \
  tests/test_ingest_case.py \
  tests/test_ingest_case_from_index_resolution.py \
  tests/test_merge_drafts.py \
  tests/test_promote_draft_to_canonical.py \
  tests/test_source_integrity.py \
  -v

# Include bulk queue tests if/when the implementation adds the module.
.venv/bin/python -m pytest tests/test_run_bulk_extraction.py -v

# Schema and lint checks
.venv/bin/python scripts/cases/integrity/validate_cases.py
.venv/bin/python -m ruff check \
  app/cases/models/case.py \
  scripts/cases/extract/ingest_case.py \
  scripts/cases/extract/extract_case_from_source.py \
  scripts/cases/extract/merge_drafts.py \
  scripts/cases/promote/promote_draft_to_canonical.py \
  scripts/cases/integrity/check_source_integrity.py \
  scripts/cases/extract/run_bulk_extraction.py

# Dry-run a recovered non-English case through the scaffold/cache path.
.venv/bin/python scripts/cases/extract/ingest_case.py \
  --case-id eu_piag_mmbet_rbh_2024 \
  --from-index \
  --focus outcome_metadata \
  --no-claude

# Queue reporting should expose pending language buckets after 5.16 data exists.
.venv/bin/python scripts/cases/extract/run_bulk_extraction.py \
  --jurisdiction eu \
  --dry-run \
  --limit 20
```

Manual checks:

- Inspect one generated non-English draft and confirm `quote_snippet` is verbatim
  German/French/Italian/etc. text from the PDF, `source_language` matches the
  index `pdf_language`, and `quote_translation` is English.
- Confirm `check_source_integrity.py` finds the non-English `quote_snippet` in the
  cache and does not try to ground the translation.
- Promote one reviewed non-English draft to a temporary output path and confirm
  `source_language` / `quote_translation` survive canonical validation.
- Confirm the UI/API still loads legacy cases whose passages do not have language
  fields.

## Rollback

The schema change is additive. To roll back, stop emitting the new fields from
the extractor and remove `source_language`, `quote_translation`, and
`source_documents[].language` from any drafts or canonical YAML generated during
the experiment. Existing records without the fields continue to validate.
