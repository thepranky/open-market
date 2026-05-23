// Full-text keyword search across cases
// Parameters: $query (string)
CALL db.index.fulltext.queryNodes("case_search", $query)
YIELD node, score
RETURN node AS case, score
ORDER BY score DESC
LIMIT 20
