from typing import Any

from app.core.neo4j_client import run_query


async def get_case_neighbourhood(case_id: str) -> dict[str, Any]:
    query = """
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
    """
    rows = await run_query(query, {"case_id": case_id})
    if not rows:
        return {}

    row = rows[0]
    case_node = dict(row["c"]) if row["c"] else {}

    def node_list(items: list) -> list[dict]:
        return [dict(n) for n in items if n is not None]

    similar = []
    for s in row.get("similar_cases", []):
        if s and s.get("case"):
            similar.append({
                "case": dict(s["case"]),
                "score": s.get("score"),
                "reasons": s.get("reasons", []),
            })

    return {
        "case": case_node,
        "parties": node_list(row.get("parties", [])),
        "sectors": node_list(row.get("sectors", [])),
        "product_markets": node_list(row.get("product_markets", [])),
        "geographic_markets": node_list(row.get("geographic_markets", [])),
        "theories_of_harm": node_list(row.get("theories", [])),
        "outcomes": node_list(row.get("outcomes", [])),
        "similar_cases": similar,
        "authority": dict(row["auth"]) if row.get("auth") else None,
        "jurisdiction": dict(row["jur"]) if row.get("jur") else None,
    }
