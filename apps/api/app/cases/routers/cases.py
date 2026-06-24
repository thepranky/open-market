from fastapi import APIRouter, HTTPException, Query

from app.cases.models import CaseRecord
from app.cases.services.case_service import get_all_cases, get_case, search_cases

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
    cases = get_all_cases()
    if jurisdiction:
        cases = [c for c in cases if c.jurisdiction.upper() == jurisdiction.upper()]
    if sector:
        cases = [c for c in cases if sector.lower() in c.sector.lower()]
    if outcome:
        cases = [c for c in cases if c.outcome.value == outcome]
    if theory:
        tl = theory.lower()
        cases = [
            c for c in cases
            if any(tl in t.name.lower() or tl in (t.description or "").lower()
                   for t in c.theories_of_harm)
        ]
    if year_from:
        cases = [c for c in cases if c.decision_date.year >= year_from]
    if year_to:
        cases = [c for c in cases if c.decision_date.year <= year_to]
    return cases


@router.get("/{case_id}", response_model=CaseRecord)
def case_detail(case_id: str):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    return case
