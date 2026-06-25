from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .case import Outcome, Party
from .concept import ConceptRef


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
    ai_summary: Optional[str] = None
    parties: list[Party] = Field(default_factory=list)
    concept_refs: list[ConceptRef] = Field(default_factory=list)

    @field_validator("jurisdiction")
    @classmethod
    def validate_jurisdiction(cls, v: str) -> str:
        allowed = {"EU", "UK", "US"}
        if v not in allowed:
            raise ValueError(f"jurisdiction must be one of {allowed}")
        return v
