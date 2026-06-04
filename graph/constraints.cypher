// Unique constraints
CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE;
CREATE CONSTRAINT jurisdiction_name IF NOT EXISTS FOR (j:Jurisdiction) REQUIRE j.name IS UNIQUE;
CREATE CONSTRAINT authority_name IF NOT EXISTS FOR (a:Authority) REQUIRE a.name IS UNIQUE;
CREATE CONSTRAINT party_name IF NOT EXISTS FOR (p:Party) REQUIRE p.name IS UNIQUE;
CREATE CONSTRAINT sector_name IF NOT EXISTS FOR (s:Sector) REQUIRE s.name IS UNIQUE;
CREATE CONSTRAINT product_market_id IF NOT EXISTS FOR (pm:ProductMarket) REQUIRE pm.market_id IS UNIQUE;
CREATE CONSTRAINT geographic_market_id IF NOT EXISTS FOR (gm:GeographicMarket) REQUIRE gm.market_id IS UNIQUE;
CREATE CONSTRAINT theory_id IF NOT EXISTS FOR (t:TheoryOfHarm) REQUIRE t.theory_id IS UNIQUE;
CREATE CONSTRAINT outcome_name IF NOT EXISTS FOR (o:Outcome) REQUIRE o.name IS UNIQUE;
CREATE CONSTRAINT source_doc_id IF NOT EXISTS FOR (sd:SourceDocument) REQUIRE sd.doc_id IS UNIQUE;
CREATE CONSTRAINT source_passage_id IF NOT EXISTS FOR (sp:SourcePassage) REQUIRE sp.passage_id IS UNIQUE;
CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (co:Concept) REQUIRE co.concept_id IS UNIQUE;
