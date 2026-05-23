// Return the full neighbourhood for a given case
// Parameters: $case_id (string)
MATCH (c:Case {case_id: $case_id})
OPTIONAL MATCH (c)-[:INVOLVES_PARTY]->(p:Party)
OPTIONAL MATCH (c)-[:CONCERNS_SECTOR]->(s:Sector)
OPTIONAL MATCH (c)-[:CONSIDERED_PRODUCT_MARKET]->(pm:ProductMarket)
OPTIONAL MATCH (c)-[:CONSIDERED_GEOGRAPHIC_MARKET]->(gm:GeographicMarket)
OPTIONAL MATCH (c)-[:APPLIES_THEORY]->(t:TheoryOfHarm)
OPTIONAL MATCH (c)-[:RESULTED_IN]->(o:Outcome)
OPTIONAL MATCH (c)-[sim:SIMILAR_TO]->(similar:Case)
OPTIONAL MATCH (auth:Authority)-[:DECIDED]->(c)
OPTIONAL MATCH (jur:Jurisdiction)-[:HAS_AUTHORITY]->(auth)
RETURN
  c,
  collect(DISTINCT p) AS parties,
  collect(DISTINCT s) AS sectors,
  collect(DISTINCT pm) AS product_markets,
  collect(DISTINCT gm) AS geographic_markets,
  collect(DISTINCT t) AS theories,
  collect(DISTINCT o) AS outcomes,
  collect(DISTINCT {case: similar, score: sim.score, reasons: sim.reasons}) AS similar_cases,
  auth,
  jur
