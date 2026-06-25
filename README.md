# Meridian

Open-source market-definition research and merger-control threshold screening for
competition lawyers.

Two products in one repo:

1. **Case research** — source-linked EU/UK/US merger decisions, searchable by sector,
   market, theory of harm, and outcome, with semantic search and graph views.
2. **Jurisdiction screening** — ~60 jurisdiction threshold profiles; screen deals via
   rules engine and deal-intake chat.

> **Disclaimer:** Meridian is a research aid, not legal advice. Records may be
> AI-assisted. Verify all propositions against linked source materials before relying
> on them.

---

## Quick start (Docker)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose)
- Optional: `GOOGLE_API_KEY` for semantic search embeddings

### 1. Clone and configure

```bash
git clone https://github.com/your-org/open-market.git
cd open-market
cp .env.example .env   # add GOOGLE_API_KEY if using semantic search
```

### 2. Start the stack

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Web | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Postgres (pgvector) | localhost:5433 |

### 3. Embed cases (optional, for semantic search)

```bash
docker compose --profile embed up embed
```

---

## Local development (without Docker)

### Backend

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://compmap:compmap_local@localhost:5433/compmap
export DATA_CASES_PATH=../../data/cases
export DATA_CASE_INDEX_PATH=../../data/case_index
uvicorn main:app --reload
```

### Frontend

```bash
cd apps/web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

---

## Validation gates

Run from `apps/api/` with venv active:

```bash
.venv/bin/python scripts/cases/validate_cases.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/check_source_links.py
.venv/bin/python scripts/cases/check_source_integrity.py --cases-dir ../../data/cases
.venv/bin/python scripts/cases/run_eval_benchmark.py --config ../../data/evals/benchmark.market_definition.ci.yaml
.venv/bin/python scripts/screening/run_jurisdiction_verification.py --tier push
```

---

## Tests

```bash
cd apps/api
.venv/bin/python -m pytest tests/ -v
cd ../web && npm run lint && npm run build
```

---

## Repo structure

```
open-market/
  apps/
    api/          FastAPI — app/{cases,screening,shared}/, scripts/{cases,screening}/
    web/          Next.js 14 — src/app/ routes; src/features/{cases,screening}/
  data/
    cases/        Canonical case YAML (270+ records)
    drafts/       AI extraction output (never auto-promoted)
    case_index/   Lighter indexed metadata
    jurisdictions/  Threshold profiles (~60)
    evals/        Gold fixtures and benchmarks
  docs/           Architecture and operations (see docs/README.md)
  docker-compose.yml
```

YAML is the source of truth. Postgres/pgvector holds case embeddings only. Screening
evaluates jurisdiction YAML in memory.

---

## API routes (summary)

| Area | Paths |
|------|-------|
| Health | `GET /health` |
| Cases | `GET /cases`, `/cases/{id}`, `/indexed-cases`, `/indexed-cases/{id}` |
| Search | `GET /search`, `/search/semantic`, `/search/market`, `/search/all` |
| Graph | `GET /graph/case/{id}`, `/graph/stats`, `/graph/markets`, … |
| Jurisdictions | `GET /jurisdictions/`, `/jurisdictions/{id}` |
| Screening | `POST /jurisdictions/screen`, `/jurisdictions/chat`, `/jurisdictions/parse-financials` |

Full OpenAPI spec: http://localhost:8000/docs

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture/overview.md](docs/architecture/overview.md) | System map |
| [docs/operations/ingestion.md](docs/operations/ingestion.md) | Extraction pipeline |
| [docs/operations/promotion-checklist.md](docs/operations/promotion-checklist.md) | Draft → canonical workflow |
| [docs/data/source-integrity.md](docs/data/source-integrity.md) | Quote and locator rules |
| [ROADMAP.md](ROADMAP.md) | Work plan to production |

---

## Source integrity

Every `source_passage` must cite a real document with a verbatim `quote_snippet` at the
stated page/paragraph. Run `check_source_links.py` and `check_source_integrity.py`
before merging data changes. Full rules: [docs/data/source-integrity.md](docs/data/source-integrity.md).

---

## Limitations

- Research tool, not production SaaS — no authentication in current build.
- Case records vary in review depth; check `review_status` and verification badges.
- Semantic search requires Postgres + `GOOGLE_API_KEY`.
