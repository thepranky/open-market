"""Shared helpers for building validated case-index discovery records."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_API_DIR = Path(__file__).resolve().parents[3]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.cases.models.case_index import CaseIndexEntry  # noqa: E402

PartyRoleValue = Literal["acquirer", "target", "merged_entity", "third_party"]


@dataclass(frozen=True)
class CaseIndexParty:
    name: str
    role: PartyRoleValue


@dataclass(frozen=True)
class CaseIndexSeed:
    case_id: str
    case_name: str
    jurisdiction: Literal["EU", "UK", "US"]
    authority: str
    decision_date: str
    sector: str
    outcome: str
    source_url: str | None = None
    ai_summary: str | None = None
    parties: tuple[CaseIndexParty, ...] = ()


def build_case_index_dict(seed: CaseIndexSeed) -> dict:
    """Build and validate a YAML-safe CaseIndexEntry dict from a normalized seed."""
    record = {
        "case_id": seed.case_id,
        "case_name": seed.case_name,
        "jurisdiction": seed.jurisdiction,
        "authority": seed.authority,
        "decision_date": seed.decision_date,
        "sector": seed.sector,
        "outcome": seed.outcome,
        "case_type": "merger",
        "source_url": seed.source_url,
        "ai_summary": seed.ai_summary,
        "parties": [
            {"name": party.name, "role": party.role}
            for party in seed.parties
        ],
        "concept_refs": [],
    }
    entry = CaseIndexEntry.model_validate(record)
    return entry.model_dump(
        mode="json",
        exclude={"pdf_url", "pdf_language", "extraction_status"},
    )
