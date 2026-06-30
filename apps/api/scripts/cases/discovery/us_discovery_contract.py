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


_CAPTION_PREFIXES = (
    r"u\.?s\.?\s+et\s+al\.?\s+v\.?\s+",
    r"united\s+states\s+et\s+al\.?\s+v\.?\s+",
    r"united\s+states\s+v\.?\s+",
    r"federal\s+trade\s+commission\s+v\.?\s+",
    r"ftc\s+v\.?\s+",
)
_LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "lp",
    "plc",
}
_DESCRIPTORS = {
    "airlines",
    "airways",
    "group",
    "holdings",
    "northeast",
    "unlimited",
}
_PHRASE_SLUGS = (
    ("at and t", "att"),
    ("at t", "att"),
    ("time warner", "timewarner"),
    ("change healthcare", "changehealthcare"),
    ("simon schuster", "simonschuster"),
    ("activision blizzard", "activision"),
    ("penguin random house", "penguin"),
)


def _strip_caption_boilerplate(case_name: str) -> str:
    normalized = case_name.strip()
    for pattern in _CAPTION_PREFIXES:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r",?\s+in\s+the\s+matter\s+of\s*$", "", normalized, flags=re.IGNORECASE)
    return normalized


def _party_slug(party_name: str) -> str:
    normalized = party_name.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for phrase, replacement in _PHRASE_SLUGS:
        normalized = re.sub(rf"\b{re.escape(phrase)}\b", replacement, normalized)
    tokens = [
        token
        for token in normalized.split()
        if token not in _LEGAL_SUFFIXES and token not in _DESCRIPTORS and token != "and"
    ]
    return "_".join(tokens)


def generate_us_case_id(authority: Literal["DOJ", "FTC"], case_name: str, year: str) -> str:
    """Generate a stable US case-index id for a DOJ or FTC matter."""
    authority_slug = authority.lower()
    normalized = _strip_caption_boilerplate(case_name)
    party_slugs = [
        slug
        for slug in (
            _party_slug(part)
            for part in re.split(r"\s*(?:/|\+|,?\s+and\s+)\s*", normalized)
        )
        if slug
    ]
    name_slug = "_".join(party_slugs)
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
