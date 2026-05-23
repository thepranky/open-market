# CompMap

Open-source market-definition research graph for competition lawyers.

CompMap lets you search merger precedent across the EU, UK, and US by sector, product market, authority, theory of harm, and outcome. Every market-definition proposition links back to a specific page, paragraph, and quote in the underlying decision or court document.

> **Disclaimer:** CompMap is a research aid, not legal advice. Records may be AI-assisted and may contain errors. Verify all propositions against the linked source materials before relying on them.

---

## Quick start (Docker Compose)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose)
- ~2 GB free RAM (Neo4j needs ~1 GB)

### 1. Clone and configure

```bash
git clone https://github.com/your-org/open-market.git
cd open-market
cp .env.example .env
```

### 2. Start the stack

```bash
docker compose up --build
```

This starts:
- **Neo4j** on `bolt://localhost:7687` and browser at `http://localhost:7474`
- **FastAPI** on `http://localhost:8000` (docs at `/docs`)
- **Next.js** on `http://localhost:3000`

### 3. Seed the graph

In a separate terminal:

```bash
docker compose --profile seed run seed
```

This loads all YAML case records from `data/cases/` into Neo4j.

### 4. Open the app

- **Frontend:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Neo4j browser:** http://localhost:7474 (user: `neo4j`, password: `compmap_local`)

---

## Running locally (without Docker)

### Backend

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Set env vars (or create a .env file)
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=compmap_local
export DATA_CASES_PATH=../../data/cases

uvicorn main:app --reload
```

### Frontend

```bash
cd apps/web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### Neo4j

Start Neo4j locally or use only the Docker Neo4j service:

```bash
docker compose up neo4j
```

---

## Validate YAML case records

```bash
cd apps/api
python scripts/validate_cases.py --cases-dir ../../data/cases
```

Expected output:

```
Validating cases in ../../data/cases ...

Results: 5 valid, 0 invalid
All cases valid.
```

---

## Check source links

Lightweight URL checker — validates HTTP status, content-type, and redirects for all source URLs in YAML case records:

```bash
cd apps/api
.venv/bin/python scripts/check_source_links.py
# or with verbose output for all URLs:
.venv/bin/python scripts/check_source_links.py --verbose
```

Exit 0 if all links OK; exit 1 if any are broken. Does not modify any data.

---

## Source integrity check

Full source validation gate — fetches each source document, extracts text, and checks quote snippets against the actual document content:

```bash
cd apps/api
.venv/bin/python scripts/check_source_integrity.py --cases-dir ../../data/cases
# verbose mode includes INFO-level results (quote found, text extraction notes):
.venv/bin/python scripts/check_source_integrity.py --verbose
```

Issue levels:
- **ERROR** — broken link, dangling `source_document_id` reference, empty quote snippet, `pdf_url` returning HTML
- **WARNING** — quote not found in extracted document text, generic portal URL, `doc_type` keywords absent from URL path
- **INFO** — check passed; text extraction notes

Exit 0 if no errors; exit 1 if any ERROR-level issues found. Does not modify any data. Requires `pypdf` (included in `requirements.txt`).

See `docs/ingestion-design.md` for the full source integrity policy and the design of the future ingestion pipeline.

---

## Seed the graph (local)

With Neo4j running and the API virtualenv active:

```bash
python graph/seed_graph.py --cases-dir data/cases --wipe
```

Flags:
- `--wipe` — delete all nodes before seeding (safe for development)
- `--no-constraints` — skip applying constraints/indexes

---

## Run tests

```bash
cd apps/api
pip install -r requirements.txt
pytest tests/ -v
```

Tests do not require Neo4j. The graph route falls back to YAML-derived data when Neo4j is unavailable.

---

## Repo structure

```
open-market/
  README.md
  docker-compose.yml
  .env.example

  apps/
    api/                  FastAPI backend
      main.py
      app/
        models/           Pydantic schema (case.py)
        routers/          API routes (cases, search, graph, health)
        services/         Business logic
        core/             Config + Neo4j client
        loader/           YAML loader + validator
      tests/              pytest suite
      scripts/            validate_cases.py

    web/                  Next.js 14 frontend (App Router)
      src/
        app/
          page.tsx         Landing page (/)
          explore/         Search/filter page (/explore)
          cases/[case_id]/ Case detail page
        components/        Shared UI components
        lib/               API client, types, utils

  data/
    cases/
      eu/                 EU case YAML records
      uk/                 UK case YAML records
      us/                 US case YAML records

  graph/
    constraints.cypher    Neo4j uniqueness constraints
    indexes.cypher        Full-text and range indexes
    seed_graph.py         Import YAML into Neo4j
    queries/              Reference Cypher queries

  packages/schema/        (reserved for shared JSON Schema in later slices)
  ingestion/              (reserved for AI ingestion pipeline)
  evals/                  (reserved for extraction quality evals)
  docs/                   (reserved for architecture docs)
```

---

## API routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (includes Neo4j status) |
| GET | `/cases` | List cases (filter: `jurisdiction`, `sector`, `outcome`) |
| GET | `/cases/{case_id}` | Case detail |
| GET | `/search?q=...` | Keyword search across cases |
| GET | `/graph/case/{case_id}` | Graph neighbourhood (Neo4j if seeded, YAML fallback) |

---

## Case schema

Each case record (`data/cases/**/*.yaml`) follows the `CaseRecord` Pydantic model in `apps/api/app/models/case.py`. Key fields:

- `case_id`, `case_name`, `jurisdiction`, `authority`, `decision_date`
- `outcome`: `cleared` | `cleared_with_remedies` | `blocked` | `abandoned` | `referred`
- `product_markets_considered` — with `definition_status`: `defined` | `discussed` | `segmented` | `left_open`
- `source_passages` — each with `quote_snippet`, source locator, `extraction_method`, `review_status`, `confidence_score`
- `metadata` — `extraction_method`, `review_status`, `overall_confidence`

---

## Source integrity rules

Every `source_documents` entry and every `source_passages` quote must meet the following criteria before being committed:

**Source documents**
- The `pdf_url` or `case_page_url` must resolve with an HTTP 200 and return the expected content type. Run `check_source_links.py` and confirm zero broken links before merging.
- Do not add a source document with only a plausible title and no verified URL. A title alone is not evidence the document exists.
- `doc_type` must match the actual document (e.g., `complaint`, `court_opinion`, `decision`, `final_report`). Do not label a complaint as a decision or vice versa.

**Source passages**
- Every `source_passage` must reference a `source_document_id` that exists in the same record's `source_documents` list.
- The `quote_snippet` must be text that appears in the linked document at the stated page or paragraph. Do not paraphrase or reconstruct — use the actual words.
- Do not characterise complaint allegations as adjudicated findings. If the only available source is a complaint, the `definition_status` for any referenced markets should be `discussed`, not `defined`.
- If no verified source exists for a proposition, omit the `source_passages` entry and set the market or theory notes to indicate `SOURCE NEEDED`.

**Case history events**
- An event should only be added if you are confident the event occurred. Public record events (filings, court dates, deal closures) may be recorded without a `source_url` but must be marked `review_status: unreviewed` and must include `SOURCE NEEDED` in the summary.
- Do not invent procedural history to fill gaps. If the record of events is incomplete, leave it incomplete.

---

## Adding a new case

1. Create a YAML file in the correct jurisdiction subdirectory under `data/cases/`.
2. Follow the schema in `apps/api/app/models/case.py`.
3. Validate: `python apps/api/scripts/validate_cases.py`.
4. Check source links: `python apps/api/scripts/check_source_links.py`.
5. Re-run the seed script to import into Neo4j.

---

## Architecture

```
Browser → Next.js (port 3000)
              ↓ fetch (NEXT_PUBLIC_API_URL)
          FastAPI (port 8000)
              ↓ reads from
          data/cases/*.yaml  (canonical source of truth)
              ↓ seeds into
          Neo4j (port 7687)  (queryable graph store)
```

YAML files are the canonical source of truth. Neo4j is populated by the seed script and used for graph neighbourhood queries. Search currently runs over the in-memory YAML cache; full-text Neo4j search is available via `graph/queries/search.cypher` for later integration.

---

## Known gaps and next slice

This is the **first vertical slice**. The following are out of scope and reserved for subsequent slices:

- **AI ingestion pipeline** (`ingestion/`) — fetch URL → extract text → Claude → draft YAML
- **Embedding-based similarity** — semantic search over summaries and passages
- **Graph visualisation** — Cytoscape.js interactive graph on the frontend
- **Research set and exports** — select cases, export CSV/Markdown
- **Full-text Neo4j search** — currently uses YAML-based keyword matching
- **Memo generation** — AI-generated research memos from selected cases
- **50+ case records** — current dataset is 5 samples; needs expansion
- **`/graph` explorer page** and **`/admin/ingestion` page** — reserved, not yet built

---

## Limitations

- Records are manually authored samples for v0. They are not exhaustive and have not been lawyer-reviewed.
- AI summaries are labelled; they summarise publicly available decisions and should be verified against source.
- No authentication, user accounts, or payments in this slice.
- The app does not verify the legal correctness of any market-definition proposition.
