from typing import Literal

from fastapi import APIRouter, Query

from app.cases.models import CaseRecord
from app.cases.models.api_responses import CaseSearchHit
from app.cases.services.case_catalog import CatalogSearchQuery, get_case_catalog
from app.cases.services.case_service import search_cases
from app.cases.services.semantic_search_service import (
    search_cases_semantic,
    search_markets_semantic,
)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[CaseRecord])
def search(q: str = Query(..., min_length=1, description="Search query")):
    return search_cases(q)


@router.get("/search/semantic", response_model=list[CaseSearchHit])
async def search_semantic(
    q: str = Query(..., min_length=1, description="Natural language query"),
    top_k: int = Query(default=10, ge=1, le=50),
):
    rows = await search_cases_semantic(q, top_k=top_k)
    catalog = get_case_catalog()
    hits: list[CaseSearchHit] = []
    for row in rows:
        record = catalog.get(row["case_id"], include_indexed=False)
        if record:
            hit = catalog.project_hit(record)
            hit.similarity_score = float(row["similarity"])
            hits.append(hit)
    return hits


@router.get("/search/market", response_model=list[dict])
async def search_market(
    name: str = Query(..., min_length=1, description="Market name to find similar cases"),
    top_k: int = Query(default=20, ge=1, le=100),
):
    return await search_markets_semantic(name, top_k=top_k)


@router.get("/search/all", response_model=list[CaseSearchHit])
def search_all(
    q: str = Query(..., min_length=1, description="Search query"),
    scope: Literal["all", "canonical", "indexed"] = Query(
        "all", description="Which record layer to search: all, canonical, or indexed"
    ),
    jurisdiction: str | None = Query(None),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
):
    return get_case_catalog().search(CatalogSearchQuery(
        q=q,
        scope=scope,
        jurisdiction=jurisdiction,
        year_from=year_from,
        year_to=year_to,
    ))
