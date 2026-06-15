CREATE EXTENSION IF NOT EXISTS vector;

-- Case-level embeddings: one row per canonical case
-- embed_text = ai_summary + market names + theory names + sector
CREATE TABLE IF NOT EXISTS case_embeddings (
    case_id       TEXT PRIMARY KEY,
    case_name     TEXT NOT NULL,
    jurisdiction  TEXT NOT NULL,
    authority     TEXT NOT NULL,
    decision_date DATE NOT NULL,
    sector        TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    embed_text    TEXT NOT NULL,
    embedding     vector(768) NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS case_embeddings_vec_idx
    ON case_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

-- Product market embeddings: one row per (case_id, market_id)
CREATE TABLE IF NOT EXISTS market_embeddings (
    id                SERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL,
    market_id         TEXT NOT NULL,
    market_name       TEXT NOT NULL,
    definition_status TEXT NOT NULL,
    notes             TEXT,
    embed_text        TEXT NOT NULL,
    embedding         vector(768) NOT NULL,
    updated_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE (case_id, market_id)
);

CREATE INDEX IF NOT EXISTS market_embeddings_vec_idx
    ON market_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

-- Theory of harm embeddings: one row per (case_id, theory_id)
CREATE TABLE IF NOT EXISTS theory_embeddings (
    id          SERIAL PRIMARY KEY,
    case_id     TEXT NOT NULL,
    theory_id   TEXT NOT NULL,
    theory_name TEXT NOT NULL,
    description TEXT,
    embed_text  TEXT NOT NULL,
    embedding   vector(768) NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (case_id, theory_id)
);

CREATE INDEX IF NOT EXISTS theory_embeddings_vec_idx
    ON theory_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
