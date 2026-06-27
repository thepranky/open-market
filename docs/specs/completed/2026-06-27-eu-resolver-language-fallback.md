# Spec: EU resolver language fallback

## Goal

Stop the EU Cellar resolver from returning false `not_found` for decisions that
exist in EUR-Lex but are not published in English.

## Context

PR #30 / #31 resolved `pdf_url` for case-index entries. The EU adapter
(`EuCellarResolver`) derives the CELEX id `3{year}M{number}` and requests one
fixed URL: `…/resource/celex/{CELEX}.ENG.pdf`. When that 404s it reports
`not_found`.

168 EU index entries came back `not_found`. Investigation showed this is wrong:
the decisions **are** in Cellar, but only in their authentic language. EC
simplified / Phase I clearances are frequently published only in the language of
the notifying parties (German, French, Italian, Dutch, …) with a cover line such
as *"Nur der deutsche Text ist verfügbar und verbindlich."* The decision PDFs
even cite the same CELEX our resolver derived.

Confirmation:

- `…/celex/32023M10969.ENG.pdf` → 404, but `…/celex/32023M10969.DEU.pdf` → 200
  `application/pdf` (XXXLUTZ / HOME24).
- A random sample of 10 of the 168 `not_found` entries all resolved in a
  non-English language (DEU/FRA/ITA/NLD): the misses are language, not absence.

So the resolver correctly derives the CELEX and correctly reaches Cellar; it just
asks for a language manifestation that does not exist.

## Approach

Change `EuCellarResolver.resolve` to try a **prioritised language chain** on the
derived CELEX instead of English only:

1. Build the CELEX exactly as today (`3{year}M{number}`); Phase II / appeal
   outcomes still short-circuit to `manual_required` with no HTTP.
2. Request `…/celex/{CELEX}.{LANG}.pdf` for each language in priority order,
   stopping at the first `200` + `pdf` content-type. English is tried first so an
   English manifestation is still preferred when one exists.
3. If no language returns a PDF, report `not_found` (genuinely not in Cellar).
4. Record the resolved language in the resolution `reason`
   (e.g. `cellar_celex_32023M10969_deu`) so dry-run reports show it. No
   `CaseIndexEntry` schema change — consistent with the v1 "write only `pdf_url`"
   decision. Durable per-entry language capture, if wanted later, is a separate
   schema-change PR.

Language priority (ISO 639-2 / Cellar codes), common authentic languages first
then the remaining official EU languages:

```
ENG, FRA, DEU, ITA, NLD, SPA, POL, POR, SWE, DAN, FIN, CES, ELL, HUN,
RON, BUL, HRV, SLK, SLV, EST, LAV, LIT, GLE, MLT
```

Early-exit means the common case costs 1–3 HEAD requests; a genuine miss costs
one HEAD per language (bounded, rate-limited, acceptable for a backlog job).

### Why not query Cellar manifest metadata instead

A metadata/SPARQL lookup of available languages would avoid trying each suffix,
but adds a second request shape and parser for a bounded, well-understood loop.
The language chain with early-exit is smaller and fully testable with the
existing injected `Fetcher`. Revisit only if request volume becomes a problem.

### Why English-first

The product is English-facing. When the Commission published an English
manifestation we want it; the authentic-language version is the fallback, not the
preference.

## Files

| File | Change |
|------|--------|
| `apps/api/scripts/cases/discovery/pdf_resolvers.py` | EU resolver tries a language chain; `_CELLAR_TEMPLATE` parameterised by language; resolved language in `reason` |
| `apps/api/tests/test_pdf_resolvers.py` | Tests: English preferred when present, non-English fallback, all-language miss → `not_found`, Phase II still short-circuits with no HTTP |
| `docs/operations/ingestion.md` | Note the EU resolver tries non-English manifestations |
| `ROADMAP.md` | Note the 5.10 follow-up |

## Verification

From `apps/api/` with `.venv` active:

```bash
.venv/bin/python -m pytest tests/test_pdf_resolvers.py -v
.venv/bin/ruff check scripts/cases/discovery/pdf_resolvers.py

# Previously-missed cases now resolve (dry-run, no writes)
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction eu --dry-run --case-id eu_xxxlutz_home24_2023
.venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \
  --jurisdiction eu --dry-run --limit 10
```

Manual check: for one non-English resolved case, open the `pdf_url` and confirm
it is the decision in its authentic language (not a wrong document).

The actual data re-run that writes the recovered `pdf_url`s is a separate commit /
PR, mirroring #31 (code first, then data).

## Rollback

Revert `EuCellarResolver.resolve` to the single `.ENG.pdf` request. No schema or
data migration is involved (resolved language lives only in the report `reason`).
