"""Presentation-layer response models for the indexed-case and combined-search endpoints."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.case import Outcome, Party
from app.models.concept import ConceptRef


class IndexedCaseDetail(BaseModel):
    """Lightweight record from data/case_index/. No source-backed legal propositions."""

    data_layer: Literal["indexed"] = "indexed"
    record_status: Literal["indexed_metadata"] = "indexed_metadata"

    case_id: str
    case_name: str
    jurisdiction: str
    authority: str
    decision_date: date
    sector: str
    outcome: Outcome
    case_type: str
    source_url: Optional[str] = None
    ai_summary: Optional[str] = None
    parties: list[Party]
    concept_refs: list[ConceptRef]


class CaseSearchHit(BaseModel):
    """Flat search summary valid for both canonical and indexed cases.

    data_layer and record_status are always present so callers can branch on them.
    For indexed hits product_market_count / theory_count / source_passage_count are 0.
    """

    data_layer: str
    record_status: str

    case_id: str
    case_name: str
    jurisdiction: str
    authority: str
    decision_date: date
    sector: str
    outcome: Outcome
    case_type: str
    source_url: Optional[str] = None
    ai_summary: Optional[str] = None
    parties: list[Party]
    concept_refs: list[ConceptRef]

    # Summary counts — populated for canonical records; always 0 for indexed.
    product_market_count: int = 0
    theory_count: int = 0
    source_passage_count: int = 0
