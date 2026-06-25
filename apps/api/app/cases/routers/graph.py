from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.cases.models.api_responses import GraphEdge, GraphNeighborhoodResponse, GraphNode
from app.cases.models.case import CaseRecord
from app.cases.models.case_index import CaseIndexEntry
from app.cases.services.case_service import get_case
from app.cases.services.graph_service import get_case_neighbourhood
from app.cases.services.index_case_service import get_indexed_case

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/case/{case_id}")
async def case_graph(case_id: str) -> dict[str, Any]:
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    try:
        neighbourhood = await get_case_neighbourhood(case_id)
    except Exception:
        neighbourhood = _yaml_neighbourhood(case)
    return neighbourhood


@router.get("/neighborhood/{case_id}", response_model=GraphNeighborhoodResponse)
async def graph_neighborhood(
    case_id: str,
    depth: int = Query(default=1, ge=1, le=2),
    include_indexed: bool = Query(default=True),
) -> GraphNeighborhoodResponse:
    """Return a UI-oriented graph neighborhood for canonical or indexed cases.

    Nodes include id, label, type, data_layer, record_status, href.
    Edges include id, source, target, type, quality_level, provenance.
    Falls back to YAML-derived data when Neo4j is unavailable.
    """
    case = get_case(case_id)
    if case:
        return _neighborhood_canonical(case)

    if include_indexed:
        entry = get_indexed_case(case_id)
        if entry:
            return _neighborhood_indexed(entry)

    raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")


def _neighborhood_canonical(case: CaseRecord) -> GraphNeighborhoodResponse:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    center_id = f"case:{case.case_id}"

    nodes.append(GraphNode(
        id=center_id,
        label=case.case_name,
        type="case",
        data_layer="canonical",
        record_status="canonical_reviewed",
        href=f"/cases/{case.case_id}",
    ))

    quality = "canonical_reviewed"

    auth_id = f"authority:{case.authority}"
    nodes.append(GraphNode(id=auth_id, label=case.authority, type="authority"))
    edges.append(GraphEdge(
        id=f"{center_id}->{auth_id}:DECIDED_BY",
        source=center_id, target=auth_id, type="DECIDED_BY",
        quality_level=quality,
    ))

    sector_id = f"sector:{case.sector}"
    nodes.append(GraphNode(id=sector_id, label=case.sector, type="sector"))
    edges.append(GraphEdge(
        id=f"{center_id}->{sector_id}:CONCERNS_SECTOR",
        source=center_id, target=sector_id, type="CONCERNS_SECTOR",
        quality_level=quality,
    ))

    outcome_id = f"outcome:{case.outcome.value}"
    nodes.append(GraphNode(id=outcome_id, label=case.outcome.value.replace("_", " "), type="outcome"))
    edges.append(GraphEdge(
        id=f"{center_id}->{outcome_id}:RESULTED_IN",
        source=center_id, target=outcome_id, type="RESULTED_IN",
        quality_level=quality,
    ))

    for party in case.parties:
        party_id = f"party:{party.name}:{party.role.value}"
        nodes.append(GraphNode(id=party_id, label=f"{party.name} ({party.role.value})", type="party"))
        edges.append(GraphEdge(
            id=f"{center_id}->{party_id}:INVOLVES_PARTY",
            source=center_id, target=party_id, type="INVOLVES_PARTY",
            quality_level=quality,
        ))

    for pm in case.product_markets_considered:
        pm_id = f"product_market:{pm.market_id}"
        nodes.append(GraphNode(id=pm_id, label=pm.name, type="product_market"))
        edges.append(GraphEdge(
            id=f"{center_id}->{pm_id}:CONSIDERED_PRODUCT_MARKET",
            source=center_id, target=pm_id, type="CONSIDERED_PRODUCT_MARKET",
            quality_level=quality,
        ))

    for gm in case.geographic_markets_considered:
        gm_id = f"geographic_market:{gm.market_id}"
        nodes.append(GraphNode(id=gm_id, label=gm.name, type="geographic_market"))
        edges.append(GraphEdge(
            id=f"{center_id}->{gm_id}:CONSIDERED_GEOGRAPHIC_MARKET",
            source=center_id, target=gm_id, type="CONSIDERED_GEOGRAPHIC_MARKET",
            quality_level=quality,
        ))

    for toh in case.theories_of_harm:
        toh_id = f"theory_of_harm:{toh.theory_id}"
        nodes.append(GraphNode(id=toh_id, label=toh.name, type="theory_of_harm"))
        edges.append(GraphEdge(
            id=f"{center_id}->{toh_id}:APPLIES_THEORY",
            source=center_id, target=toh_id, type="APPLIES_THEORY",
            quality_level=quality,
        ))

    for ref in case.concept_refs:
        concept_id = f"concept:{ref.concept_id}"
        nodes.append(GraphNode(id=concept_id, label=ref.concept_id.replace("_", " "), type="concept"))
        edges.append(GraphEdge(
            id=f"{center_id}->{concept_id}:REFERENCES_CONCEPT",
            source=center_id, target=concept_id, type="REFERENCES_CONCEPT",
            quality_level=ref.quality_level,
            provenance=ref.provenance,
        ))

    for sim in case.similar_cases:
        sim_case_id = f"case:{sim.case_id}"
        href = f"/cases/{sim.case_id}"
        data_layer = "canonical"
        record_status = "canonical_reviewed"
        if not get_case(sim.case_id):
            href = f"/indexed-cases/{sim.case_id}"
            data_layer = "indexed"
            record_status = "indexed_metadata"
        nodes.append(GraphNode(
            id=sim_case_id,
            label=sim.case_id.replace("_", " "),
            type="case",
            data_layer=data_layer,
            record_status=record_status,
            href=href,
        ))
        edges.append(GraphEdge(
            id=f"{center_id}->{sim_case_id}:SIMILAR_TO",
            source=center_id, target=sim_case_id, type="SIMILAR_TO",
            quality_level=quality,
        ))

    return GraphNeighborhoodResponse(
        center_case_id=case.case_id,
        nodes=nodes,
        edges=edges,
        source="yaml",
    )


def _neighborhood_indexed(entry: CaseIndexEntry) -> GraphNeighborhoodResponse:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    center_id = f"case:{entry.case_id}"

    nodes.append(GraphNode(
        id=center_id,
        label=entry.case_name,
        type="case",
        data_layer="indexed",
        record_status="indexed_metadata",
        href=f"/indexed-cases/{entry.case_id}",
    ))

    quality = "indexed_metadata"

    auth_id = f"authority:{entry.authority}"
    nodes.append(GraphNode(id=auth_id, label=entry.authority, type="authority"))
    edges.append(GraphEdge(
        id=f"{center_id}->{auth_id}:DECIDED_BY",
        source=center_id, target=auth_id, type="DECIDED_BY",
        quality_level=quality,
    ))

    sector_id = f"sector:{entry.sector}"
    nodes.append(GraphNode(id=sector_id, label=entry.sector, type="sector"))
    edges.append(GraphEdge(
        id=f"{center_id}->{sector_id}:CONCERNS_SECTOR",
        source=center_id, target=sector_id, type="CONCERNS_SECTOR",
        quality_level=quality,
    ))

    outcome_id = f"outcome:{entry.outcome.value}"
    nodes.append(GraphNode(id=outcome_id, label=entry.outcome.value.replace("_", " "), type="outcome"))
    edges.append(GraphEdge(
        id=f"{center_id}->{outcome_id}:RESULTED_IN",
        source=center_id, target=outcome_id, type="RESULTED_IN",
        quality_level=quality,
    ))

    for party in entry.parties:
        party_id = f"party:{party.name}:{party.role.value}"
        nodes.append(GraphNode(id=party_id, label=f"{party.name} ({party.role.value})", type="party"))
        edges.append(GraphEdge(
            id=f"{center_id}->{party_id}:INVOLVES_PARTY",
            source=center_id, target=party_id, type="INVOLVES_PARTY",
            quality_level=quality,
        ))

    for ref in entry.concept_refs:
        concept_id = f"concept:{ref.concept_id}"
        nodes.append(GraphNode(id=concept_id, label=ref.concept_id.replace("_", " "), type="concept"))
        edges.append(GraphEdge(
            id=f"{center_id}->{concept_id}:REFERENCES_CONCEPT",
            source=center_id, target=concept_id, type="REFERENCES_CONCEPT",
            quality_level=ref.quality_level,
            provenance=ref.provenance,
        ))

    return GraphNeighborhoodResponse(
        center_case_id=entry.case_id,
        nodes=nodes,
        edges=edges,
        source="yaml",
    )


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
