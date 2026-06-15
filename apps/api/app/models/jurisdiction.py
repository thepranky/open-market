"""Pydantic models for the jurisdiction threshold schema."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


class MetricType(str, Enum):
    revenue = "revenue"
    revenue_or_assets = "revenue_or_assets"
    deal_value = "deal_value"
    assets = "assets"
    market_share = "market_share"
    incremental_share = "incremental_share"


class ScopeType(str, Enum):
    worldwide = "worldwide"
    domestic = "domestic"
    eu_eea = "eu_eea"
    eu_member_state = "eu_member_state"
    single_member_state = "single_member_state"
    uk = "uk"
    us = "us"
    eea_member_state = "eea_member_state"


class PartyType(str, Enum):
    combined = "combined"
    acquirer_group = "acquirer_group"
    target_group = "target_group"
    either_party = "either_party"
    each_party = "each_party"
    each_of_at_least_two = "each_of_at_least_two"


class CountQualifier(BaseModel):
    type: Literal["count_of_countries"]
    operator: Literal[">=", ">"]
    count: int
    country_set: str
    cross_reference: Optional[str] = None


class SourceType(str, Enum):
    primary_legislation = "primary_legislation"   # statute, regulation, official journal
    official_guidance   = "official_guidance"     # authority-published guidance (not legislation)
    authority_announcement = "authority_announcement"  # official press release / annual threshold notice
    practitioner        = "practitioner"          # law firm alert, secondary database — not primary


class ThresholdCondition(BaseModel):
    condition_id: str
    metric: MetricType
    scope: ScopeType
    party: PartyType
    operator: Literal[">", ">=", "<", "<="]
    value: float
    currency: Optional[str] = None
    source: str                                   # human-readable citation (article/section)
    source_type: SourceType = SourceType.primary_legislation
    source_url: Optional[str] = None             # direct link to source document
    verified_via: list[str] = []                 # URLs of secondary sources used to confirm
    qualifier: Optional[CountQualifier] = None
    note: Optional[str] = None


class Exclusion(BaseModel):
    exclusion_id: str
    description: str
    source: str
    effect: Literal["excludes_jurisdiction", "reduces_scope"]


class Exception_(BaseModel):
    exception_id: str
    description: str
    source: str
    effect: Optional[str] = None


class ThresholdTest(BaseModel):
    test_id: str
    description: str
    legal_basis: str
    source_url: str
    note: Optional[str] = None
    annual_adjustment: bool
    effective_date: Optional[date] = None
    status: Optional[str] = None
    conditions: list[ThresholdCondition]
    exclusions: list[Exclusion] = []
    exceptions: list[Exception_] = []


class Authority(BaseModel):
    name: str
    abbreviation: str
    url: str
    filing_url: str


class Regime(BaseModel):
    mandatory: bool
    suspensory: bool
    voluntary: bool


class LegalBasis(BaseModel):
    citation: str
    url: str
    note: Optional[str] = None
    source_type: SourceType = SourceType.primary_legislation


class FilingDeadlines(BaseModel):
    deadline_from_signing_days: Optional[int] = None
    deadline_from_closing_days: Optional[int] = None
    pre_closing_required: bool
    note: Optional[str] = None


class ReviewPeriod(BaseModel):
    days: int
    day_type: Optional[Literal["calendar", "working"]] = None
    day_unit: Optional[str] = None
    extendable_to_days: Optional[int] = None
    day_unit_extended: Optional[str] = None
    legal_basis: str
    note: Optional[str] = None


class ReviewPeriods(BaseModel):
    phase_1: ReviewPeriod
    phase_2: ReviewPeriod


# ── Source passages (anti-hallucination: verbatim statutory text) ─────────────

class SourcePassage(BaseModel):
    """Verbatim quote from the statutory or regulatory source that anchors a condition."""
    passage_id: str
    document_title: str
    article_reference: str            # e.g. "Article 1(2)"
    document_url: str
    quoted_text: str                  # verbatim text in English (or official translation)
    source_type: SourceType = SourceType.primary_legislation
    supports_conditions: list[str] = []   # condition_ids backed by this passage


# ── Scope / trigger event section ─────────────────────────────────────────────

class JurisdictionScope(BaseModel):
    """What types of transactions trigger the regime and how 'concentration' is defined."""
    concentration_definition: Optional[str] = None
    concentration_definition_source: Optional[str] = None
    concentration_definition_url: Optional[str] = None   # link to the defining statute article
    trigger_events: list[str] = []           # merger, share_acquisition, asset_acquisition, jv, minority_stake
    control_threshold: Optional[str] = None  # exclusive_control, joint_control, material_influence, decisive_influence
    intra_group_exempt: Optional[bool] = None
    foreign_to_foreign_rule: Optional[str] = None
    substantive_test: Optional[str] = None         # "dominance", "siec", "slc", "dominance_and_siec"
    substantive_test_note: Optional[str] = None
    substantive_test_url: Optional[str] = None     # link to the article setting the substantive test
    note: Optional[str] = None


# ── Gun-jumping / standstill obligation ───────────────────────────────────────

class GunJumping(BaseModel):
    automatic_void: Optional[bool] = None
    voidable: Optional[bool] = None
    max_fine_pct_turnover: Optional[float] = None   # e.g. 10 for 10% of turnover
    max_fine_fixed: Optional[float] = None
    max_fine_currency: Optional[str] = None
    per_day_fine: Optional[float] = None
    criminal_sanctions: Optional[bool] = None
    legal_basis: Optional[str] = None
    legal_basis_url: Optional[str] = None           # direct link to the standstill/penalty provision
    note: Optional[str] = None


# ── FDI / national security screening ────────────────────────────────────────

class FdiScreening(BaseModel):
    applicable: bool
    regime_name: Optional[str] = None
    authority: Optional[str] = None
    url: Optional[str] = None           # authority/ministry website
    legislation_url: Optional[str] = None  # direct link to the FDI screening law
    sectors_covered: list[str] = []
    note: Optional[str] = None


# ── Filing fees ───────────────────────────────────────────────────────────────

class Fees(BaseModel):
    structure: Optional[str] = None   # "none" or multi-line fee schedule
    source: Optional[str] = None
    source_type: SourceType = SourceType.primary_legislation
    source_url: Optional[str] = None
    annual_adjustment: bool = False
    note: Optional[str] = None


class JurisdictionRule(BaseModel):
    jurisdiction_id: str
    jurisdiction_name: str
    last_verified: date
    authority: Authority
    regime: Regime
    legal_basis: list[LegalBasis]
    filing: FilingDeadlines
    review_periods: ReviewPeriods
    threshold_tests: list[ThresholdTest]
    notes: list[str] = []
    # Optional enrichment sections (added progressively)
    scope: Optional[JurisdictionScope] = None
    gun_jumping: Optional[GunJumping] = None
    fdi_screening: Optional[FdiScreening] = None
    fees: Optional[Fees] = None
    source_passages: list[SourcePassage] = []
