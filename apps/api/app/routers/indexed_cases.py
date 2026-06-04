from fastapi import APIRouter, HTTPException, Query

from app.models.api_responses import IndexedCaseDetail
from app.models.case_index import CaseIndexEntry
from app.services.index_case_service import get_all_indexed, get_indexed_case

router = APIRouter(prefix="/indexed-cases", tags=["indexed-cases"])


def _to_detail(entry: CaseIndexEntry) -> IndexedCaseDetail:
    return IndexedCaseDetail.model_validate(entry.model_dump())


@router.get("", response_model=list[IndexedCaseDetail])
def list_indexed_cases(
    jurisdiction: str | None = Query(None),
    sector: str | None = Query(None),
    outcome: str | None = Query(None),
):
    entries = get_all_indexed()
    if jurisdiction:
        entries = [e for e in entries if e.jurisdiction.upper() == jurisdiction.upper()]
    if sector:
        entries = [e for e in entries if sector.lower() in e.sector.lower()]
    if outcome:
        entries = [e for e in entries if e.outcome.value == outcome]
    return [_to_detail(e) for e in entries]


@router.get("/{case_id}", response_model=IndexedCaseDetail)
def indexed_case_detail(case_id: str):
    entry = get_indexed_case(case_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Indexed case '{case_id}' not found")
    return _to_detail(entry)
