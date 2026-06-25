# DDR-A: Data contracts and source integrity

## Before you start

Read/trace:
- `apps/api/app/cases/models/case.py`, `app/screening/models/jurisdiction.py`, `app/cases/models/case_index.py`
- `data/cases/` (one EU example), `data/jurisdictions/_schema.md`
- `docs/data/source-integrity.md`
- `apps/api/app/cases/loader/validator.py`
- `apps/api/scripts/cases/check_source_integrity.py`

Trace one `quote_snippet` from YAML → integrity script → `features/cases/components/Evidence.tsx`.

## Agent prompt

> Walk me through Meridian's data contracts and source-integrity model. Start from `CaseRecord` and `JurisdictionRule` field-by-field (only non-obvious fields). Explain the `data/` folder layout (cases vs drafts vs case_index vs jurisdictions). Trace how `scripts/cases/check_source_integrity.py` validates a quote. Compare why YAML is SoT vs storing cases in Postgres. End with what's missing and what you'd change. Teach bottom-up then summarize top-down.

---

## What it does

_(1–3 sentences)_

## Why this way

_(Chosen design; link to key files)_

## Alternatives considered

_(What else could work; why not)_

## Gaps

_(What's missing or weak — add follow-ups to ROADMAP.md if you act on them)_
