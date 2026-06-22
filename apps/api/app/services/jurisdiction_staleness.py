"""Freshness / staleness checks for annual-adjustment jurisdictions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from app.models.jurisdiction import JurisdictionRule
from app.models.jurisdiction_verification import FreshnessStatus, JurisdictionVerification
from app.services.jurisdiction_verification_store import load_sidecar, write_sidecar
from app.services.threshold_engine import load_all_jurisdictions


@dataclass
class StalenessAnchor:
    policy_source: str
    effective_date: date
    policy_window_days: int = 180
    thresholds: dict[str, float] = field(default_factory=dict)


@dataclass
class StalenessReport:
    jurisdiction_id: str
    freshness_status: FreshnessStatus
    drift: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_anchors(path: Path) -> dict[str, StalenessAnchor]:
    raw = yaml.safe_load(path.read_text()) or {}
    result: dict[str, StalenessAnchor] = {}
    for jid, payload in (raw.get("anchors") or {}).items():
        result[jid] = StalenessAnchor(
            policy_source=payload["policy_source"],
            effective_date=date.fromisoformat(str(payload["effective_date"])),
            policy_window_days=int(payload.get("policy_window_days", 180)),
            thresholds={k: float(v) for k, v in (payload.get("thresholds") or {}).items()},
        )
    return result


def _condition_values(rule: JurisdictionRule) -> dict[str, float]:
    values: dict[str, float] = {}
    for test in rule.threshold_tests:
        for condition in test.conditions:
            values[condition.condition_id] = condition.value
    return values


def evaluate_staleness(rule: JurisdictionRule, anchor: Optional[StalenessAnchor]) -> StalenessReport:
    if anchor is None:
        return StalenessReport(rule.jurisdiction_id, FreshnessStatus.unknown, notes=["no_anchor_configured"])

    drift: list[str] = []
    yaml_values = _condition_values(rule)
    for condition_id, expected in anchor.thresholds.items():
        actual = yaml_values.get(condition_id)
        if actual is None:
            drift.append(f"missing_condition:{condition_id}")
            continue
        if abs(actual - expected) > max(abs(expected) * 0.001, 1.0):
            drift.append(f"{condition_id}: yaml={actual} anchor={expected}")

    age_days = (date.today() - rule.last_verified).days
    if drift:
        status = FreshnessStatus.drift_detected
    elif age_days > anchor.policy_window_days:
        status = FreshnessStatus.stale
    else:
        status = FreshnessStatus.fresh

    return StalenessReport(rule.jurisdiction_id, status, drift=drift)


def update_sidecar_freshness(
    data_dir: Path,
    report: StalenessReport,
    anchor: Optional[StalenessAnchor],
) -> JurisdictionVerification:
    existing = load_sidecar(data_dir, report.jurisdiction_id)
    sidecar = existing or JurisdictionVerification(jurisdiction_id=report.jurisdiction_id)
    now = datetime.now(timezone.utc)
    sidecar.freshness_status = report.freshness_status
    sidecar.freshness.checked_at = now
    if anchor:
        sidecar.freshness.policy_window_days = anchor.policy_window_days
        sidecar.freshness.anchors_checked = [anchor.policy_source]
    # Only advance verified_at when the check actually confirmed freshness;
    # drift/stale/unknown should not look freshly verified to downstream gates.
    if report.freshness_status == FreshnessStatus.fresh:
        sidecar.verified_at = now
    write_sidecar(data_dir, sidecar)
    return sidecar


def evaluate_all(data_dir: Path, anchors_path: Path) -> list[StalenessReport]:
    anchors = load_anchors(anchors_path)
    rules = load_all_jurisdictions(str(data_dir))
    reports: list[StalenessReport] = []
    for rule in rules:
        if not any(t.annual_adjustment for t in rule.threshold_tests):
            continue
        reports.append(evaluate_staleness(rule, anchors.get(rule.jurisdiction_id)))
    return reports
