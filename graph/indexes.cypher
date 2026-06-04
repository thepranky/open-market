// Full-text search indexes
CREATE FULLTEXT INDEX case_search IF NOT EXISTS FOR (c:Case) ON EACH [c.case_name, c.sector, c.ai_summary];
CREATE FULLTEXT INDEX market_search IF NOT EXISTS FOR (pm:ProductMarket) ON EACH [pm.name, pm.notes];
CREATE FULLTEXT INDEX passage_search IF NOT EXISTS FOR (sp:SourcePassage) ON EACH [sp.quote_snippet];

// Range / lookup indexes
CREATE INDEX case_jurisdiction IF NOT EXISTS FOR (c:Case) ON (c.jurisdiction);
CREATE INDEX case_outcome IF NOT EXISTS FOR (c:Case) ON (c.outcome);
CREATE INDEX case_sector IF NOT EXISTS FOR (c:Case) ON (c.sector);
CREATE INDEX case_decision_date IF NOT EXISTS FOR (c:Case) ON (c.decision_date);
CREATE INDEX passage_confidence IF NOT EXISTS FOR (sp:SourcePassage) ON (sp.confidence_score);
CREATE INDEX case_data_layer IF NOT EXISTS FOR (c:Case) ON (c.data_layer);
