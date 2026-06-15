"""
Entity-centric graph endpoints. Serves aggregate data for the Market Map
and Theory Map views — all cases that touched a given market or theory.

Entity queries use in-memory YAML aggregation (fast, no DB).
The ?semantic=true variant merges in pgvector similarity results.
"""
from fastapi import APIRouter, Query

from app.services.case_service import get_case
from app.services.case_service import get_all_cases
from app.services.graph_entity_service import (
    get_all_markets,
    get_all_sectors,
    get_all_theories,
    get_market_cases,
    get_sector_markets,
    get_similar_markets_cooccurrence,
    get_theory_cases,
)
from app.services.index_case_service import get_all_indexed
from app.services.semantic_search_service import (
    search_markets_semantic,
    search_theories_semantic,
)

router = APIRouter(prefix="/graph", tags=["graph-entities"])


@router.get("/stats")
def graph_stats():
    """Aggregate counts for the home page and header."""
    canonical = get_all_cases()
    indexed = get_all_indexed()
    markets = get_all_markets()
    jurisdictions = sorted({c.jurisdiction for c in canonical} | {e.jurisdiction for e in indexed})
    return {
        "canonical_case_count": len(canonical),
        "indexed_case_count": len(indexed),
        "total_case_count": len(canonical) + len(indexed),
        "unique_market_count": len(markets),
        "jurisdiction_count": len(jurisdictions),
        "jurisdictions": jurisdictions,
    }


@router.get("/sectors")
def graph_sectors():
    """Top-level sector groups with case and market counts, derived from canonical cases."""
    return get_all_sectors()


@router.get("/sector/{sector}/markets")
def graph_sector_markets(sector: str):
    """All product markets from canonical cases in the given top-level sector."""
    return get_sector_markets(sector)


@router.get("/markets/similar")
async def graph_markets_similar(
    name: str = Query(..., min_length=1, description="Market name to find similar markets for"),
    limit: int = Query(default=10, ge=1, le=30),
):
    """Combined co-occurrence + semantic similar markets for a given market name."""
    cooc = get_similar_markets_cooccurrence(name, limit=limit)
    seen_names = {m["market_name"].strip().lower() for m in cooc}

    sem_rows = await search_markets_semantic(name, top_k=limit)
    for row in sem_rows:
        key = row["market_name"].strip().lower()
        if key not in seen_names and key != name.strip().lower():
            cooc.append({
                "market_name": row["market_name"],
                "shared_case_count": 0,
                "shared_case_ids": [],
                "case_count": 1,
                "dominant_status": row.get("definition_status", "discussed"),
            })
            seen_names.add(key)

    return cooc[:limit]


@router.get("/markets")
def graph_markets():
    """All product markets across canonical cases with case count and status breakdown."""
    return get_all_markets()


@router.get("/market/{market_name:path}")
async def graph_market(
    market_name: str,
    semantic: bool = Query(default=False),
):
    """Cases that considered this market. With ?semantic=true merges in vector-similar markets."""
    exact_results = get_market_cases(market_name)

    if not semantic:
        return {"market_name": market_name, "cases": exact_results, "mode": "exact"}

    sem_rows = await search_markets_semantic(market_name)
    seen = {r["case_id"] for r in exact_results}

    for row in sem_rows:
        if row["case_id"] not in seen:
            case = get_case(row["case_id"])
            if case:
                exact_results.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "jurisdiction": case.jurisdiction,
                    "authority": case.authority,
                    "decision_date": case.decision_date.isoformat(),
                    "outcome": case.outcome.value,
                    "market_id": row["market_id"],
                    "definition_status": row["definition_status"],
                    "notes": row.get("notes"),
                    "similarity": float(row["similarity"]),
                })
            seen.add(row["case_id"])

    return {"market_name": market_name, "cases": exact_results, "mode": "semantic"}


@router.get("/theories")
def graph_theories():
    """All theories of harm with case count and outcome breakdown."""
    return get_all_theories()


@router.get("/theory/{theory_name:path}")
async def graph_theory(
    theory_name: str,
    semantic: bool = Query(default=False),
):
    """Cases that applied this theory. With ?semantic=true merges in vector-similar theories."""
    exact_results = get_theory_cases(theory_name)

    if not semantic:
        return {"theory_name": theory_name, "cases": exact_results, "mode": "exact"}

    sem_rows = await search_theories_semantic(theory_name)
    seen = {r["case_id"] for r in exact_results}

    for row in sem_rows:
        if row["case_id"] not in seen:
            case = get_case(row["case_id"])
            if case:
                exact_results.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "jurisdiction": case.jurisdiction,
                    "authority": case.authority,
                    "decision_date": case.decision_date.isoformat(),
                    "outcome": case.outcome.value,
                    "theory_id": row["theory_id"],
                    "description": row.get("description"),
                    "similarity": float(row["similarity"]),
                })
            seen.add(row["case_id"])

    return {"theory_name": theory_name, "cases": exact_results, "mode": "semantic"}
