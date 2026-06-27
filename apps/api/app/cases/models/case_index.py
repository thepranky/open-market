from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .case import Outcome, Party
from .concept import ConceptRef

# Whether an index entry is a candidate for deep extraction into a canonical record:
#   extracted      — a canonical CaseRecord already exists for this case
#   not_applicable — simplified procedure / no market-analysis sections to extract
#   pending        — substantive, not yet extracted
ExtractionStatus = Literal["pending", "not_applicable", "extracted"]


class CaseIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    case_name: str
    jurisdiction: str
    authority: str
    decision_date: date
    sector: str
    outcome: Outcome
    case_type: str = "merger"
    source_url: Optional[str] = None
    pdf_url: Optional[str] = None
    # ISO 639-2 code of the resolved pdf_url's language manifestation (e.g. "deu",
    # "fra"). EC simplified clearances are often published only in the authentic
    # language; this records which one was resolved. Set by the PDF resolver.
    pdf_language: Optional[str] = None
    ai_summary: Optional[str] = None
    parties: list[Party] = Field(default_factory=list)
    concept_refs: list[ConceptRef] = Field(default_factory=list)
    extraction_status: Optional[ExtractionStatus] = None

    @field_validator("jurisdiction")
    @classmethod
    def validate_jurisdiction(cls, v: str) -> str:
        allowed = {"EU", "UK", "US"}
        if v not in allowed:
            raise ValueError(f"jurisdiction must be one of {allowed}")
        return v
