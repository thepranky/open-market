"""US case-index discovery contract shared by future DOJ and FTC scrapers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

try:
    from scripts.cases.discovery.case_index_builder import (
        CaseIndexParty,
        CaseIndexSeed,
        build_case_index_dict,
    )
except ModuleNotFoundError:
    from case_index_builder import (
        CaseIndexParty,
        CaseIndexSeed,
        build_case_index_dict,
    )


@dataclass(frozen=True)
class UsScrapedCase:
    authority: Literal["DOJ", "FTC"]
    case_name: str
    parties: tuple[CaseIndexParty, ...]
    source_url: str
    decision_date: str | None
    outcome_guess: str | None
    sector: str


def generate_us_case_id(authority: Literal["DOJ", "FTC"], case_name: str, year: str) -> str:
    """Generate a stable US case-index id for a DOJ or FTC matter."""
    authority_slug = authority.lower()
    name_slug = re.sub(r"[^a-z0-9]+", "_", case_name.lower())
    name_slug = re.sub(r"_+", "_", name_slug).strip("_")
    if len(name_slug) > 60:
        name_slug = name_slug[:60].rstrip("_")
    if not name_slug:
        name_slug = "case"
    return f"us_{authority_slug}_{name_slug}_{year}"


def to_case_index_seed(record: UsScrapedCase) -> CaseIndexSeed:
    """Convert one US scraped listing record into the shared case-index seed."""
    if record.decision_date is None:
        raise ValueError("decision_date is required to build a case-index entry")
    year = record.decision_date[:4]
    return CaseIndexSeed(
        case_id=generate_us_case_id(record.authority, record.case_name, year),
        case_name=record.case_name,
        jurisdiction="US",
        authority=record.authority,
        decision_date=record.decision_date,
        sector=record.sector,
        outcome=record.outcome_guess or "pending",
        source_url=record.source_url,
        parties=record.parties,
    )


def to_case_index_dict(record: UsScrapedCase) -> dict:
    """Convert one US scraped listing record into a validated CaseIndexEntry dict."""
    return build_case_index_dict(to_case_index_seed(record))
