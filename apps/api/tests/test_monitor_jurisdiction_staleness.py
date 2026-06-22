"""Tests for jurisdiction staleness monitor."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from app.models.jurisdiction import (
    Authority,
    FilingDeadlines,
    JurisdictionRule,
    LegalBasis,
    Regime,
    ReviewPeriod,
    ReviewPeriods,
    SourceType,
    ThresholdCondition,
    ThresholdTest,
)
from app.models.jurisdiction import MetricType
from app.models.jurisdiction_verification import FreshnessStatus
from app.services.jurisdiction_staleness import (
    StalenessAnchor,
    evaluate_staleness,
    load_anchors,
    update_sidecar_freshness,
)

ANCHORS = Path(__file__).resolve().parents[3] / "data" / "jurisdictions" / "_staleness_anchors.yaml"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "monitor_jurisdiction_staleness.py"


def _hsr_rule(**overrides) -> JurisdictionRule:
    base = JurisdictionRule(
        jurisdiction_id="us_hsr",
        jurisdiction_name="US HSR",
        last_verified=date.today(),
        authority=Authority(name="FTC", abbreviation="FTC", url="https://ftc.gov", filing_url="https://ftc.gov"),
        regime=Regime(mandatory=True, suspensory=True, voluntary=False),
        legal_basis=[LegalBasis(citation="HSR", url="https://ftc.gov")],
        filing=FilingDeadlines(pre_closing_required=True),
        review_periods=ReviewPeriods(phase_1=ReviewPeriod(days=30, legal_basis="s.18a")),
        threshold_tests=[
            ThresholdTest(
                test_id="us_hsr_standard",
                description="standard",
                legal_basis="HSR",
                source_url="https://ftc.gov",
                annual_adjustment=True,
                effective_date=date(2026, 2, 17),
                conditions=[
                    ThresholdCondition(
                        condition_id=condition_id,
                        metric=MetricType.deal_value,
                        scope="worldwide",
                        party="combined",
                        operator=">",
                        value=value,
                        currency="USD",
                        source="HSR",
                        source_type=SourceType.authority_announcement,
                    )
                    for condition_id, value in (
                        ("size_of_transaction", 133_900_000),
                        ("size_of_person_larger", 267_800_000),
                        ("size_of_person_smaller", 26_800_000),
                        ("large_transaction_value", 535_500_000),
                    )
                ],
            )
        ],
    )
    return base.model_copy(update=overrides)


def test_load_anchors():
    anchors = load_anchors(ANCHORS)
    assert "us_hsr" in anchors
    assert anchors["us_hsr"].thresholds["size_of_transaction"] == 133_900_000


def test_us_hsr_fresh_when_values_match():
    anchor = load_anchors(ANCHORS)["us_hsr"]
    report = evaluate_staleness(_hsr_rule(), anchor)
    assert report.freshness_status == FreshnessStatus.fresh


def test_us_hsr_drift_when_value_differs():
    anchor = load_anchors(ANCHORS)["us_hsr"]
    rule = _hsr_rule()
    rule.threshold_tests[0].conditions[0].value = 999
    report = evaluate_staleness(rule, anchor)
    assert report.freshness_status == FreshnessStatus.drift_detected


def test_unknown_when_no_anchor():
    report = evaluate_staleness(_hsr_rule(), None)
    assert report.freshness_status == FreshnessStatus.unknown
    assert "no_anchor_configured" in report.notes


def test_stale_when_verification_is_old():
    anchor = load_anchors(ANCHORS)["us_hsr"]
    old = date.today() - timedelta(days=anchor.policy_window_days + 1)
    report = evaluate_staleness(_hsr_rule(last_verified=old), anchor)
    assert report.freshness_status == FreshnessStatus.stale


def test_missing_condition_flagged_as_drift():
    anchor = load_anchors(ANCHORS)["us_hsr"]
    rule = _hsr_rule()
    rule.threshold_tests[0].conditions[0].condition_id = "renamed_condition"
    report = evaluate_staleness(rule, anchor)
    assert report.freshness_status == FreshnessStatus.drift_detected
    assert any(d.startswith("missing_condition:size_of_transaction") for d in report.drift)


def test_verified_at_only_advances_when_fresh(tmp_path):
    from app.services.jurisdiction_staleness import StalenessReport
    from app.services.jurisdiction_verification_store import load_sidecar

    anchor = load_anchors(ANCHORS)["us_hsr"]
    report = StalenessReport("us_hsr", FreshnessStatus.drift_detected, drift=["x"])
    update_sidecar_freshness(tmp_path, report, anchor)
    sidecar = load_sidecar(tmp_path, "us_hsr")
    assert sidecar.freshness_status == FreshnessStatus.drift_detected
    assert sidecar.verified_at is None
    assert sidecar.freshness.checked_at is not None


def test_cli_runs_without_error():
    # Regression: the CLI previously raised NameError on FreshnessStatus.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    assert '"checked"' in result.stdout
