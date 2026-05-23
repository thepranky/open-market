from fastapi import APIRouter, HTTPException, Query

from app.models import CaseRecord
from app.services.case_service import get_all_cases, get_case, search_cases

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseRecord])
def list_cases(
    jurisdiction: str | None = Query(None),
    sector: str | None = Query(None),
    outcome: str | None = Query(None),
):
    cases = get_all_cases()
    if jurisdiction:
        cases = [c for c in cases if c.jurisdiction.upper() == jurisdiction.upper()]
    if sector:
        cases = [c for c in cases if sector.lower() in c.sector.lower()]
    if outcome:
        cases = [c for c in cases if c.outcome.value == outcome]
    return cases


@router.get("/{case_id}", response_model=CaseRecord)
def case_detail(case_id: str):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    return case
