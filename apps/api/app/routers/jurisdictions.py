"""Jurisdiction threshold screening endpoints."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.models.jurisdiction import JurisdictionRule
from app.services.threshold_engine import (
    DealParameters,
    RevenueByScope,
    JurisdictionScreeningResult,
    load_all_jurisdictions,
    load_jurisdiction,
    screen_all,
    screen_jurisdiction,
)

router = APIRouter(prefix="/jurisdictions", tags=["jurisdictions"])

DATA_DIR = os.path.join(os.path.dirname(settings.data_cases_path), "jurisdictions")


def _get_rules() -> list[JurisdictionRule]:
    try:
        return load_all_jurisdictions(DATA_DIR)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load jurisdiction data: {e}")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RevenueByScopeInput(BaseModel):
    worldwide: Optional[float] = None
    domestic: Optional[float] = None
    eu_eea: Optional[float] = None
    uk: Optional[float] = None
    us: Optional[float] = None
    by_country: dict[str, float] = {}


class ScreeningRequest(BaseModel):
    acquirer: RevenueByScopeInput = RevenueByScopeInput()
    target: RevenueByScopeInput = RevenueByScopeInput()
    acquirer_assets: Optional[float] = None
    target_assets: Optional[float] = None
    deal_value: Optional[float] = None
    deal_currency: str = "EUR"
    revenue_currency: str = "EUR"
    fx_rates: dict[str, float] = {}
    combined_market_share: dict[str, float] = {}
    acquirer_market_share: dict[str, float] = {}
    incremental_share: dict[str, float] = {}


class ConditionResultResponse(BaseModel):
    condition_id: str
    met: Optional[bool]
    actual_value: Optional[float]
    threshold_value: float
    gap: Optional[float]
    note: Optional[str] = None
    missing_data: Optional[str] = None


class TestResultResponse(BaseModel):
    test_id: str
    fired: Optional[bool]
    description: Optional[str] = None
    excluded: bool
    exclusion_reason: Optional[str]
    conditions: list[ConditionResultResponse]


class ScreeningResultResponse(BaseModel):
    jurisdiction_id: str
    jurisdiction_name: str
    status: str
    triggered_by: list[str]
    confidence: str
    filing_type: Optional[str]
    suspensory: Optional[bool]
    test_results: list[TestResultResponse]
    notes: list[str]


def _to_deal(req: ScreeningRequest) -> DealParameters:
    def _rev(r: RevenueByScopeInput) -> RevenueByScope:
        return RevenueByScope(
            worldwide=r.worldwide,
            domestic=r.domestic,
            eu_eea=r.eu_eea,
            uk=r.uk,
            us=r.us,
            by_country=r.by_country,
        )

    return DealParameters(
        acquirer=_rev(req.acquirer),
        target=_rev(req.target),
        acquirer_assets=req.acquirer_assets,
        target_assets=req.target_assets,
        deal_value=req.deal_value,
        deal_currency=req.deal_currency,
        revenue_currency=req.revenue_currency,
        fx_rates=req.fx_rates,
        combined_market_share=req.combined_market_share,
        acquirer_market_share=req.acquirer_market_share,
        incremental_share=req.incremental_share,
    )


def _serialise(r: JurisdictionScreeningResult) -> ScreeningResultResponse:
    return ScreeningResultResponse(
        jurisdiction_id=r.jurisdiction_id,
        jurisdiction_name=r.jurisdiction_name,
        status=r.status.value,
        triggered_by=r.triggered_by,
        confidence=r.confidence,
        filing_type=r.filing_type,
        suspensory=r.suspensory,
        test_results=[
            TestResultResponse(
                test_id=t.test_id,
                fired=t.fired,
                description=t.description,
                excluded=t.excluded,
                exclusion_reason=t.exclusion_reason,
                conditions=[
                    ConditionResultResponse(
                        condition_id=c.condition_id,
                        met=c.met,
                        actual_value=c.actual_value,
                        threshold_value=c.threshold_value,
                        gap=c.gap,
                        note=c.note,
                        missing_data=c.missing_data,
                    )
                    for c in t.conditions
                ],
            )
            for t in r.test_results
        ],
        notes=r.notes,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[dict[str, Any]])
def list_jurisdictions():
    """List all available jurisdiction rules (metadata only)."""
    rules = _get_rules()
    return [
        {
            "jurisdiction_id": r.jurisdiction_id,
            "jurisdiction_name": r.jurisdiction_name,
            "authority": r.authority.abbreviation,
            "mandatory": r.regime.mandatory,
            "suspensory": r.regime.suspensory,
            "last_verified": r.last_verified.isoformat(),
            "test_count": len(r.threshold_tests),
        }
        for r in rules
    ]


@router.get("/{jurisdiction_id}", response_model=dict[str, Any])
def get_jurisdiction(jurisdiction_id: str):
    """Return the full rule set for a single jurisdiction."""
    try:
        rule = load_jurisdiction(jurisdiction_id, DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Jurisdiction '{jurisdiction_id}' not found")
    return rule.model_dump()


@router.get("/{jurisdiction_id}/passages", response_model=list[dict[str, Any]])
def get_jurisdiction_passages(jurisdiction_id: str):
    """Return source passages (verbatim statutory quotes) for a jurisdiction."""
    try:
        rule = load_jurisdiction(jurisdiction_id, DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Jurisdiction '{jurisdiction_id}' not found")
    return [p.model_dump() for p in rule.source_passages]


@router.post("/screen", response_model=list[ScreeningResultResponse])
def screen_all_jurisdictions(req: ScreeningRequest):
    """Screen a deal against all loaded jurisdictions."""
    rules = _get_rules()
    deal = _to_deal(req)
    results = screen_all(deal, rules)
    return [_serialise(r) for r in results]


@router.post("/screen/{jurisdiction_id}", response_model=ScreeningResultResponse)
def screen_single_jurisdiction(jurisdiction_id: str, req: ScreeningRequest):
    """Screen a deal against a single jurisdiction."""
    try:
        rule = load_jurisdiction(jurisdiction_id, DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Jurisdiction '{jurisdiction_id}' not found")
    deal = _to_deal(req)
    result = screen_jurisdiction(deal, rule)
    return _serialise(result)
