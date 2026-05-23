# CompMap v0 Spec

## Product scope

CompMap is an open-source market-definition research graph for competition lawyers. v0 focuses on merger cases across the EU, UK, and US.

The product should help a lawyer:

- search for market-definition precedent by sector, product market, authority, party, theory of harm, and outcome;
- inspect source-linked case records;
- navigate case/market/sector/theory relationships through a graph view;
- identify similar precedent cases and case clusters;
- select cases into a research set;
- export a source-grounded research table or memo.

v0 is a research aid, not a legal advice system. It should make uncertainty visible through source links, confidence scores, extraction method, and review status.

## v0 dataset scope

Jurisdictions:

- EU: European Commission merger decisions.
- UK: CMA merger decisions.
- US: DOJ / FTC merger materials.

Case type:

- Merger cases only.
- Conduct cases are out of scope for v0.

Target dataset:

- Minimum: 50 case records.
- Stretch: 100 case records.

Initial sectors:

- digital / platforms;
- pharma / life sciences;
- airlines / travel;
- energy;
- telecoms;
- retail / grocery / consumer;
- AI / chips / data infrastructure / cloud.

## Core data model

Canonical case records should be stored as YAML files committed to the repo under `data/cases/`.

Each case record should include:

- `case_id`
- `case_name`
- `jurisdiction`
- `authority`
- `decision_date`
- `case_type`
- `procedure_stage`
- `sector`
- `parties`
- `outcome`
- `remedies`
- `theories_of_harm`
- `product_markets_considered`
- `geographic_markets_considered`
- `source_documents`
- `source_passages`
- `similar_cases`
- `ai_summary`
- `metadata`

Every extracted market-definition proposition should include:

- source URL or source document ID;
- page / paragraph / section locator where available;
- short quote snippet where legally safe;
- extraction method;
- review status;
- confidence score;
- last checked date.

Review statuses:

- `unreviewed`
- `spot_checked`
- `lawyer_reviewed`

Extraction methods:

- `ai_extracted`
- `manually_added`
- `imported_metadata`

## Graph model

Use Neo4j as the graph database.

Core nodes:

- `Jurisdiction`
- `Authority`
- `Case`
- `Party`
- `Sector`
- `ProductMarket`
- `GeographicMarket`
- `TheoryOfHarm`
- `Outcome`
- `Remedy`
- `SourceDocument`
- `SourcePassage`
- `PrecedentCluster`

Core relationships:

- `(:Jurisdiction)-[:HAS_AUTHORITY]->(:Authority)`
- `(:Authority)-[:DECIDED]->(:Case)`
- `(:Case)-[:INVOLVES_PARTY]->(:Party)`
- `(:Case)-[:CONCERNS_SECTOR]->(:Sector)`
- `(:Case)-[:CONSIDERED_PRODUCT_MARKET]->(:ProductMarket)`
- `(:Case)-[:CONSIDERED_GEOGRAPHIC_MARKET]->(:GeographicMarket)`
- `(:Case)-[:APPLIES_THEORY]->(:TheoryOfHarm)`
- `(:Case)-[:RESULTED_IN]->(:Outcome)`
- `(:Case)-[:HAS_REMEDY]->(:Remedy)`
- `(:Case)-[:HAS_SOURCE]->(:SourceDocument)`
- `(:SourceDocument)-[:CONTAINS_PASSAGE]->(:SourcePassage)`
- `(:SourcePassage)-[:SUPPORTS_MARKET]->(:ProductMarket)`
- `(:SourcePassage)-[:SUPPORTS_GEOGRAPHIC_MARKET]->(:GeographicMarket)`
- `(:SourcePassage)-[:SUPPORTS_THEORY]->(:TheoryOfHarm)`
- `(:Case)-[:SIMILAR_TO {score, method, reasons}]->(:Case)`
- `(:Case)-[:BELONGS_TO_CLUSTER]->(:PrecedentCluster)`

Source passages should be first-class nodes. This is what makes the app useful for legal research rather than just a visual database.

## Tech stack

### Frontend

Use:

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Cytoscape.js or Neo4j NVL for graph visualisation

Recommended default: use Cytoscape.js first unless Neo4j NVL is clearly easier to integrate.

### Backend

Use:

- Python
- FastAPI
- Pydantic
- Neo4j Python driver
- PyYAML
- Anthropic SDK for Claude-powered extraction/summaries
- OpenAI SDK or equivalent embedding provider for similarity search
- PyMuPDF and/or pdfplumber for PDF extraction
- BeautifulSoup + httpx for HTML/source fetching
- pytest for backend tests

### Data/storage

Use:

- YAML files as canonical open-source data records;
- Neo4j as the queryable graph store;
- local file storage under `data/sources/` for downloaded/public source files where appropriate;
- no Postgres in v0 unless a clear need appears.

## Backend architecture

The backend should expose a FastAPI service with modules for:

- schema validation;
- YAML case loading;
- Neo4j seeding;
- search;
- graph neighbourhood queries;
- case detail retrieval;
- source passage retrieval;
- ingestion;
- embeddings and similarity;
- exports;
- AI summaries and memo generation.

Suggested API routes:

- `GET /health`
- `GET /cases`
- `GET /cases/{case_id}`
- `GET /search?q=...`
- `GET /graph/neighbourhood?node_id=...`
- `GET /graph/case/{case_id}`
- `POST /research-set/export/csv`
- `POST /research-set/export/markdown`
- `POST /ai/memo`
- `POST /ingestion/fetch-source`
- `POST /ingestion/extract-case-yaml`
- `POST /ingestion/validate-record`

## Ingestion pipeline

v0 should support both automated and manual ingestion.

Automated path:

1. User provides source URL or PDF URL.
2. Backend fetches source.
3. Backend extracts text.
4. Claude converts source text into draft structured YAML.
5. Pydantic validates the YAML.
6. Record is saved with `ai_extracted` and `unreviewed` metadata.
7. Seed script imports validated records into Neo4j.

Manual fallback:

1. User uploads or places a PDF/text file in `data/sources/`.
2. Backend extracts text.
3. Same Claude-to-YAML flow runs.
4. User can manually edit YAML if needed.

The pipeline should be transparent. Failed extraction should produce useful error messages, not silent bad records.

## Search and similarity

Search should support:

- keyword search;
- filters;
- semantic search over summaries, source passages, sectors, markets, and theories of harm;
- graph expansion from selected cases/markets/sectors.

Filters:

- jurisdiction;
- authority;
- sector;
- date range;
- product market;
- geographic market;
- theory of harm;
- outcome;
- market definition status;
- review status;
- confidence score.

Similarity should combine:

- embedding similarity; and
- graph feature overlap.

Similarity reasons should be shown in the UI. Do not show only a raw score.

## Frontend/UI

Main pages:

- `/` — short landing page and disclaimer.
- `/explore` — main search/filter/results interface.
- `/cases/[case_id]` — case detail page.
- `/graph` — graph explorer.
- `/research-set` — selected cases and export workflow.
- `/admin/ingestion` — local/admin ingestion workflow.

### Explore page

Layout:

- left filter panel;
- central results table/cards;
- right preview panel for selected case/source passage;
- research-set tray or side panel.

Each result should show:

- case name;
- jurisdiction;
- authority;
- date;
- sector;
- product/geographic markets;
- theory of harm;
- outcome;
- review status/confidence.

### Case detail page

Must show:

- case metadata;
- parties;
- product markets considered;
- geographic markets considered;
- whether market was defined, discussed, segmented, or left open;
- theories of harm;
- outcome/remedy;
- source passages;
- source links;
- AI summary with visible caveat;
- similar cases with reasons;
- graph neighbourhood.

### Graph view

The graph should allow a user to:

- click nodes;
- filter by node type;
- expand case neighbourhoods;
- jump from graph node to case detail;
- hide/show low-confidence or unreviewed records.

The graph is a research aid, not decorative UI.

## AI features

v0 may include:

- AI-generated short case summaries;
- AI-generated market-definition summaries;
- AI-assisted YAML extraction;
- AI-generated memo from selected cases.

Rules:

- AI outputs must be marked as AI-generated.
- Memo generation must use only selected cases/source passages.
- Memo output must include source IDs and caveats.
- The app should never claim to provide legal advice.

## Exports

v0 should support:

- CSV export of selected cases;
- Markdown research table;
- Markdown research memo if AI memo generation is implemented.

DOCX export is out of scope for v0.

## Repo structure

Use a monorepo:

```text
open-market/
  README.md
  docker-compose.yml
  .env.example
  v0-spec.md

  apps/
    web/
    api/

  packages/
    schema/

  data/
    cases/
      eu/
      uk/
      us/
    sources/
    seed/

  ingestion/

  graph/
    constraints.cypher
    indexes.cypher
    seed_graph.py
    queries/

  evals/

  docs/
```

## Deployment

v0 target:

- local Docker Compose demo.

Docker services:

- frontend;
- FastAPI backend;
- Neo4j.

Public deployment can come after v0:

- frontend on Vercel;
- backend on Render/Fly.io;
- graph database on Neo4j Aura.

Do not over-optimise for public deployment before the local app and dataset work properly.

## Required libraries/frameworks

Frontend:

```bash
npx create-next-app@latest apps/web --ts --tailwind --eslint --app
cd apps/web
npm install @tanstack/react-query cytoscape react-cytoscapejs zod lucide-react class-variance-authority clsx tailwind-merge
npx shadcn@latest init
```

Backend:

```bash
mkdir -p apps/api
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic pydantic-settings neo4j pyyaml anthropic openai pymupdf pdfplumber beautifulsoup4 httpx python-multipart pytest ruff
```

Optional backend libraries:

```bash
pip install pandas numpy scikit-learn tiktoken
```

Neo4j:

Use Docker Compose for local Neo4j. Do not require the user to install Neo4j manually.

## v0 acceptance criteria

v0 is complete when:

- local Docker Compose starts the app, API, and Neo4j;
- at least 50 case records exist across EU/UK/US;
- case records validate against the schema;
- seed script imports cases into Neo4j;
- search and filters work;
- graph neighbourhood view works;
- case detail pages show source-linked market-definition data;
- similar cases appear with reasons;
- users can build a research set;
- CSV and Markdown exports work;
- AI summaries are clearly labelled;
- ingestion can fetch or accept a source and produce draft YAML;
- README explains setup, architecture, limitations, and disclaimer.

## Out of scope for v0

- user accounts;
- authentication;
- payments;
- custom trained model;
- conduct cases;
- global jurisdictions beyond EU/UK/US;
- full legal chatbot;
- DOCX export;
- production admin CMS;
- claims that the app verifies legal correctness.

## Disclaimer

CompMap is an open-source research aid for market-definition research. It is not legal advice. Records may be generated or assisted by AI and may contain errors. Users must verify all propositions against the linked source materials before relying on them.