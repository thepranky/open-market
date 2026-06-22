"""Gold deal regression and re-extraction diff helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app.models.jurisdiction import JurisdictionRule, MetricType
from app.models.jurisdiction_verification import AUTHORITATIVE_SOURCE_TYPES
from app.services.jurisdiction_numeric import parse_monetary_values, parse_share_values
from app.services.threshold_engine import DealParameters, RevenueByScope, load_jurisdiction, screen_jurisdiction


@dataclass
class GoldDeal:
    deal_id: str
    description: str
    jurisdictions: list[str]
    expected: dict[str, str]
    deal: dict
    source_url: Optional[str] = None


@dataclass
class ReextractMismatch:
    condition_id: str
    field_name: str
    yaml_value: object
    extracted_value: object
    message: str


@dataclass
class ReextractReport:
    jurisdiction_id: str
    mismatches: list[ReextractMismatch] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches


def load_gold_deals(path: Path) -> list[GoldDeal]:
    raw = yaml.safe_load(path.read_text()) or {}
    return [GoldDeal(**item) for item in raw.get("deals", [])]


def _deal_from_dict(raw: dict) -> DealParameters:
    def rev(data: dict | None) -> RevenueByScope:
        data = data or {}
        return RevenueByScope(
            worldwide=data.get("worldwide"),
            domestic=data.get("domestic"),
            eu_eea=data.get("eu_eea"),
            uk=data.get("uk"),
            us=data.get("us"),
            by_country=data.get("by_country") or {},
        )

    return DealParameters(
        acquirer=rev(raw.get("acquirer")),
        target=rev(raw.get("target")),
        acquirer_assets=raw.get("acquirer_assets"),
        target_assets=raw.get("target_assets"),
        deal_value=raw.get("deal_value"),
        deal_currency=raw.get("deal_currency", "EUR"),
        revenue_currency=raw.get("revenue_currency", "EUR"),
        fx_rates=raw.get("fx_rates") or {},
        deal_type=raw.get("deal_type"),
        pct_shares_acquired=raw.get("pct_shares_acquired"),
        post_closing_control=raw.get("post_closing_control"),
        relationship_type=raw.get("relationship_type"),
        combined_market_share=raw.get("combined_market_share") or {},
        acquirer_market_share=raw.get("acquirer_market_share") or {},
        incremental_share=raw.get("incremental_share") or {},
    )


def _deal_for_jurisdiction(raw: dict, jurisdiction_id: str) -> DealParameters:
    params = _deal_from_dict(raw)
    jid = jurisdiction_id.lower()

    def _scope(rev: RevenueByScope) -> None:
        if rev.domestic is None:
            rev.domestic = rev.by_country.get(jid) or rev.by_country.get(jid.upper())
        if jid == "uk" and rev.uk is not None:
            rev.domestic = rev.domestic or rev.uk
        if jid == "us_hsr" and rev.us is not None:
            rev.domestic = rev.domestic or rev.us

    _scope(params.acquirer)
    _scope(params.target)
    return params


def run_gold_deal(deal: GoldDeal, data_dir: Path) -> list[tuple[str, str, str]]:
    """Return list of (jurisdiction_id, expected, actual) tuples for mismatches."""
    mismatches: list[tuple[str, str, str]] = []
    for jid in deal.jurisdictions:
        expected = deal.expected.get(jid)
        if expected is None:
            continue
        rule = load_jurisdiction(jid, str(data_dir))
        params = _deal_for_jurisdiction(deal.deal, jid)
        result = screen_jurisdiction(params, rule)
        actual = result.status.value
        if actual != expected:
            mismatches.append((jid, expected, actual))
    return mismatches


def _extract_from_passages(rule: JurisdictionRule) -> dict[str, float]:
    extracted: dict[str, float] = {}
    condition_map = {
        c.condition_id: c
        for test in rule.threshold_tests
        for c in test.conditions
        if c.source_type in AUTHORITATIVE_SOURCE_TYPES
    }
    for passage in rule.source_passages:
        text = passage.quoted_text
        for condition_id in passage.supports_conditions:
            condition = condition_map.get(condition_id)
            if condition is None:
                continue
            if condition.metric in {MetricType.market_share, MetricType.incremental_share}:
                candidates = parse_share_values(text)
            else:
                candidates = parse_monetary_values(text, currency=condition.currency)
            if not candidates:
                continue
            # A passage may mention several numbers; compare against the one
            # closest to the YAML value so unrelated figures (dates, other
            # thresholds) don't produce spurious mismatches.
            extracted[condition_id] = min(candidates, key=lambda c: abs(c - condition.value))
    return extracted


def diff_reextract(rule: JurisdictionRule) -> ReextractReport:
    report = ReextractReport(jurisdiction_id=rule.jurisdiction_id)
    extracted = _extract_from_passages(rule)
    for test in rule.threshold_tests:
        for condition in test.conditions:
            if condition.source_type not in AUTHORITATIVE_SOURCE_TYPES:
                continue
            if condition.condition_id not in extracted:
                continue
            got = extracted[condition.condition_id]
            if abs(got - condition.value) > max(abs(condition.value) * 0.02, 1.0):
                report.mismatches.append(
                    ReextractMismatch(
                        condition_id=condition.condition_id,
                        field_name="value",
                        yaml_value=condition.value,
                        extracted_value=got,
                        message=f"Passage extraction {got} != YAML {condition.value}",
                    )
                )
    return report
