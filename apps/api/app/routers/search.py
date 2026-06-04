from typing import Literal

from fastapi import APIRouter, Query

from app.models import CaseRecord
from app.models.api_responses import CaseSearchHit
from app.services.case_service import search_cases
from app.services.index_case_service import search_indexed

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[CaseRecord])
def search(q: str = Query(..., min_length=1, description="Search query")):
    return search_cases(q)


def _canonical_to_hit(case: CaseRecord) -> CaseSearchHit:
    source_url = next(
        (d.case_page_url for d in case.source_documents if d.case_page_url),
        None,
    ) or next(
        (d.url for d in case.source_documents if d.url),
        None,
    )
    return CaseSearchHit(
        data_layer="canonical",
        record_status="canonical_reviewed",
        case_id=case.case_id,
        case_name=case.case_name,
        jurisdiction=case.jurisdiction,
        authority=case.authority,
        decision_date=case.decision_date,
        sector=case.sector,
        outcome=case.outcome,
        case_type=case.case_type,
        source_url=source_url,
        ai_summary=case.ai_summary,
        parties=case.parties,
        concept_refs=case.concept_refs,
        product_market_count=len(case.product_markets_considered),
        theory_count=len(case.theories_of_harm),
        source_passage_count=len(case.source_passages),
    )


def _indexed_to_hit(entry) -> CaseSearchHit:
    return CaseSearchHit(
        data_layer="indexed",
        record_status="indexed_metadata",
        case_id=entry.case_id,
        case_name=entry.case_name,
        jurisdiction=entry.jurisdiction,
        authority=entry.authority,
        decision_date=entry.decision_date,
        sector=entry.sector,
        outcome=entry.outcome,
        case_type=entry.case_type,
        source_url=entry.source_url,
        ai_summary=entry.ai_summary,
        parties=entry.parties,
        concept_refs=entry.concept_refs,
    )


@router.get("/search/all", response_model=list[CaseSearchHit])
def search_all(
    q: str = Query(..., min_length=1, description="Search query"),
    scope: Literal["all", "canonical", "indexed"] = Query(
        "all", description="Which record layer to search: all, canonical, or indexed"
    ),
):
    hits: list[CaseSearchHit] = []
    if scope in ("all", "canonical"):
        hits.extend(_canonical_to_hit(c) for c in search_cases(q))
    if scope in ("all", "indexed"):
        hits.extend(_indexed_to_hit(e) for e in search_indexed(q))
    return hits
