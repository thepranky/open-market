"""Pydantic models for jurisdiction verification sidecars and gate reports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.jurisdiction import SourceType


class SourceVerificationTier(int, Enum):
    schema_valid = 0
    passages_grounded = 1
    numbers_confirmed = 2
    structure_complete = 3
    cross_checked = 4


class GateStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    skip = "skip"
    not_run = "not_run"


class RegressionStatus(str, Enum):
    not_run = "not_run"
    passed = "passed"
    failed = "failed"


class FreshnessStatus(str, Enum):
    fresh = "fresh"
    stale = "stale"
    drift_detected = "drift_detected"
    unknown = "unknown"


class FetchStatus(str, Enum):
    ok = "ok"
    broken = "broken"
    bot_protected = "bot_protected"
    ssl_uncertain = "ssl_uncertain"
    unsupported = "unsupported"


# Hard-fact conditions may be grounded in any of these source types.
AUTHORITATIVE_SOURCE_TYPES: frozenset[SourceType] = frozenset(
    {
        SourceType.primary_legislation,
        SourceType.official_guidance,
        SourceType.authority_announcement,
    }
)


class SourceTierBreakdown(BaseModel):
    passages_grounded: GateStatus = GateStatus.not_run
    numbers_confirmed: GateStatus = GateStatus.not_run
    structure_complete: GateStatus = GateStatus.not_run
    cross_checked: GateStatus = GateStatus.not_run


class FreshnessMetadata(BaseModel):
    checked_at: Optional[datetime] = None
    policy_window_days: int = 180
    anchors_checked: list[str] = Field(default_factory=list)


class ConditionVerification(BaseModel):
    tier: SourceVerificationTier = SourceVerificationTier.schema_valid
    passage_id: Optional[str] = None
    numeric_match: Optional[bool] = None
    source_type: Optional[SourceType] = None
    note: Optional[str] = None


class VerificationFailure(BaseModel):
    gate: str
    code: str
    message: str
    field_path: Optional[str] = None


class JurisdictionVerification(BaseModel):
    jurisdiction_id: str
    verified_at: Optional[datetime] = None
    source_verification_tier: SourceVerificationTier = SourceVerificationTier.schema_valid
    source_tier_breakdown: SourceTierBreakdown = Field(default_factory=SourceTierBreakdown)
    regression_status: RegressionStatus = RegressionStatus.not_run
    freshness_status: FreshnessStatus = FreshnessStatus.unknown
    freshness: FreshnessMetadata = Field(default_factory=FreshnessMetadata)
    failures: list[VerificationFailure] = Field(default_factory=list)
    conditions_verified: dict[str, ConditionVerification] = Field(default_factory=dict)


class ArchetypeRequirements(BaseModel):
    description: str
    min_threshold_tests: int = 1
    requires_exclusions: bool = False
    requires_gun_jumping: bool = False
    requires_voluntary_regime: bool = False
    requires_mandatory_regime: bool = False
    requires_suspensory_regime: bool = False
    requires_annual_adjustment_flag: bool = False
    requires_fdi_screening: bool = False
    requires_source_passages: bool = False


class ArchetypeConfig(BaseModel):
    version: int = 1
    assignments: dict[str, list[str]] = Field(default_factory=dict)
    archetypes: dict[str, ArchetypeRequirements] = Field(default_factory=dict)

    def archetypes_for(self, jurisdiction_id: str) -> list[tuple[str, ArchetypeRequirements]]:
        names = self.assignments.get(jurisdiction_id, [])
        return [(name, self.archetypes[name]) for name in names if name in self.archetypes]


class BaselineJurisdictionRow(BaseModel):
    jurisdiction_id: str
    condition_count: int
    authoritative_condition_count: int
    source_passage_count: int
    supported_condition_count: int
    missing_passage_support_count: int
    annual_adjustment_test_count: int
    archetypes: list[str] = Field(default_factory=list)


class BaselineCoverageReport(BaseModel):
    generated_at: datetime
    jurisdiction_count: int
    threshold_condition_count: int
    primary_legislation_condition_count: int
    authoritative_condition_count: int
    condition_with_source_url_count: int
    source_passage_count: int
    supported_condition_count: int
    authoritative_missing_passage_count: int
    jurisdictions_without_source_passages: list[str] = Field(default_factory=list)
    annual_adjustment_test_count: int
    jurisdictions: list[BaselineJurisdictionRow] = Field(default_factory=list)
