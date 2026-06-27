"""Tests for jurisdiction verification models and baseline metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
ARCHETYPES_PATH = DATA_DIR / "_archetypes.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.screening.models.jurisdiction import SourceType
from app.screening.models.jurisdiction_verification import (
    ArchetypeConfig,
    FreshnessStatus,
    GateStatus,
    JurisdictionVerification,
    RegressionStatus,
    SourceVerificationTier,
)
from app.screening.services.jurisdiction_baseline import compute_baseline_report


def test_sidecar_example_loads():
    sidecar = JurisdictionVerification.model_validate(
        {
            "jurisdiction_id": "uk",
            "verified_at": "2026-06-20T14:00:00Z",
            "source_verification_tier": 3,
            "source_tier_breakdown": {
                "passages_grounded": "pass",
                "numbers_confirmed": "pass",
                "structure_complete": "pass",
                "cross_checked": "not_run",
            },
            "regression_status": "not_run",
            "freshness_status": "fresh",
            "freshness": {
                "checked_at": "2026-06-20T14:00:00Z",
                "policy_window_days": 180,
                "anchors_checked": [],
            },
            "conditions_verified": {
                "uk_turnover_target": {
                    "tier": 2,
                    "passage_id": "uk_ea2002_s23_1",
                    "numeric_match": True,
                    "source_type": "primary_legislation",
                }
            },
        }
    )
    assert sidecar.jurisdiction_id == "uk"
    assert sidecar.source_verification_tier == SourceVerificationTier.structure_complete
    assert sidecar.source_tier_breakdown.passages_grounded == GateStatus.pass_
    assert sidecar.regression_status == RegressionStatus.not_run
    assert sidecar.freshness_status == FreshnessStatus.fresh


def test_archetypes_yaml_validates():
    raw = yaml.safe_load(ARCHETYPES_PATH.read_text())
    config = ArchetypeConfig.model_validate(raw)
    assert config.version == 1
    assert "eu" in config.assignments
    assert "eu_turnover" in config.archetypes
    eu_archetypes = config.archetypes_for("eu")
    assert any(name == "eu_turnover" for name, _ in eu_archetypes)


def test_baseline_report_counts():
    report = compute_baseline_report(DATA_DIR, ARCHETYPES_PATH)
    assert report.jurisdiction_count == 47
    assert report.threshold_condition_count == 172
    assert report.primary_legislation_condition_count == 124
    assert report.authoritative_condition_count == 168
    assert report.condition_with_source_url_count == 17
    assert report.source_passage_count == 75
    assert report.supported_condition_count == 138
    assert report.authoritative_missing_passage_count == 29
    assert report.annual_adjustment_test_count == 15
    assert report.jurisdictions_without_source_passages == []


def test_baseline_report_serializes():
    report = compute_baseline_report(DATA_DIR, ARCHETYPES_PATH)
    payload = report.model_dump(mode="json")
    assert payload["jurisdiction_count"] == 47
    assert isinstance(payload["generated_at"], str)


def test_authoritative_source_types_exclude_practitioner():
    from app.screening.models.jurisdiction_verification import AUTHORITATIVE_SOURCE_TYPES

    assert SourceType.practitioner not in AUTHORITATIVE_SOURCE_TYPES
    assert SourceType.primary_legislation in AUTHORITATIVE_SOURCE_TYPES
