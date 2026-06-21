"""Verify jurisdiction source_passages against authoritative source text."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.models.jurisdiction import JurisdictionRule, SourceType, ThresholdCondition
from app.models.jurisdiction_verification import (
    AUTHORITATIVE_SOURCE_TYPES,
    ConditionVerification,
    GateStatus,
    JurisdictionVerification,
    SourceVerificationTier,
    VerificationFailure,
)
from app.services.jurisdiction_numeric import value_in_text
from app.services.jurisdiction_verification_store import load_sidecar, write_sidecar
from app.services.source_fetcher import FetchStatus, SourceFetchResult, fetch_source, quote_in_text


@dataclass
class PassageFailure:
    code: str
    message: str
    field_path: Optional[str] = None


@dataclass
class PassageReport:
    jurisdiction_id: str
    failures: list[PassageFailure] = field(default_factory=list)
    conditions_verified: dict[str, ConditionVerification] = field(default_factory=dict)

    @property
    def passages_grounded(self) -> bool:
        return not any(f.code.startswith("quote_") or f.code == "fetch_failed" for f in self.failures)

    @property
    def numbers_confirmed(self) -> bool:
        return self.passages_grounded and not any(f.code == "numeric_mismatch" for f in self.failures)


def _condition_map(rule: JurisdictionRule) -> dict[str, ThresholdCondition]:
    mapping: dict[str, ThresholdCondition] = {}
    for test in rule.threshold_tests:
        for condition in test.conditions:
            mapping[condition.condition_id] = condition
    return mapping


def _fetch_with_fixtures(
    url: str,
    fixtures: dict[str, Path],
    live_fetch: Callable[[str], SourceFetchResult],
) -> SourceFetchResult:
    for key, path in fixtures.items():
        if key in url:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".html":
                from app.services.source_fetcher import html_to_text

                text = html_to_text(text)
            else:
                from app.services.source_fetcher import normalize_text

                text = normalize_text(text)
            return SourceFetchResult(
                url=url,
                final_url=url,
                content_type="text/fixture",
                fetch_status=FetchStatus.ok,
                text=text,
            )
    return live_fetch(url)


def verify_passages(
    rule: JurisdictionRule,
    *,
    fetch_fn: Callable[[str], SourceFetchResult],
) -> PassageReport:
    report = PassageReport(jurisdiction_id=rule.jurisdiction_id)
    conditions = _condition_map(rule)
    fetch_cache: dict[str, SourceFetchResult] = {}

    for passage in rule.source_passages:
        prefix = f"source_passages.{passage.passage_id}"
        url = passage.document_url
        if url not in fetch_cache:
            fetch_cache[url] = fetch_fn(url)
        fetched = fetch_cache[url]

        if fetched.fetch_status != FetchStatus.ok:
            report.failures.append(
                PassageFailure(
                    code="fetch_failed",
                    message=f"Could not fetch {url}: {fetched.fetch_status.value} {fetched.error or ''}".strip(),
                    field_path=f"{prefix}.document_url",
                )
            )
            continue

        if not quote_in_text(passage.quoted_text, fetched.text):
            report.failures.append(
                PassageFailure(
                    code="quote_not_found",
                    message=f"Quoted text not found at {url}",
                    field_path=f"{prefix}.quoted_text",
                )
            )
            continue

        for condition_id in passage.supports_conditions:
            condition = conditions.get(condition_id)
            if condition is None:
                report.failures.append(
                    PassageFailure(
                        code="unknown_condition",
                        message=f"Passage supports unknown condition '{condition_id}'",
                        field_path=f"{prefix}.supports_conditions",
                    )
                )
                continue

            numeric_match: Optional[bool] = None
            if condition.source_type in AUTHORITATIVE_SOURCE_TYPES:
                numeric_match = value_in_text(
                    passage.quoted_text,
                    condition.value,
                    metric=condition.metric,
                    currency=condition.currency,
                ) or value_in_text(
                    fetched.text,
                    condition.value,
                    metric=condition.metric,
                    currency=condition.currency,
                )
                if numeric_match is False:
                    report.failures.append(
                        PassageFailure(
                            code="numeric_mismatch",
                            message=(
                                f"Condition '{condition_id}' value {condition.value} "
                                f"not found in passage/source text"
                            ),
                            field_path=f"conditions.{condition_id}.value",
                        )
                    )

            tier = SourceVerificationTier.numbers_confirmed if numeric_match else SourceVerificationTier.passages_grounded
            if numeric_match is False:
                tier = SourceVerificationTier.passages_grounded
            elif numeric_match is True:
                tier = SourceVerificationTier.numbers_confirmed
            elif numeric_match is None and condition.source_type in AUTHORITATIVE_SOURCE_TYPES:
                tier = SourceVerificationTier.passages_grounded

            report.conditions_verified[condition_id] = ConditionVerification(
                tier=tier,
                passage_id=passage.passage_id,
                numeric_match=numeric_match,
                source_type=condition.source_type,
            )

    for test in rule.threshold_tests:
        for condition in test.conditions:
            if condition.source_type not in AUTHORITATIVE_SOURCE_TYPES:
                continue
            if condition.condition_id in report.conditions_verified:
                continue
            report.failures.append(
                PassageFailure(
                    code="missing_passage_support",
                    message=f"Authoritative condition '{condition.condition_id}' has no supporting source_passage",
                    field_path=f"conditions.{condition.condition_id}",
                )
            )

    return report


def build_sidecar_update(
    report: PassageReport,
    existing: Optional[JurisdictionVerification] = None,
) -> JurisdictionVerification:
    sidecar = existing or JurisdictionVerification(jurisdiction_id=report.jurisdiction_id)
    sidecar.source_tier_breakdown.passages_grounded = (
        GateStatus.pass_ if report.passages_grounded else GateStatus.fail
    )
    sidecar.source_tier_breakdown.numbers_confirmed = (
        GateStatus.pass_ if report.numbers_confirmed else GateStatus.fail
    )
    sidecar.failures = [f for f in sidecar.failures if f.gate != "verify_jurisdiction_passages"]
    sidecar.failures.extend(
        VerificationFailure(
            gate="verify_jurisdiction_passages",
            code=f.code,
            message=f.message,
            field_path=f.field_path,
        )
        for f in report.failures
    )
    sidecar.conditions_verified.update(report.conditions_verified)

    if report.numbers_confirmed:
        sidecar.source_verification_tier = SourceVerificationTier.numbers_confirmed
    elif report.passages_grounded:
        sidecar.source_verification_tier = SourceVerificationTier.passages_grounded
    else:
        sidecar.source_verification_tier = SourceVerificationTier.schema_valid

    sidecar.verified_at = datetime.now(timezone.utc)
    return sidecar


def verify_and_optional_write(
    rule: JurisdictionRule,
    data_dir: Path,
    *,
    fetch_fn: Callable[[str], SourceFetchResult],
    write_sidecar_file: bool = False,
) -> PassageReport:
    report = verify_passages(rule, fetch_fn=fetch_fn)
    if write_sidecar_file:
        existing = load_sidecar(data_dir, rule.jurisdiction_id)
        sidecar = build_sidecar_update(report, existing)
        write_sidecar(data_dir, sidecar)
    return report


def default_fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "jurisdiction_sources"


def build_offline_fetch(fixtures_dir: Path) -> Callable[[str], SourceFetchResult]:
    fixtures = {path.stem.replace("_", "."): path for path in fixtures_dir.glob("*") if path.is_file()}
    # Also map by filename substring keys used in tests
    named: dict[str, Path] = {}
    for path in fixtures_dir.glob("*"):
        if path.is_file():
            named[path.name] = path
            if "uk_section" in path.name:
                named["legislation.gov.uk/ukpga/2002/40/section/23"] = path
            if "eu_article" in path.name:
                named["eur-lex.europa.eu"] = path
            if "us_hsr" in path.name:
                named["ftc.gov"] = path

    def fetch(url: str) -> SourceFetchResult:
        return _fetch_with_fixtures(url, named, lambda u: fetch_source(u))

    return fetch
