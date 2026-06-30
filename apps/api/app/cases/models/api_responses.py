"""Presentation-layer response models for the indexed-case and combined-search endpoints."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

from .case import Outcome, Party
from .concept import ConceptRef


class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # "case" | "authority" | "sector" | "outcome" | "party" | "concept" | "product_market" | "geographic_market" | "theory_of_harm"
    data_layer: Optional[str] = None  # "canonical" | "indexed"
    record_status: Optional[str] = None  # "canonical_reviewed" | "indexed_metadata"
    href: Optional[str] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    quality_level: Optional[str] = None
    provenance: Optional[str] = None


class GraphNeighborhoodResponse(BaseModel):
    center_case_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    source: str = "yaml"


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
    pdf_url: Optional[str] = None
    pdf_language: Optional[str] = None
    ai_summary: Optional[str] = None
    parties: list[Party]
    concept_refs: list[ConceptRef]
    extraction_status: Optional[Literal["pending", "not_applicable", "extracted"]] = None


class CaseSearchHit(BaseModel):
    """Flat search summary valid for both canonical and indexed cases.

    data_layer and record_status are always present so callers can branch on them.
    For indexed hits product_market_count / theory_count / source_passage_count are 0.
    """

    data_layer: str
    record_status: str
    href: Optional[str] = None

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

    # Only present for semantic search results.
    similarity_score: Optional[float] = None
