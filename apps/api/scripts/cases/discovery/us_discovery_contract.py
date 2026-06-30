"""US case-index discovery contract shared by DOJ and FTC scrapers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

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


_DOJ_CAPTION_PREFIXES = (
    "us-and-plaintiff-states-v-",
    "us-et-al-v-",
    "us-v-",
)
_FTC_MATTER_RE = re.compile(r"^(\d{3})-?(\d{4})-(.+)$")
_SLUG_MAX_LEN = 55


def _url_path_slug(source_url: str) -> str:
    path = urlparse(source_url).path.rstrip("/")
    if not path:
        raise ValueError("source_url must include a path segment")
    return path.rsplit("/", 1)[-1]


def _normalize_slug(slug: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    if len(normalized) > _SLUG_MAX_LEN:
        normalized = normalized[:_SLUG_MAX_LEN].rstrip("_")
    return normalized


def _doj_slug_from_url(source_url: str) -> str:
    slug = _url_path_slug(source_url)
    for prefix in _DOJ_CAPTION_PREFIXES:
        if slug.startswith(prefix):
            slug = slug[len(prefix) :]
            break
    if slug.endswith("-et-al"):
        slug = slug[: -len("-et-al")]
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("could not derive a DOJ case slug from source_url")
    return normalized


def _ftc_slug_from_url(source_url: str) -> str:
    slug = _url_path_slug(source_url)
    match = _FTC_MATTER_RE.match(slug)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("could not derive an FTC case slug from source_url")
    return normalized


def generate_us_case_id(authority: Literal["DOJ", "FTC"], source_url: str, year: str) -> str:
    """Generate a stable US case-index id from an authority listing source URL."""
    authority_slug = authority.lower()
    if authority == "DOJ":
        name_slug = _doj_slug_from_url(source_url)
    else:
        name_slug = _ftc_slug_from_url(source_url)
    return f"us_{authority_slug}_{name_slug}_{year}"


def to_case_index_seed(record: UsScrapedCase) -> CaseIndexSeed:
    """Convert one US scraped listing record into the shared case-index seed."""
    if record.decision_date is None:
        raise ValueError("decision_date is required to build a case-index entry")
    year = record.decision_date[:4]
    return CaseIndexSeed(
        case_id=generate_us_case_id(record.authority, record.source_url, year),
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
