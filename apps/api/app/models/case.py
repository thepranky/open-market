from datetime import date
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ExtractionMethod(str, Enum):
    ai_extracted = "ai_extracted"
    manually_added = "manually_added"
    imported_metadata = "imported_metadata"
    pdf_extracted = "pdf_extracted"


class ReviewStatus(str, Enum):
    unreviewed = "unreviewed"
    spot_checked = "spot_checked"
    lawyer_reviewed = "lawyer_reviewed"


class DefinitionStatus(str, Enum):
    defined = "defined"
    discussed = "discussed"
    segmented = "segmented"
    left_open = "left_open"
    considered = "considered"   # Commission adopted a working market basis with cautious/context-specific
                                # wording (e.g. "for the purpose of this decision…"); lower precedential
                                # weight than "defined", more concrete than "left_open".


class PartyRole(str, Enum):
    acquirer = "acquirer"
    target = "target"
    merged_entity = "merged_entity"
    third_party = "third_party"


class Outcome(str, Enum):
    cleared = "cleared"
    cleared_with_remedies = "cleared_with_remedies"   # backward compat
    cleared_with_conditions = "cleared_with_conditions"
    blocked = "blocked"
    abandoned = "abandoned"
    referred = "referred"
    pending = "pending"
    pending_litigation = "pending_litigation"
    under_appeal = "under_appeal"
    annulled = "annulled"
    partially_annulled = "partially_annulled"
    upheld_on_appeal = "upheld_on_appeal"
    unknown = "unknown"


class VerificationStatus(str, Enum):
    source_linked = "source_linked"
    verified = "verified"
    no_source_linked = "no_source_linked"


class RetrievalStatus(str, Enum):
    direct = "direct"
    fallback = "fallback"
    broken = "broken"
    unknown = "unknown"


class CaseHistoryStatus(str, Enum):
    final_no_known_challenge = "final_no_known_challenge"
    challenged = "challenged"
    pending_litigation = "pending_litigation"
    under_appeal = "under_appeal"
    upheld = "upheld"
    upheld_on_appeal = "upheld_on_appeal"
    annulled = "annulled"
    partially_annulled = "partially_annulled"
    withdrawn = "withdrawn"
    settled = "settled"
    unknown = "unknown"


class PropositionVerification(BaseModel):
    verification_status: VerificationStatus = VerificationStatus.no_source_linked
    verified_by: Optional[str] = None
    verified_at: Optional[date] = None
    verification_notes: Optional[str] = None
    verification_count: int = 0


class CaseHistoryEvent(BaseModel):
    event_type: str
    event_date: Optional[date] = None  # NOT 'date' — would shadow datetime.date in Pydantic v2
    forum: Optional[str] = None
    case_number: Optional[str] = None
    title: str
    outcome: Optional[str] = None
    source_url: Optional[str] = None
    summary: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.unreviewed


class CaseHistory(BaseModel):
    status: CaseHistoryStatus = CaseHistoryStatus.unknown
    events: list[CaseHistoryEvent] = Field(default_factory=list)


class SourcePassage(BaseModel):
    passage_id: str
    source_document_id: str
    page: Optional[str] = None
    paragraph: Optional[str] = None
    section: Optional[str] = None
    quote_snippet: str
    extraction_method: ExtractionMethod
    review_status: ReviewStatus
    confidence_score: float = Field(ge=0.0, le=1.0)
    last_checked_date: date
    supports_markets: list[str] = Field(default_factory=list)
    supports_geographic_markets: list[str] = Field(default_factory=list)
    supports_theories: list[str] = Field(default_factory=list)


class SourceDocument(BaseModel):
    doc_id: str
    title: str
    url: Optional[str] = None           # generic fallback URL (kept for backward compat)
    pdf_url: Optional[str] = None       # direct PDF link
    case_page_url: Optional[str] = None # authority case registry page
    doc_type: str
    authority_reference: Optional[str] = None
    retrieval_status: RetrievalStatus = RetrievalStatus.unknown
    published_date: Optional[date] = None
    last_checked: Optional[date] = None


class Party(BaseModel):
    name: str
    role: PartyRole


class ProductMarket(BaseModel):
    market_id: str
    name: str
    definition_status: DefinitionStatus
    notes: Optional[str] = None
    verification: Optional[PropositionVerification] = None


class GeographicMarket(BaseModel):
    market_id: str
    name: str
    definition_status: DefinitionStatus
    notes: Optional[str] = None
    verification: Optional[PropositionVerification] = None


class TheoryOfHarm(BaseModel):
    theory_id: str
    name: str
    description: Optional[str] = None
    verification: Optional[PropositionVerification] = None


class SimilarCase(BaseModel):
    case_id: str
    score: float = Field(ge=0.0, le=1.0)
    method: str
    reasons: list[str]


class CaseMetadata(BaseModel):
    extraction_method: ExtractionMethod
    review_status: ReviewStatus
    overall_confidence: float = Field(ge=0.0, le=1.0)
    created_date: date
    last_updated_date: date
    tags: list[str] = Field(default_factory=list)


class CaseRecord(BaseModel):
    case_id: str
    case_name: str
    jurisdiction: str
    authority: str
    decision_date: date
    case_type: str = "merger"
    procedure_stage: str
    sector: str
    parties: list[Party]
    outcome: Outcome
    remedies: list[str] = Field(default_factory=list)
    theories_of_harm: list[TheoryOfHarm] = Field(default_factory=list)
    product_markets_considered: list[ProductMarket] = Field(default_factory=list)
    geographic_markets_considered: list[GeographicMarket] = Field(default_factory=list)
    source_documents: list[SourceDocument] = Field(default_factory=list)
    source_passages: list[SourcePassage] = Field(default_factory=list)
    similar_cases: list[SimilarCase] = Field(default_factory=list)
    ai_summary: Optional[str] = None
    case_history: Optional[CaseHistory] = None
    metadata: CaseMetadata

    @field_validator("jurisdiction")
    @classmethod
    def validate_jurisdiction(cls, v: str) -> str:
        allowed = {"EU", "UK", "US"}
        if v not in allowed:
            raise ValueError(f"jurisdiction must be one of {allowed}")
        return v

    def to_graph_dict(self) -> dict[str, Any]:
        """Flatten to a dict suitable for Neo4j node properties."""
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "jurisdiction": self.jurisdiction,
            "authority": self.authority,
            "decision_date": self.decision_date.isoformat(),
            "case_type": self.case_type,
            "procedure_stage": self.procedure_stage,
            "sector": self.sector,
            "outcome": self.outcome.value,
            "ai_summary": self.ai_summary,
        }
