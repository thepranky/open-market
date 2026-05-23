from fastapi import APIRouter, Query

from app.models import CaseRecord
from app.services.case_service import search_cases

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[CaseRecord])
def search(q: str = Query(..., min_length=1, description="Search query")):
    return search_cases(q)
