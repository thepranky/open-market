# DDR-A: Data contracts and source integrity

**Status:** Active reference 
**Scope:** Case research data shape, YAML source of truth, quote grounding

---

## Quick trace (when debugging)

1. YAML on disk → `CaseRecord.model_validate()` via `cases/loader/yaml_loader.py`
2. Promotion gate → `promote_case_pipeline.py` runs `validate_cases`, `check_source_links`, `check_source_integrity`
3. UI → `Evidence.tsx` renders `source_passages` with page-anchored PDF links

Key files: `app/cases/models/case.py`, `app/screening/models/jurisdiction.py`, `app/cases/models/case_index.py`, `docs/data/source-integrity.md`, `scripts/cases/check_source_integrity.py`

---

## 1. What data contracts are

A **data contract** is the agreed shape and meaning of data between producers (extraction scripts, human editors) and consumers (API, web UI, search).

Meridian implements contracts as **Pydantic `BaseModel` classes**. On load, invalid YAML fails loudly (`ValidationError`) instead of breaking the UI silently.

Two validation layers:

| Layer | When | What it checks |
|-------|------|----------------|
| **Schema** (`validate_cases.py`, loaders) | Every load / promotion | Types, required fields, enums, ranges (e.g. `confidence_score` 0–1) |
| **Source integrity** (`check_source_integrity.py`) | Promotion + manual QA | URLs live, quotes appear in document text, page locators plausible |

Schema ≠ truth. A record can pass Pydantic and still contain a hallucinated quote. Integrity catches that.

---

## 2. The three contracts

### `CaseRecord` — canonical case research (`data/cases/`)

Full merger-decision record: parties, markets, theories, remedies, **source-linked evidence**.

Non-obvious: `jurisdiction` (regulator bucket: `EU`/`UK`/`US`), `definition_status` (legal weight), `verification` (attestation on proposition), `SourceDocument` (`pdf_url` → `case_page_url` → `url`), `SourcePassage.page` (printed folio), `SourcePassage.paragraph`, `SourcePassage.quote_snippet` (verbatim), `supports_*` (join to `market_id`/`theory_id`, outcome passages must not link to markets), `review_status: spot_checked` (human check), `confidence_score` (quality meta), `similar_cases` (curated), `ai_summary` (unverified, not substitute).

### `JurisdictionRule` — screening profiles (`data/jurisdictions/`)

Threshold and procedural law for ~60 countries. Loaded in-memory for `POST /jurisdictions/screen`.

Logic (from `_schema.md`):

- `threshold_tests[]` are **OR**'d (any triggers filing)
- `conditions[]` within a test are **AND**'d
- `exclusions` cancel a test; `exceptions` are carve-outs

Non-obvious: `ThresholdCondition.party` (`each_party`, `either_party`, …), `CountQualifier`, `minority_thresholds.standard`, `source_type` hierarchy (`primary_legislation` > `official_guidance` > `practitioner`).

**Different `SourcePassage` type** from cases: uses `quoted_text` + `article_reference` + `supports_conditions` (no `page`/`source_document_id`). Not covered by `check_source_integrity.py` today.

### `CaseIndexEntry` — discovery layer (`data/case_index/`)

Thin record: identity, parties, outcome, one `source_url`, optional `ai_summary`. `extra="forbid"` — no passages, no markets.

Purpose: **coverage map** for cases known to exist but not yet fully extracted (~2000 indexed vs ~270 canonical). Scripts (`scrape_*`, `resolve_*`, `check_case_index_sources.py`) maintain URLs; full extraction promotes to `data/cases/`. See §6 Q7.

---

## 3. `data/` layout

```
data/
├── cases/{eu,uk,us}/       # Canonical CaseRecord — git SoT for research
├── drafts/{eu,uk,us}/      # AI/human staging — never auto-promoted
├── case_index/{eu,uk,us}/  # CaseIndexEntry — discovery backlog
├── jurisdictions/*.yaml    # JurisdictionRule — screening SoT
├── source_text/*.json      # Per-page PDF text cache for integrity checks
├── concepts/               # Shared graph concept nodes
├── evals/                  # Gold fixtures + benchmarks
├── pipeline_profiles/      # Per-jurisdiction extraction config
└── review_learning/        # Human correction deltas for pipeline
```

Pipeline: `PDF → extract → drafts/ → integrity + review → promote → cases/`

---

## 4. How `check_source_integrity.py` works

Per case file:

**Documents** — for each `source_document` referenced by passages:

1. Fetch `pdf_url` (else `case_page_url`, else `url`)
2. ERROR if broken / missing URL; WARNING if `pdf_url` returns HTML or looks like a portal
3. Heuristics: `doc_type` keywords in URL, title tokens (skipped for opaque authority file IDs)
4. Extract HTML/PDF text into `text_map` when passages exist

**Passages** — for each `source_passage`:

1. ERROR if `source_document_id` dangling or `quote_snippet` empty
2. If `data/source_text/{doc_id}.json` exists: search quote on **listed page**, then all pages
   - Found on listed page → INFO
   - Found on different page → WARNING (run `repair_source_passages.py`)
   - Not found anywhere → WARNING (possible hallucination)
3. Else: fuzzy match quote in whole-document `text_map` (`quote_found_in_text` — normalize + fragment windows)

Severity: ERROR blocks promotion; WARNING needs human triage.

UI (`Evidence.tsx`) displays passages and builds `#page=` links from YAML — it does not re-run checks.

---

## 5. Page numbers: printed folio vs PDF index

**Contract says:** `page` = printed folio (`docs/data/source-integrity.md`). Lawyers cite what appears on the document, not the PDF viewer's 0-based counter.

**Cache says:** `data/source_text/` stores `page_number` as PDF reader index (1-based from pdfplumber).

**Pipeline default:** extraction writes PDF index into drafts (`extract_case_from_source.py` → `ep.page_number`).

**Canonical practice:** human promotion corrects to printed folio (EC decisions often ~2-page offset from PDF index — see remediation log in `source-integrity.md`).

**Do not switch canonical YAML to PDF index.** That would make citations wrong for lawyers. The fix is: human spot-check at promotion + `repair_source_passages.py` when cache finds quote on a different page. Longer-term: printed-folio detection in cache builder — see `ROADMAP.md` Phase 4.

---

## 6. Your questions — answers and timing

### Q1. Remove legacy `SourceDocument.url`?

**Answer:** It's the last-resort link when `pdf_url` and `case_page_url` are absent. `check_source_links.py` and integrity still check it. Removing it is a breaking change across older YAML.

**Timing:** **Defer.** Deprecate in docs first; remove only after a migration pass on any records still using `url` alone.

### Q2. Expand `case_type` beyond `"merger"`?

**Answer:** Today it's a free string defaulting to `"merger"`, not an enum. The product is merger-focused; JV/minority cases could use the same schema with different `case_type` values when we extract them.

**Timing:** **Defer** until we actually ingest non-merger cases. Then add a `Literal` or enum + extraction profile — not before.

### Q3. Use PDF reader index instead of printed folio?

**Answer:** **No — your concern about errors is valid, but the solution isn't PDF index in YAML.** Printed folio is the legally meaningful locator. Errors come from pipeline writing PDF index into drafts without human correction. Integrity + repair scripts + spot-check at promotion are the guardrails.

**Timing:** **No schema change now.** Optional cache-side folio parsing → roadmap.

### Q4. How is `confidence_score` determined?

**Answer:** **Not algorithmically scored against source text.** Pipeline defaults `0.70` for `pdf_extracted` passages. Humans raise it (often `0.97`) when spot-checking. It's operational metadata for triage — explicitly excluded from `review_learning` diff corrections.

**Timing:** **No implementation change.** If we want real scores later, tie to integrity match confidence — roadmap.

### Q5. How is `SimilarCase` score/method determined?

**Answer:** **Manually curated in canonical YAML**, not computed at API read time. `method` is a free string (e.g. `graph_feature_overlap`); `score` and `reasons` are author-provided. `similar_cases` is a canonical-only section (not from drafts). Neo4j seed reads them when graph DB is enabled.

**Timing:** **Defer** automated similarity until graph/search quality is a priority (see roadmap). No bug to fix now.

### Q6. Must jurisdiction `SourcePassage.source_type` be `primary_legislation`?

**Answer:** **No.** Default is `primary_legislation` but the enum allows `official_guidance`, `authority_announcement`, `practitioner`. Several jurisdiction YAMLs use non-primary types where statute text isn't available in English.

**Timing:** **No change.** Prefer primary sources when possible; don't force the field.

### Q7. Do we still need `CaseIndexEntry` / `data/case_index`?

**Answer:** **Yes, for now — but it's a product tension, not a separate "indexer platform."** It answers: "what EC/FTC/CMA cases exist that we haven't fully extracted yet?" (~2000 vs ~270). Powers `/indexed-cases`, scrape/resolve scripts, and extraction planning. It does add dual-layer confusion (canonical vs indexed).

**Timing:** **Defer merge/deprecation** to a product decision (ROADMAP 5.2). Short term: keep both layers; improve docs/UX copy. Don't delete `case_index` until we decide to collapse layers.

---

## 7. Why YAML source of truth (not Postgres for cases)

| | YAML (`data/cases/`) | Postgres (pgvector) |
|--|----------------------|---------------------|
| **Role** | Authoritative legal record | Derived search index |
| **Contents** | Full record + passages + provenance | Embeddings only |
| **Review** | Git diffs, PR review | Opaque vectors |
| **Integrity** | Quote-level grounding | N/A |

Postgres exists for semantic search (`index_embeddings.py` → `case_embeddings`, `market_embeddings`, `theory_embeddings`). If Postgres is down, keyword search and direct case reads still work from YAML.

Jurisdictions never touch Postgres — loaded in-memory from YAML.

---

## 8. Alternatives considered

| Alternative | Why not |
|-------------|---------|
| **Cases in Postgres as SoT** | Loses git-auditable verbatim quotes; schema migrations for legal data; harder lawyer review |
| **Single `SourcePassage` type for cases + jurisdictions** | Different locator needs (page/¶ vs article); unification is refactor cost without immediate payoff |
| **Integrity only at extraction time** | URLs rot; quotes drift; need re-check on promotion and periodically |
| **Drop `case_index` layer** | Would lose coverage tracking for ~1700 not-yet-extracted cases |
| **PDF index as canonical `page`** | Wrong citation format for legal users |

---

## 9. Gaps — implement now

Tracked in `ROADMAP.md` Phase 3. Implement via one spec (see prompt below).

1. **PR CI: canonical schema gate** — `validate_cases.py` + `tests/test_schema.py` when `data/cases/` changes (3.1).

2. **PR CI: jurisdiction verification push tier** — `run_jurisdiction_verification.py --tier push` when `data/jurisdictions/` changes (3.2). Today this runs nightly only; PR gate is missing.

3. **PR CI: case_index schema gate** — validate `data/case_index/` against `CaseIndexEntry` when that tree changes (3.3). New `validate_case_index.py` or extend `validator.py`.

4. **Docs cross-link** — link this DDR from `docs/architecture/case-research.md` Data layout section (3.4).

Deferred follow-ups (semantic lint, jurisdiction quote integrity, folio cache, etc.) are in `ROADMAP.md` Phases 4–8.

---

## 10. Top-down summary

```
data/ YAML (git) ──► Pydantic contracts ──► API / UI
        │                    │
        │                    └── check_source_integrity (quotes + URLs)
        │
        └── promote pipeline (drafts → cases, never auto)

Postgres = embeddings only (semantic search), rebuilt from canonical YAML
```

**Trust model:** A market definition is only as strong as its `definition_status` *and* grounded `source_passages` with `review_status: spot_checked`. Contracts enforce shape; integrity enforces provenance.
