from typing import Optional

from pydantic import BaseModel, Field


class ConceptRef(BaseModel):
    concept_id: str
    quality_level: str  # "canonical" | "indexed"
    provenance: str     # e.g. "ai_extracted" | "manually_tagged" | "yaml_concept_field"


class ConceptNode(BaseModel):
    concept_id: str
    name: str
    category: str  # e.g. "theory_of_harm" | "market_type" | "remedy_type" | "sector"
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
