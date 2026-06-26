# Regroup `scripts/cases/` by pipeline stage (ROADMAP 4.10)

## Goal

`apps/api/scripts/cases/` is a flat folder of 33 scripts spanning every pipeline
stage — discovery, extraction, review, promotion, integrity gates, evals, and
embeddings — with no grouping. It is hard to see what each script does, which stage
it belongs to, or whether efforts overlap (DDR-B Q3a). Regroup the scripts into
stage subfolders so the pipeline is legible from the directory tree.

**This is a move + reference-fix change. No script behaviour changes.** Same inputs,
same outputs, same CLIs. No new modules or abstractions — every edit is a relocated
file, an incremented `__file__` depth, a path string, or an `import` line (see Approach).

In scope:

- Move all 32 scripts (+ `__init__.py`) under `scripts/cases/` into stage subfolders.
- Fix every reference that breaks on the move: runtime sibling imports, subprocess
  path literals, test imports, CI workflows, docker-compose, and operational docs.

Out of scope:

- `scripts/screening/` — separate folder, separate ROADMAP item; untouched here.
- Any consolidation, renaming, or de-duplication of script *logic*. The flat layout
  hides possible overlaps (e.g. several `repair_*` / `validate_*` scripts), but merging
  them is a behaviour change and belongs in its own spec. This change only relocates.
- Converting the scripts to a runnable package (`python -m ...`). Invocation stays
  `python apps/api/scripts/cases/<bucket>/<script>.py`, as today.

## Why the ROADMAP framing needs adjusting

ROADMAP 4.10 proposes four subfolders (`discovery/ extract/ review/ promote/`) and
calls this "path-only churn, no behaviour change." Independent inspection shows two
corrections are needed:

1. **Four buckets don't cover the corpus.** 8 scripts belong to none of those four
   stages — canonical integrity gates, eval/gold tooling, and embedding indexing.
   Forcing them into the four would recreate the "mixed bag" the regroup is meant to
   cure. We add `integrity/`, `evals/`, and `embeddings/`.
2. **It is not path-only churn.** Scripts are coupled four ways that all break on a
   move (see below). The move is mechanical, but the reference-fixing is the real work
   and the risk surface. Calling it "path-only" undersells it.

## Coupling that breaks on a move (the actual risk)

| # | Mechanism | Today works because… | Breaks because… |
|---|-----------|----------------------|-----------------|
| 0 | **Depth-anchored path arithmetic** — **all 32 scripts** derive `_REPO_ROOT` / `_API_DIR` / data dirs from `Path(__file__).resolve().parents[N]` (or `_SCRIPTS_DIR.parent.parent`) with a hardcoded `N` | a script at `cases/X.py` is exactly `parents[2]`=`apps/api`, `parents[4]`=repo root | the file is now one level deeper (`cases/<bucket>/X.py`); every `__file__`-anchored depth resolves one level too high — silently, to the wrong tree |
| 1 | **Runtime sibling imports** — scripts do flat `from pipeline_profile import …`, `from check_source_integrity import …` (11 scripts, ~18 import lines; only the **cross-bucket** subset actually breaks) | when run as a file, the script's own dir is `sys.path[0]`, and every sibling is in that same dir | a sibling that moves to a *different* bucket is no longer on `sys.path` (same-bucket imports keep resolving) |
| 2 | **Subprocess / `_script()` invocations** — `promote_case_pipeline.py` (8 real `subprocess.run` calls) and `run_controlled_case.py` (a `_script(name)` resolver) point at sibling scripts; several other scripts print stale `scripts/cases/X.py` *usage strings* | paths are correct for the flat folder | the target file now lives under a subfolder |
| 3 | **Dotted-package test imports** — 6 test files do `from scripts.cases.<name> import …` | `scripts/__init__.py` + `scripts/cases/__init__.py` make it a package | module path is now `scripts.cases.<bucket>.<name>` and subfolders aren't packages |
| 4 | **Flat test imports** — ~14 test files rely on `conftest.py` putting `scripts/cases` on `sys.path`, then `from ingest_case import …` | `conftest.py` adds exactly `scripts/cases` | the module now lives one level deeper |

**Mechanism 0 is the dominant one** and was the largest gap in the first draft of this
spec: it touches *every* script, not just those with sibling imports, and fails
*silently* (paths resolve to a wrong-but-existing directory rather than erroring). It is
fixed per-script (increment the `__file__`-anchored depth by one). Mechanism 4 is fixed
centrally in `conftest.py`. Mechanisms 1, 2, 3 touch the specific import/path lines that
move.

## Proposed layout

```
scripts/cases/
  __init__.py               # existing
  discovery/                # find sources, resolve PDFs, build/validate the index
    scrape_eu_index.py        # was scrape_ec_registry.py  (see "Discovery naming")
    scrape_uk_index.py        # was scrape_cma_index.py
    resolve_eu_pdf_urls.py    # was resolve_pdf_urls.py
    resolve_uk_pdf_urls.py    # was resolve_cma_pdf_urls.py
    check_case_index_sources.py
    validate_case_index.py
  extract/                  # PDF -> draft, coverage planning, batch orchestration
    extract_case_from_source.py
    ingest_case.py
    pipeline_profile.py
    plan_coverage.py
    plan_extraction_ranges.py
    merge_drafts.py
    run_bulk_extraction.py
    run_controlled_case.py
    run_unit_assessment_batch.py
  review/                   # critic, readiness, review-learning loop
    review_draft.py
    check_review_readiness.py
    create_review_learning_log.py
    apply_review_learning.py
  promote/                  # draft -> canonical
    promote_case_pipeline.py
    promote_draft_to_canonical.py
    bulk_promote_pass.py
  integrity/                # canonical-corpus gates and repair
    validate_cases.py
    check_source_integrity.py
    check_source_links.py
    lint_case_semantics.py
    repair_source_passages.py
  evals/                    # benchmark + gold-fixture tooling
    run_eval_benchmark.py
    evaluate_extraction.py
    create_gold_draft.py
    repair_gold_quotes.py
    validate_gold_quotes.py
  embeddings/               # derived pgvector index
    index_embeddings.py
```

Each new subfolder gets an empty `__init__.py` (so the dotted-package test imports in
mechanism 3 keep resolving).

**Why `evals/`, not `eval/`.** `eval` is a Python builtin; a top-level package named
`eval` (which sibling imports would reference — see Approach) shadows it and is a known
footgun. `evals/` sidesteps that *and* matches the existing `data/evals/` directory, so
the name is consistent with the rest of the repo.

**Resolved placements** (previously flagged, now decided):

- **`validate_case_index.py` + `check_case_index_sources.py` → `discovery/`.** All
  `case_index`-related scripts live in `discovery/`, grouped by the data they concern
  (the index) rather than when they run. `validate_case_index.py` is still wired as a
  data-contract CI gate from its new path.
- **`embeddings/` holds a single script.** Accepted: a one-file folder is fine for a
  systematic, predictable layout, and `index_embeddings.py` is the only
  "YAML → derived Postgres" step (invoked by docker-compose).

## Discovery naming and consolidation

The four EU/UK source scripts were inspected for overlap and naming clarity.

**What each does (they are genuinely distinct — keep them independent):**

| Script | Authority | Job |
|--------|-----------|-----|
| `scrape_eu_index` (was `scrape_ec_registry`) | EU | Build `data/case_index/eu/` from EUR-Lex SPARQL + Cellar FormEx XML |
| `scrape_uk_index` (was `scrape_cma_index`) | UK | Build `data/case_index/uk/` from the GOV.UK search + content API |
| `resolve_eu_pdf_urls` (was `resolve_pdf_urls`) | EU | Fill `pdf_url` on EU index entries via the EUR-Lex Cellar CELEX URL template |
| `resolve_uk_pdf_urls` (was `resolve_cma_pdf_urls`) | UK | Fill `pdf_url` on UK index entries by scraping the GOV.UK case page for the best report PDF |

`resolve_pdf_urls.py` vs `resolve_cma_pdf_urls.py` do the *same step* (populate
`pdf_url`) for *different authorities* with completely different mechanics — a
deterministic CELEX URL template for EU vs HTML scraping of GOV.UK asset links for UK.
The EU one carries a `--jurisdiction` flag defaulting to `eu`, which made it *read* like
a generic multi-jurisdiction resolver, but its logic is EU/Cellar-only — that mismatch
is exactly the "what does this actually do?" confusion to remove.

**Do not consolidate now.** Unifying the two resolvers behind one interface with
per-authority adapters (EUR-Lex, CMA, FTC/DOJ) is already scoped as **ROADMAP 5.10**
("Multi-jurisdiction PDF resolution"). Merging them here would be a behaviour change and
would pre-empt 5.10's design. The scrapers are inherently per-authority (SPARQL vs a
content API) and stay separate regardless. 4.10 is a relocation, not a refactor.

**Rename for a consistent, future-proof scheme** (`<verb>_<jurisdiction>_<noun>`, with
the jurisdiction token matching `data/case_index/{eu,uk}/`):

- `scrape_ec_registry.py` → `scrape_eu_index.py` (drops the lone "registry"; the other
  three already speak "index")
- `scrape_cma_index.py` → `scrape_uk_index.py`
- `resolve_pdf_urls.py` → `resolve_eu_pdf_urls.py` (kills the false-generic name)
- `resolve_cma_pdf_urls.py` → `resolve_uk_pdf_urls.py`

This reads as a matrix — `scrape_{eu,uk}_index`, `resolve_{eu,uk}_pdf_urls` — so a
future `scrape_us_index` / `resolve_us_pdf_urls` (5.10) slots in with an obvious name.
The renames are folded into this spec because the move already `git mv`s these files;
doing both in one motion avoids a second pass. Reference churn is small (script bodies'
usage strings, `docs/operations/ingestion.md`, `ddr-b`, the `resolve_pdf_urls.py`
mention in ROADMAP 5.10, and three memory pointers — all enumerated in Files).

## Approach

**No shared helper, no new abstraction.** An earlier draft proposed a
`_pipeline_paths.py` helper that mutated `sys.path` on import and looked scripts up by
basename, so the move would survive arbitrary future re-bucketing. Rejected: this is the
*stable, final* layout ("what the directory will look like going forward"), so
re-bucket-resilience buys little, and the helper trades explicitness for magic
(import-time side effects, dynamic lookups) — exactly the kind of abstraction CLAUDE.md
says not to add unless the spec requires it. Explicit, greppable paths are the better
long-term call here. Every edit below is either a literal path string or an ordinary
`import` line; nothing resolves at runtime by magic.

The pervasiveness of mechanism 0 (below) is the one honest argument *for* a shared
`_paths.py` (compute `REPO_ROOT`/`API_DIR` once, import everywhere — re-bucketing then
touches one file). Still rejected: importing such a helper needs its own `sys.path`
bootstrap (the same depth problem, one level removed), it adds an import dependency to all
32 scripts, and the per-script `+1` is mechanical and fully transparent. The depth
arithmetic is inherently move-fragile, but this is the *final* layout, so a one-time
per-script fix is acceptable — and verification gates it.

### Depth-anchored paths — increment by one (mechanism 0)

For every script, each path expression anchored on `__file__` gains one level of depth:

- `Path(__file__).resolve().parents[2]` (→ `apps/api`) becomes `parents[3]`.
- `Path(__file__).resolve().parents[4]` (→ repo root / `data/…`) becomes `parents[5]`.
- `_SCRIPTS_DIR = Path(__file__).resolve().parent` then `_API_DIR =
  _SCRIPTS_DIR.parent.parent` gains one more `.parent`.
- **`os.path`-style depth too** — `index_embeddings.py` uses
  `os.path.join(os.path.dirname(__file__), "..", "..")` (not pathlib `parents[N]`), so it
  gains one more `".."`. (Found during implementation; the original audit grepped only for
  `parents[N]`, so the `os.path` form was initially missed.)

**Only `__file__`-anchored depths change.** Expressions derived from an *already-fixed*
anchor stay as-is: `_REPO_ROOT = _API_DIR.parents[1]` (e.g. `ingest_case.py`,
`extract_case_from_source.py`) and `_REPO_ROOT = _API_DIR.parent.parent`
(`promote_case_pipeline.py`) need no edit once `_API_DIR` is correct. And
`run_eval_benchmark.py:230`'s `config_path.resolve().parent.parent` is anchored on a
config-path argument, not `__file__` — leave it.

A per-script edit in **all 32 scripts** (audited list with line numbers in Files). It is
mechanical but must be exhaustive: a missed one fails *silently* — it resolves to a real
but wrong directory rather than erroring. Verification step 3 (`--help` import smoke) and
step 5 (real data-path commands) catch misses.

### Sibling imports — keep flat, add the sibling bucket to `sys.path` (mechanism 1)

Buckets become packages (each gets an `__init__.py` — needed for mechanism 3 anyway).
When a script runs as a file its own bucket dir is `sys.path[0]`, so **same-bucket** flat
imports keep working untouched — only **cross-bucket** imports break.

**Imports stay flat; we do not bucket-qualify them.** Implementation surfaced why: the
library modules import *their own* siblings flat (e.g. `integrity/repair_source_passages.py`
does `from check_source_integrity import …`; `evals/evaluate_extraction.py` does
`from validate_gold_quotes import …`). If a caller imported one as a package submodule
(`from integrity.repair_source_passages import …`), that submodule's internal flat import
would fail because `integrity/` is not on `sys.path`. Keeping every sibling a **top-level**
module — by putting the needed bucket dir(s) on `sys.path` and importing flat — is both
correct and more surgical (no cascade of qualifying internal imports, no dual-identity of a
module imported under two names). So each cross-bucket importer adds one line:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrity"))  # cross-bucket flat siblings
...
from check_source_integrity import quote_found_in_text   # unchanged, flat
```

This `sys.path.insert` is the same idiom the test suite already uses ~14 times. The rule is
**transitive**: a script needs every bucket in its *transitive* flat-import closure on the
path. **Six** scripts need an added bucket dir:

| Importer (bucket) | Needs on path | Why |
|---|---|---|
| `extract/extract_case_from_source` | `integrity/` | imports `check_source_integrity`, `repair_source_passages` |
| `extract/ingest_case` | `integrity/` | imports `check_source_integrity` (+ `extract_case_from_source`, which also needs it) |
| `extract/plan_coverage` | `integrity/` | imports `repair_source_passages` |
| `extract/plan_extraction_ranges` | `integrity/` | imports `repair_source_passages` |
| `extract/run_unit_assessment_batch` | `integrity/` | **transitive** — imports `extract_case_from_source` / `plan_extraction_ranges`, which import integrity modules |
| `review/check_review_readiness` | `extract/` | imports `pipeline_profile` |

`run_unit_assessment_batch` is the transitive case the spec's first draft missed (it has no
*direct* cross-bucket import but pulls in modules that do). The remaining sibling-importers
are same-bucket only and need just their mechanism-0 depth fix: `extract/run_controlled_case`
(→ `pipeline_profile`), and `evals/run_eval_benchmark`, `evals/evaluate_extraction`,
`evals/repair_gold_quotes`, `integrity/repair_source_passages` (→ their own bucket).

### Subprocess / `_script()` invocations — point at the new path (mechanism 2)

Two scripts invoke siblings at runtime:

- **`promote/promote_case_pipeline.py`** — 8 `subprocess.run` calls with hardcoded
  literals (lines 120, 267, 300, 314, 330, 344, 373, 398); update each, e.g.
  `"apps/api/scripts/cases/integrity/check_source_integrity.py"`.
- **`extract/run_controlled_case.py`** — uses `_script(name) = str(_SCRIPTS_DIR / name)`
  with `_SCRIPTS_DIR = Path(__file__).resolve().parent`. Post-move `_SCRIPTS_DIR` is the
  `extract/` bucket, so same-bucket targets (`ingest_case.py`, `plan_coverage.py`,
  `merge_drafts.py`) keep resolving but the cross-bucket
  `_script("check_review_readiness.py")` breaks. Fix: re-anchor the resolver on the
  `cases/` root (`Path(__file__).resolve().parents[1]`) and qualify the cross-bucket call
  → `_script("review/check_review_readiness.py")`. (`run_bulk_extraction.py` and
  `bulk_promote_pass.py` use the same `Path(__file__).parent / "sibling.py"` pattern but
  their targets stay in the *same* bucket, so they need only the mechanism-0 fix.)

Separately, several scripts **print** stale `scripts/cases/X.py` strings as next-step
*hints* (not `subprocess.run`): `ingest_case.py`, `plan_extraction_ranges.py`,
`promote_draft_to_canonical.py`, `run_unit_assessment_batch.py`. These don't break
execution but would mislead operators; update the strings to the bucketed paths.

Explicit and greppable throughout; verification step 6 enforces none are stale.

### `conftest.py` (mechanism 4)

Replace the hardcoded `for _sub in ("cases", "screening")` with a walk that adds
`scripts/cases`, **each of its subdirectories**, and `scripts/screening` to `sys.path`.
Then the flat test imports (`from ingest_case import …`) resolve unchanged — no edits to
those test files. (Adding `scripts/cases` itself also lets the dotted package imports of
mechanism 3 resolve.)

### Dotted test imports — add the bucket (mechanism 3)

Update the 6 test files: `from scripts.cases.<name>` → `from scripts.cases.<bucket>.<name>`.

### CI / compose / docs

Pure path string updates, enumerated in Files.

### Order of operations

1. Add the subfolder `__init__.py` files.
2. `git mv` each script into its bucket — and rename the 4 discovery scripts in the same
   move (preserves history; do all moves in one commit).
3. Increment the `__file__`-anchored depth in all 32 scripts (mechanism 0).
4. Add the `sys.path.insert` line + bucket-qualified imports to the 5 cross-bucket
   importers (mechanism 1); update the subprocess/`_script` paths and stale hint strings
   (mechanism 2); update `conftest.py` (mechanism 4).
5. Update dotted test imports (mechanism 3), CI, compose, docs, memory pointers.
6. Run full verification (below) before opening the PR.

## Files

**New**

- `apps/api/scripts/cases/{discovery,extract,review,promote,integrity,evals,embeddings}/__init__.py` — 7 empty package markers.

**Moved** (`git mv`, 32 scripts) — per the layout above. Four are also renamed in the
same `git mv` (Discovery naming): `scrape_ec_registry.py`→`discovery/scrape_eu_index.py`,
`scrape_cma_index.py`→`discovery/scrape_uk_index.py`,
`resolve_pdf_urls.py`→`discovery/resolve_eu_pdf_urls.py`,
`resolve_cma_pdf_urls.py`→`discovery/resolve_uk_pdf_urls.py`.

**Modified — ALL 32 scripts (mechanism 0, depth `+1`).** Each gets its `__file__`-anchored
depth incremented. Audited anchor lines to bump:

- `parents[2]`→`parents[3]`: `check_review_readiness.py:52`, `check_case_index_sources.py:31`,
  `create_gold_draft.py:47`, `evaluate_extraction.py:73`, `extract_case_from_source.py:38`,
  `lint_case_semantics.py:18`, `plan_coverage.py:34`, `plan_extraction_ranges.py:38`,
  `repair_gold_quotes.py:75`, `repair_source_passages.py:60`, `run_eval_benchmark.py:35`,
  `validate_case_index.py:13`, `validate_cases.py:13`, `validate_gold_quotes.py:39`,
  `bulk_promote_pass.py:31`.
- `parents[4]`→`parents[5]`: `bulk_promote_pass.py:25`, `check_case_index_sources.py:28`,
  `check_review_readiness.py:53`, `check_source_integrity.py:65-66`, `check_source_links.py:23`,
  `create_gold_draft.py:50`, `extract_case_from_source.py:54-55,79`, `pipeline_profile.py:24`,
  `plan_coverage.py:42`, `plan_extraction_ranges.py:45`, `repair_source_passages.py:75`,
  `resolve_pdf_urls.py:27`, `resolve_cma_pdf_urls.py:32`, `run_bulk_extraction.py:35`,
  `scrape_cma_index.py:28`, `scrape_ec_registry.py:39`.
- `_SCRIPTS_DIR.parent.parent` (→ add one `.parent`): `apply_review_learning.py:28`,
  `create_review_learning_log.py:32`, `ingest_case.py:40`, `merge_drafts.py:36`,
  `promote_case_pipeline.py:49`, `promote_draft_to_canonical.py:57`, `review_draft.py:36`,
  `run_controlled_case.py:55`, `run_unit_assessment_batch.py:46`.
- `os.path`-style: `index_embeddings.py:14` (`os.path.dirname(__file__), "..", ".."` →
  add one more `".."`).
- **Leave alone** (derived from a fixed anchor, not `__file__`): `_API_DIR.parents[1]` /
  `_API_DIR.parent.parent` lines, and `run_eval_benchmark.py:230`.

**Modified — scripts (mechanism 1, cross-bucket flat siblings; 6):**
`extract_case_from_source.py`, `ingest_case.py`, `plan_coverage.py`,
`plan_extraction_ranges.py`, `run_unit_assessment_batch.py` (add `integrity/` to
`sys.path`), and `check_review_readiness.py` (add `extract/`). Imports stay flat per the
Approach table.

**Modified — scripts (mechanism 2):** `promote_case_pipeline.py` (8 subprocess literals),
`run_controlled_case.py` (`_script()` re-anchor + qualify one call). Stale **hint
strings** to update (non-functional but misleading): `ingest_case.py`,
`plan_extraction_ranges.py`, `promote_draft_to_canonical.py`,
`run_unit_assessment_batch.py`. Plus self-referential usage strings in the 4 renamed
discovery scripts.

**Modified — tests (dotted imports; 6):** `test_promote_case_pipeline.py`,
`test_promote_draft_to_canonical.py`, `test_check_source_links.py`,
`test_check_case_index_sources.py`, `test_merge_drafts.py`,
`test_extract_case_from_source.py`.

**Modified — tests (constructed script-file path).** `test_run_unit_assessment_batch.py`
builds the script path with `Path(...) / "scripts" / "cases" / "run_unit_assessment_batch.py"`
and **reads the file** (line 726, the `TestNoHardcodedNames` source scan) — this *fails* on
the move until `"extract"` is inserted. (A reference form beyond imports/subprocess: a test
that opens a script by constructed path. Caught by the full suite, not by the grep gates.)
Same file line ~700 also has a stale `…/ingest_case.py` command string in a `WindowResult`
fixture (non-functional, updated for accuracy).

**Pre-existing failures (not caused by this change):**
`test_check_case_index_sources.py::…test_loads_all_thirty_four_entries` and
`test_ingest_case.py::…warns_conclusion_role_linked_to_market` fail identically on a clean
`main` checkout — left untouched (out of scope).

**Modified — test harness (1):** `tests/conftest.py`.

**Modified — CI / compose:**

- `.github/workflows/data-contracts.yml` — `validate_cases.py` →
  `integrity/validate_cases.py`; `lint_case_semantics.py` →
  `integrity/lint_case_semantics.py`; `validate_case_index.py` →
  `discovery/validate_case_index.py`.
- `.github/workflows/api-ci.yml` — `run_eval_benchmark.py` → `evals/run_eval_benchmark.py`.
- `docker-compose.yml` — `index_embeddings.py` → `embeddings/index_embeddings.py`.

**Modified — docs (operational, load-bearing commands):** `CLAUDE.md` (Commands +
Pipeline lines), `README.md`, `docs/operations/ingestion.md` (also the renamed
`scrape_ec_registry`/`resolve_pdf_urls` mentions), `docs/operations/hard-cases.md`,
`docs/operations/promotion-checklist.md`, `docs/architecture/overview.md`,
`docs/architecture/case-research.md`, `ROADMAP.md` (update the in-row paths it cites for
future rows — e.g. `resolve_pdf_urls.py` in 5.10, plus 5.9/5.11 — and mark 4.10 done).

**Modified — pending spec (1):** `docs/specs/2026-06-25-case-dual-extraction.md` (ROADMAP
5.9, still active — not in `completed/`) references `scripts/cases/ingest_case.py`,
`promote_case_pipeline.py`, and a *new* `compare_extractions.py` at the flat root. Update
its paths to the bucketed layout (`extract/ingest_case.py`, `promote/promote_case_pipeline.py`,
`extract/compare_extractions.py`) so 5.9 is implemented in the right place.

**Modified — memory pointers (3):** `MEMORY.md`, `project_bulk_extraction.md`,
`project_cma_ingestion.md` reference the old discovery script names; update so recall
doesn't point at paths that no longer exist.

**Docs left as historical record:** `docs/architecture/decisions/ddr-*.md` (except the
`ddr-b` `scrape_ec_registry` mention, updated above) and `docs/specs/completed/*.md`
describe past states; their `scripts/cases/<flat>.py` mentions are not runnable
instructions. Default: leave them. (Optional accuracy sweep noted in Verification; call
it in review.)

## Verification

```bash
cd apps/api

# 1. Full suite green — exercises both import styles (flat + dotted) post-move.
.venv/bin/python -m pytest tests/ -q

# 2. Lint.
.venv/bin/ruff check .

# 3. Each in-process sibling-import entrypoint imports cleanly (mechanism 1).
for s in extract/extract_case_from_source extract/ingest_case extract/plan_coverage \
         extract/plan_extraction_ranges extract/run_controlled_case \
         extract/run_unit_assessment_batch review/check_review_readiness \
         evals/evaluate_extraction evals/run_eval_benchmark evals/repair_gold_quotes \
         integrity/repair_source_passages; do
  .venv/bin/python scripts/cases/$s.py --help >/dev/null || echo "FAIL $s"
done

# 4. Subprocess chains resolve siblings at their new bucketed paths (mechanism 2).
.venv/bin/python scripts/cases/promote/promote_case_pipeline.py \
    --case-id eu_siemens_gamesa_2017 --focus market_definition --dry-run

# 5. The exact commands CI / compose / CLAUDE.md run, at their new paths.
.venv/bin/python scripts/cases/integrity/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/lint_case_semantics.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/integrity/check_source_links.py
.venv/bin/python scripts/cases/discovery/validate_case_index.py --index-dir ../../data/case_index
.venv/bin/python scripts/cases/evals/run_eval_benchmark.py \
    --config ../../data/evals/benchmark.market_definition.ci.yaml

# 6. No stale flat references remain anywhere (must return nothing).
cd ../..
grep -rnE "scripts/cases/[a-z_]+\.py" --include="*.py" --include="*.yml" \
    --include="*.yaml" --include="*.md" . | grep -v node_modules \
  | grep -vE "scripts/cases/(discovery|extract|review|promote|integrity|evals|embeddings)/" \
  | grep -v "specs/2026-06-25-regroup-cases-scripts"
# (remaining hits, if any, are intentional historical mentions in ddr-*/completed specs)

# 7. Old discovery names are fully retired (must return nothing).
#    Excludes this spec, which documents the renames as part of its rationale.
grep -rnE "scrape_ec_registry|scrape_cma_index|resolve_pdf_urls|resolve_cma_pdf_urls" \
    --include="*.py" --include="*.yml" --include="*.yaml" --include="*.md" . \
  | grep -v node_modules | grep -v "specs/2026-06-25-regroup-cases-scripts"
```

Manual: confirm `git log --follow` traces a moved/renamed script's history (proves
`git mv`, not delete+add).

## Rollback

Self-contained — no data or schema migration; the scripts only read YAML. To revert:
`git revert` the move commit. Because all moves, renames, and reference fixes land
together, the change is atomic — there is no half-moved state to clean up.
