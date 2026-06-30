from fastapi import APIRouter, HTTPException, Query

from app.cases.models import CaseRecord
from app.cases.services.case_catalog import CatalogListQuery, get_case_catalog

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseRecord])
def list_cases(
    jurisdiction: str | None = Query(None),
    sector: str | None = Query(None),
    outcome: str | None = Query(None),
    theory: str | None = Query(None, description="Filter by theory of harm keyword"),
    year_from: int | None = Query(None, description="Earliest decision year (inclusive)"),
    year_to: int | None = Query(None, description="Latest decision year (inclusive)"),
):
    records = get_case_catalog().list(CatalogListQuery(
        scope="canonical",
        jurisdiction=jurisdiction,
        sector=sector,
        outcome=outcome,
        theory=theory,
        year_from=year_from,
        year_to=year_to,
    ))
    return [record.canonical for record in records]


@router.get("/{case_id}", response_model=CaseRecord)
def case_detail(case_id: str):
    record = get_case_catalog().get(case_id, include_indexed=False)
    if not record:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    return record.canonical
