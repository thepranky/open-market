# CompMap — Product Plan

*Written June 2026. Supersedes informal roadmap in project-pipeline-explainer.md §8.*

---

## 1. What the product actually is (restated clearly)

A **directory of competition law merger cases** where every case page shows:
- The legal analysis the authority actually performed: product markets considered, geographic markets, theories of harm raised, remedies imposed, outcome
- Each finding backed by an exact quote from the source decision with page/paragraph number
- Searchable at scale across hundreds of cases by keyword, sector, market name, theory type, outcome, jurisdiction

The research value: a lawyer preparing for a media merger opens CompMap, searches "music streaming", and sees every case where that product market was defined or considered — with the exact passage from each decision. They don't read 20 PDFs.

---

## 2. Honest current-state assessment

### Works well

- **Canonical case detail pages** — the best thing in the product. Each case shows product markets, geographic markets, theories of harm, remedies, with source chips linking to exact page/paragraph. This is the core differentiator and it works.
- **Ingestion pipeline** — one-command controlled-case runner, multi-focus extraction, long-decision support (Bayer/Monsanto 1006 pages), jurisdiction profiles (EC, CMA, US courts). Hard to build, genuinely works.
- **Quote validation gate** — every quote checked against extracted source text before it enters the database. This is the anti-hallucination backbone.
- **Data quality** — 26 fully reviewed canonical cases, all Pydantic-validated, all quote-verified. Small but clean.
- **Eval benchmark** — 6 fixtures, 6/6 PASS at F1=1.0. Regression testing is real.
- **Semantic search** — Postgres+pgvector with Google Gemini embeddings (768-dim, `gemini-embedding-001`); `/search/semantic` works end-to-end; confirmed: "online advertising" → EU Google/Meta cases at 0.6+ similarity. Works locally; needs Postgres running on port 5433.
- **Entity-centric graph** — Market Map (211 unique markets) and Theory Map (37 unique theories from 26 canonical cases); Cytoscape.js force-directed; sector filter chips; click → detail panel with status breakdown; Expand → adds case nodes to canvas. Entity-centric (market/theory as primary entry point) rather than case-centric — the right research mental model.

### Works partially / not properly

- **Search** — semantic search exists and works locally; keyword search still in-memory substring match. With only 26 canonical cases embedded, semantic recall is limited. Quality improves dramatically once 200+ cases are promoted.
- **Graph view** — Market Map and Theory Map built and working locally; with only 26 canonical cases the graph is sparse (most markets have 1–2 case connections). Becomes genuinely useful at 100+ canonical cases.
- **Indexed cases** — 459 Gemini-extracted bulk drafts exist in `data/drafts/eu/` from the June 2026 Phase I EU bulk run, none yet promoted to canonical. ~496 simplified procedure cases correctly detected and skipped (no market analysis in source). 35 failures to investigate.
- **Cross-case filtering** — filter by jurisdiction/sector/outcome but not by market name in the keyword search view. Market/theory filtering works in the new graph and semantic endpoints.

### Cannot do yet (needed for real product)

- **Scale** — 26 canonical + ~2,300 indexed metadata stubs = surface-level coverage. Need to promote bulk drafts and display simplified-procedure cases gracefully.
- **Production deployment** — local Docker only. No public URL, no auth, no staging. This is now the primary unblocked gap.
- **Simplified procedure display** — ~60–75% of EC Phase I cases are simplified procedure (2-3 page formal clearances with no market analysis). These need a graceful "cleared under simplified procedure" display rather than appearing broken.
- **Automated corpus discovery** — all case selection is manual. EC registry scraper exists; CMA/US scrapers not built.

---

## 3. LLM cost strategy for scale

### The problem

Claude Sonnet at current pricing (~$3/$15 per MTok) costs roughly $0.10–$0.20 per case for a single extraction focus pass. For 4 passes (markets, theories, remedies, outcome) across 3000+ EU/UK/US cases = potentially $1,200–$2,400+ in extraction cost alone. Not viable for a side project at scale.

### The solution: tiered model strategy (implemented)

| Tier | What it's for | Model | Cost |
|------|--------------|-------|------|
| **Bulk extraction drafts** | First-pass extraction for all focus modes | Gemini 2.5 Flash | ~$0.003/case |
| **AI summaries for indexed cases** | Short case summaries for browse/discovery | Gemini 2.5 Flash | ~$0.001/case |
| **Embeddings** | Semantic search indexing and query embedding | Gemini `gemini-embedding-001` | Already working |
| **Canonical LLM review/triage** | `review_draft.py` critic before human promotion | Gemini 2.5 Flash | ~$0.013/case |
| **High-stakes extraction** | Complex Phase II decisions, hard cases, US court opinions | Claude Sonnet | Pay per case |

**Proven cost for EC Phase I corpus:**
- June 2026 bulk run: ~990 cases processed, ~$2–3 total cost (most are simplified procedure skips at zero cost)
- Remaining ~1,171 cases: estimated $2–4 additional
- Entire EC corpus from 2010–present (~3,000 cases): estimated $6–10 total

### Implementation status

Gemini integration is live and proven:
- `extract_case_from_source.py` — uses Gemini 2.5 Flash via `--provider gemini` flag (used in bulk run)
- `apps/api/app/services/embedding_service.py` — Google `gemini-embedding-001` for semantic search
- `GOOGLE_API_KEY` in `.env` — required for both extraction and embeddings

**Google Gemini SDK**: `google-genai` Python package (NOT the older `google-generativeai`). `GOOGLE_API_KEY` from Google AI Studio.

---

## 4. Product roadmap to deployment

### Phase 2 — Semantic search + cross-case filters ✅ DONE (June 2026)

Implemented with Postgres+pgvector (not sqlite-vec as originally planned — simpler ops, no file-system dependency).

- **Postgres+pgvector** running via Docker Compose (`pgvector/pgvector:pg16`); port 5433 locally, 5432 in Docker containers.
- **Embeddings:** Google `gemini-embedding-001`, 768 dims, asymmetric retrieval (RETRIEVAL_DOCUMENT for indexing, RETRIEVAL_QUERY for search).
- **Endpoints:** `GET /search/semantic?q=` (cases), `GET /search/market?name=` (market-level hits).
- **Frontend:** Keyword/Semantic pill toggle in explore search bar; `ExploreClient.tsx` client wrapper for semantic state.
- **Status:** 26 canonical cases embedded, confirmed working end-to-end.

---

### Phase 3 — Entity-centric graph exploration ✅ DONE (June 2026)

Replaced case-centric graph (1-hop neighborhood) with entity-centric graph (start from market or theory, navigate to all cases).

- **Market Map** — 211 unique product markets from 26 canonical cases; nodes sized by case count, colored by dominant definition status; sector filter chips; click → EntityDetailPanel → Expand adds case nodes.
- **Theory Map** — 37 unique theories; colored by dominant outcome (blocked/cleared with conditions/cleared).
- **Three-tab GraphView:** Case Neighborhood / Market Map / Theory Map.
- **Data source:** Pure YAML aggregation (no Postgres for entity queries — fast and reliable at current corpus size).
- **Status:** Working locally. Becomes much more useful at 100+ canonical cases.

---

### Phase 1 — Corpus scale (target: 200+ canonical cases) [IN PROGRESS]

The June 2026 Phase I EU bulk run completed its first pass:
- **Run ID:** `eu_20260612_212451` — 990 cases processed (of 2,161 runnable)
- **459 drafts generated** from real Phase I decisions (Gemini 2.5 Flash, ~$0.003/case)
- **496 simplified procedure cases correctly skipped** (no market analysis in source; pipeline detects "no chunks matched" and exits clean)
- **35 failures** to investigate (`data/batch_runs/eu_20260612_212451.json` `status: failed`)
- **~1,171 cases not yet processed** — need a second run to complete the corpus

**Next steps for Phase 1:**
1. Spot-check 5–10 random full-decision drafts from the 459 for quality before bulk promoting
2. Batch promote clean Phase I drafts via `promote_draft_to_canonical.py`
3. Resume bulk run on remaining ~1,171 cases: `nohup caffeinate -i python3 apps/api/scripts/run_bulk_extraction.py --resume-id eu_20260612_212451 --delay 2 >> data/batch_runs/bulk_overnight.log 2>&1 &`
4. Investigate 35 failures (likely merge-logic TypeError: unhashable type 'dict')
5. Re-run embedding indexer after each batch of promotions (idempotent: `ON CONFLICT DO UPDATE`)

**Simplified procedure display:** ~60–75% of EC Phase I decisions are simplified procedure (2–3 page formal clearances with no market analysis). These indexed-only cases need a graceful "Cleared under simplified procedure — no public market analysis" display using index metadata (parties, date, outcome, sector) rather than showing an empty case page.

**Success metric:** 200+ canonical cases; semantic search returns useful results for "music streaming", "online advertising", "wholesale electricity".

---

### Phase 4 — Deploy [NEXT — 1 week]

**Target stack (updated — Neo4j removed):**

| Component | Host | Cost |
|-----------|------|------|
| Next.js frontend | Vercel | Free |
| FastAPI backend | Railway | Free tier (500 hours/month) |
| Postgres+pgvector | Railway Postgres plugin | $5–10/month (or free tier) |
| YAML case data | Committed to repo / Railway volume | Free |
| PDF source cache | Cloudflare R2 or repo LFS | Free tier |

**Auth:** Single `API_KEY` env var checked in FastAPI middleware. No login UI. Give the key to beta users directly.

**Deploy steps:**
1. Add `ENVIRONMENT` config (`development` / `production`) to `apps/api/app/core/config.py`
2. Add CORS origin whitelist for production domain
3. Write `apps/api/railway.toml` or `Procfile` for Railway deploy
4. Set up Vercel project pointing to `apps/web/`; set `NEXT_PUBLIC_API_URL` to Railway URL
5. Provision Railway Postgres with pgvector (or use pgvector-compatible managed service)
6. Run embedding indexer against production DB after deploy
7. Remove dead Neo4j code: `graph/seed_graph.py`, `apps/api/app/services/graph_service.py`, `apps/api/app/core/neo4j_client.py`

**Monitoring:** Vercel Analytics for frontend. Railway logs for API. Add Sentry or similar if needed post-launch.

---

### Phase 5 — Research platform features [ongoing]

Once deployed with 200+ cases and semantic search:

- **Simplified procedure case pages** — indexed stubs with graceful "no public analysis" display, parties, outcome, and link to source
- **Case comparison view** — side-by-side: product markets, theories, outcome. Useful for cross-jurisdiction pairs (EU vs CMA on same transaction)
- **Precedent trails** — "show all EC decisions that defined market X before 2020"
- **Saved searches / alerts** — user saves a search, gets notified when a new matching case is added
- **API for power users** — public read-only API with rate limiting
- **Citation export** — copy a source passage as a formatted legal citation (Bluebook / OSCOLA)

---

## 5. What to do next session

Priority order (each unblocks the next):

1. **Triage bulk drafts** — spot-check 5–10 random `data/drafts/eu/` files from the 459 done. Look for: markets found (or not), quote grounding, `definition_status` correctness. Then decide: bulk-promote all, or filter by some quality signal first.
2. **Simplified procedure display** — add a graceful case page variant for index-only entries (parties, date, sector, outcome, "Cleared under simplified procedure") so these don't look broken. ~496 identified from the bulk run.
3. **Continue bulk run** — resume `eu_20260612_212451` on remaining ~1,171 cases. Use `caffeinate+nohup+timeout` overnight pattern. Investigate the 35 failures (likely the `unhashable type: 'dict'` merge bug).
4. **Re-run embedding indexer** — after each batch of promotions: `python apps/api/scripts/index_embeddings.py`. Idempotent.
5. **Deploy config** — Railway + Vercel wiring. Remove dead Neo4j code first.
6. **API key auth** — single `API_KEY` header check in FastAPI middleware before any route.
7. **CORS** — add production domain to `allow_origins` in `apps/api/main.py`.

Infrastructure state for next session:
- **Postgres** on port 5433: `docker compose up postgres -d`; `DATABASE_URL=postgresql://compmap:compmap_local@localhost:5433/compmap` in `.env`
- **API**: `cd apps/api && uvicorn main:app --reload --port 8000`
- **Web**: `cd apps/web && npm run dev`
- **Neo4j dead code** (safe to delete): `graph/seed_graph.py`, `apps/api/app/services/graph_service.py`, `apps/api/app/core/neo4j_client.py`

---

## 6. Open questions (for human decision)

- **Canonical promotion rate:** With Gemini-extracted drafts, how much human review bandwidth exists? Options: (a) review every case before canonical promotion [slow, high quality], (b) auto-promote high-confidence Phase I decisions with spot-check audit [fast, some risk], (c) expand the "indexed" tier to include Gemini-extracted-but-not-human-reviewed records with a distinct trust label [compromise].
- **Graph data model:** ~~Keep Neo4j vs Postgres?~~ **DECIDED:** moved to Postgres+pgvector (June 2026). Entity-centric graph queries run from YAML aggregation; vector similarity from pgvector. Neo4j code remains as dead code to delete.
- **Case scope:** EC-first (most standardised decisions, best structured), then CMA, then US courts? Or all three in parallel?
- **Name:** CompMap? Or rename before launch?

---

*This document should be updated when a phase completes or the approach changes. Do not let it drift from actual repo state for more than two weeks.*
