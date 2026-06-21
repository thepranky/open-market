# CompMap — 5-Day Deployment Sprint

*Written 2026-06-17. Last updated 2026-06-18.*

---

## North star

Ship a working, accurate, trustworthy threshold screening tool that competition lawyers can use to check merger filing obligations. Everything else is secondary until this is solid.

**Users**: competition lawyers doing merger filing analysis  
**Core promise**: Describe a deal → get a jurisdiction-by-jurisdiction filing obligation summary with specific legal citations they can rely on

---

## Day 1 — Threshold screening page ✅ DONE

### ✅ 1a. Expand jurisdictions: 36 → 47

Added 11 new jurisdiction YAMLs with full schema (thresholds, legal basis, review periods, fees, gun-jumping, FDI screening):

`fi` Finland · `dk` Denmark · `pt` Portugal · `cz` Czech Republic · `hu` Hungary · `ro` Romania · `gr` Greece · `cl` Chile · `pe` Peru · `ph` Philippines · `id` Indonesia

All URLs fixed and verified. Two (Romania, Peru) are unreachable from our IP (government servers blocking the range) but URLs are correct. Model schema extended: `CountQualifier` now accepts `count_of_parties`; `ReviewPeriods.phase_2` is optional; `day_type` accepts `months`.

**Remaining gap**: Slovakia, Croatia, Bulgaria, Thailand, Malaysia not yet added. Fine for launch — 47 is strong coverage.

### ✅ 1b. Link + data verification

Built `apps/api/scripts/verify_jurisdiction_urls.py` — async HEAD checker across all YAML URL fields, classifies broken / redirected / bot-protected / SSL-uncertain. Ran against all 47 jurisdictions; fixed ~200 broken links:

- Belgium: malformed URL (`/enmergers` → `/en/mergers`)
- Canada: Competition Bureau site restructured
- Switzerland: WEKO site restructured  
- Germany: Radware bot-capture URL replaced with real BMAW URL
- UK: typo in CMA URL
- France, Netherlands, Norway, Italy, Spain, NZ, Sweden, Japan, Korea, China, Austria: all fixed

### ✅ 1c. Intake form → 3-step chat experience

Replaced the manual revenue form with a proper 3-stage flow:

**Stage 1 — Chat (Gemini-powered)**: Conversational intake collects deal value, transaction type, and worldwide revenues for both parties. Uses `gemini-flash-lite-latest` with a fallback chain. Returns `ready: true` only once worldwide revenues for both parties are confirmed.

**Stage 2 — Jurisdiction selector**: Full chip grid with region tabs (EU / UK / Americas / Asia-Pacific / MEA / Other). "Select all 47", "Select region", or individual chips. Previously selected jurisdictions shown as removable pills.

**Stage 3 — Revenue table**: Two-column table (Acquirer | Target) per selected jurisdiction. EU/EEA total, UK, US each get their own rows; all other selections get country-specific rows that feed directly into `by_country` in the screening request. Worldwide pre-filled read-only from stage 1.

**File upload**: Upload icon in chat bar (and on start screen). Backend parses PDF (`pdfplumber`), Excel (`openpyxl`), or CSV, feeds content to Gemini, extracts company/revenue figures, and posts the summary into the chat for confirmation.

**Session persistence**: `sessionStorage` preserves stage, chat history, jurisdiction selections, and revenue entries across page navigation. "Start over" clears it.

**Full-viewport layout**: Screen page fills `calc(100vh - 58px)`. Chat history scrolls; input bar sticks to bottom. Revenue table scrolls independently. Results table fills the full height with sticky column headers.

### ✅ 1d. Citation display in results

`legal_basis` (citation + URL) and `authority_url` now returned by the screening API (`/jurisdictions/screen`) and surfaced in the results table. Primary citation shown with a link to the official source document.

---

## Day 2 — Case pages + semantic search

### 2a. Fix semantic search

Known issue: pgvector on port 5433 must be running. Steps:
1. Confirm `/search/semantic` returns results for a test query
2. Fix search UI to show case snippets with matching passage highlighted
3. Handle "no results" gracefully

### 2b. Case summary display

For each canonical case page, surface:
- A 2-3 sentence summary at the top (generate with Gemini Flash; cache in YAML or DB)
- Outcome chip (cleared / blocked / remedies) prominently
- "Related cases" based on semantic similarity (top 3 nearest neighbours from pgvector)

### 2c. Graph view improvements

Current state: Market Map + Theory Map work locally with 26 canonical cases.
- Add tooltip explaining what the graph shows
- Fix layout crashes with large node counts
- Do not add new features — stabilise what's there

---

## Day 3 — Explore page + cross-case filtering

### 3a. Explore page polish

- Surface `outcome` and `jurisdiction` as first-class filter chips
- "X cases match" count updates in real-time
- Case card: jurisdiction flag, outcome chip, top product market, date

### 3b. Promote bulk drafts (background)

Run EU bulk promotion pipeline for ~227 unprocessed cases. More canonical cases = better semantic search + graph density. Run overnight.

---

## Day 4 — Polish + edge cases

- Mobile layout check on threshold screening
- Error states: API down, jurisdiction missing data
- "Last verified" staleness badge: >6 months since verification → yellow warning in UI
- Simplified procedure cases: show "Cleared under simplified procedure" instead of blank page

---

## Day 5 — Deployment prep

- Docker Compose: confirm all services start from cold (`docker compose up`)
- Seed production DB with canonical cases
- `.env.example` with all required keys documented (including `GOOGLE_API_KEY` for chat + file parsing)
- Basic auth or IP allowlist (pre-launch tool, not public yet)
- Smoke test: screen a real deal, search a market name, open a case page

---

## What we are NOT doing in this sprint

- Billing / usage tracking
- Public launch announcement
- Mobile app
- PDF export of screening results
- Additional jurisdiction data entry (47 is enough for launch)

---

## Open questions

| Question | Status |
|---------|--------|
| Chat model: Gemini (free key) or switch to Claude Haiku? | **Resolved**: Gemini `gemini-flash-lite-latest` with fallback chain. Works on free key. |
| Show unverified jurisdictions, or hide until verified? | **Resolved**: Show all 47; `last_verified` date visible; tooltips flag when >6 months old. |
| Promote bulk drafts automatically or require review? | **Pending** — Day 3 decision |
| Who gets access on Day 5 — specific lawyers or wider beta? | **Pending** — Day 4 decision |
| File upload: what happens when Gemini can't find revenue figures? | **Resolved**: Shows error message; user falls back to manual chat entry. |
