"""Tests for the jurisdiction bundle / verification metadata service."""

from __future__ import annotations

from datetime import date, datetime, timezone

import yaml

from app.models.jurisdiction import (
    Authority,
    FilingDeadlines,
    JurisdictionRule,
    LegalBasis,
    MetricType,
    Regime,
    ReviewPeriod,
    ReviewPeriods,
    SourceType,
    ThresholdCondition,
    ThresholdTest,
)
from app.models.jurisdiction_verification import (
    FreshnessStatus,
    JurisdictionVerification,
    RegressionStatus,
    SourceVerificationTier,
)
from app.services.jurisdiction_data_service import load_bundle, verification_metadata
from app.services.jurisdiction_verification_store import clear_sidecar_cache, write_sidecar
from app.services.threshold_engine import _jurisdiction_cache


def _write_rule(data_dir) -> None:
    rule = JurisdictionRule(
        jurisdiction_id="zz",
        jurisdiction_name="Testland",
        last_verified=date(2026, 1, 1),
        authority=Authority(name="A", abbreviation="A", url="https://x", filing_url="https://x/f"),
        regime=Regime(mandatory=True, suspensory=True, voluntary=False),
        legal_basis=[LegalBasis(citation="L", url="https://x")],
        filing=FilingDeadlines(pre_closing_required=True),
        review_periods=ReviewPeriods(phase_1=ReviewPeriod(days=30, legal_basis="s.1")),
        threshold_tests=[
            ThresholdTest(
                test_id="t",
                description="d",
                legal_basis="L",
                source_url="https://x",
                annual_adjustment=False,
                conditions=[
                    ThresholdCondition(
                        condition_id="c",
                        metric=MetricType.revenue,
                        scope="worldwide",
                        party="combined",
                        operator=">",
                        value=1_000_000,
                        currency="EUR",
                        source="L",
                        source_type=SourceType.primary_legislation,
                    )
                ],
            )
        ],
    )
    (data_dir / "zz.yaml").write_text(yaml.safe_dump(rule.model_dump(mode="json", exclude_none=True)))


def _reset_caches():
    clear_sidecar_cache()
    _jurisdiction_cache.pop("zz", None)


def test_bundle_defaults_when_no_sidecar(tmp_path):
    _reset_caches()
    _write_rule(tmp_path)
    bundle = load_bundle(tmp_path, "zz")
    assert bundle.verification is None
    meta = verification_metadata(bundle)
    assert meta["source_verification_tier"] == int(SourceVerificationTier.schema_valid.value)
    assert meta["regression_status"] == RegressionStatus.not_run.value
    assert meta["freshness_status"] == FreshnessStatus.unknown.value
    assert meta["verified_at"] is None


def test_bundle_reads_sidecar_metadata(tmp_path):
    _reset_caches()
    _write_rule(tmp_path)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    write_sidecar(
        tmp_path,
        JurisdictionVerification(
            jurisdiction_id="zz",
            source_verification_tier=SourceVerificationTier.numbers_confirmed,
            regression_status=RegressionStatus.passed,
            freshness_status=FreshnessStatus.fresh,
            verified_at=now,
        ),
    )
    bundle = load_bundle(tmp_path, "zz")
    meta = verification_metadata(bundle)
    assert meta["source_verification_tier"] == int(SourceVerificationTier.numbers_confirmed.value)
    assert meta["regression_status"] == RegressionStatus.passed.value
    assert meta["freshness_status"] == FreshnessStatus.fresh.value
    assert meta["verified_at"] == now.isoformat()
