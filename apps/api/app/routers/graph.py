from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.case_service import get_case
from app.services.graph_service import get_case_neighbourhood

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/case/{case_id}")
async def case_graph(case_id: str) -> dict[str, Any]:
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    try:
        neighbourhood = await get_case_neighbourhood(case_id)
    except Exception:
        # Neo4j may not be seeded yet; fall back to YAML-derived graph
        neighbourhood = _yaml_neighbourhood(case)
    return neighbourhood


def _yaml_neighbourhood(case) -> dict[str, Any]:
    """Build a graph-like response from YAML data without Neo4j."""
    return {
        "case": case.to_graph_dict(),
        "parties": [{"name": p.name, "role": p.role.value} for p in case.parties],
        "sectors": [{"name": case.sector}],
        "product_markets": [
            {"name": m.name, "definition_status": m.definition_status.value}
            for m in case.product_markets_considered
        ],
        "geographic_markets": [
            {"name": m.name, "definition_status": m.definition_status.value}
            for m in case.geographic_markets_considered
        ],
        "theories_of_harm": [
            {"name": t.name, "description": t.description}
            for t in case.theories_of_harm
        ],
        "outcomes": [{"name": case.outcome.value}],
        "similar_cases": [
            {"case": {"case_id": s.case_id}, "score": s.score, "reasons": s.reasons}
            for s in case.similar_cases
        ],
        "authority": {"name": case.authority},
        "jurisdiction": {"name": case.jurisdiction},
        "source": "yaml",
    }
