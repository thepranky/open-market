from fastapi import APIRouter, HTTPException, Query

from app.cases.models.api_responses import IndexedCaseDetail
from app.cases.services.case_catalog import CatalogListQuery, get_case_catalog

router = APIRouter(prefix="/indexed-cases", tags=["indexed-cases"])


@router.get("", response_model=list[IndexedCaseDetail])
def list_indexed_cases(
    jurisdiction: str | None = Query(None),
    sector: str | None = Query(None),
    outcome: str | None = Query(None),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
):
    catalog = get_case_catalog()
    records = catalog.list(CatalogListQuery(
        scope="indexed",
        jurisdiction=jurisdiction,
        sector=sector,
        outcome=outcome,
        year_from=year_from,
        year_to=year_to,
    ))
    return [catalog.project_indexed_detail(record) for record in records]


@router.get("/{case_id}", response_model=IndexedCaseDetail)
def indexed_case_detail(case_id: str):
    catalog = get_case_catalog()
    record = catalog.get(case_id, data_layer="indexed")
    if not record:
        raise HTTPException(status_code=404, detail=f"Indexed case '{case_id}' not found")
    return catalog.project_indexed_detail(record)
