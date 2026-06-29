"""Verify jurisdiction source_passages against authoritative source text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.screening.models.jurisdiction import JurisdictionRule, ThresholdCondition
from app.screening.models.jurisdiction_verification import (
    AUTHORITATIVE_SOURCE_TYPES,
    ConditionVerification,
    GateStatus,
    JurisdictionVerification,
    SourceVerificationTier,
    VerificationFailure,
)
from app.screening.services.jurisdiction_numeric import value_in_text
from app.screening.services.jurisdiction_verification_store import load_sidecar, write_sidecar
from app.screening.services.source_fetcher import FetchStatus, SourceFetchResult, fetch_source, quote_in_text


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
        # Honest grounding requires that we actually verified at least one
        # authoritative condition against fetched source text — a jurisdiction
        # with no passages is "unverified", not "grounded". It also fails if any
        # authoritative condition is left unsupported (missing_passage_support).
        if not self.conditions_verified:
            return False
        return not any(
            f.code.startswith("quote_") or f.code in ("fetch_failed", "missing_passage_support")
            for f in self.failures
        )

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
                from app.screening.services.source_fetcher import html_to_text

                text = html_to_text(text)
            else:
                from app.screening.services.source_fetcher import normalize_text

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
    # Conditions whose parent test is annually adjusted: their current value lives
    # in the annual notice, not the statute, so numeric grounding against the
    # cited primary source is expected to miss — the staleness monitor tracks them.
    annual_adjusted = {
        condition.condition_id
        for test in rule.threshold_tests
        if test.annual_adjustment
        for condition in test.conditions
    }
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

            # Skip numeric grounding for sentinel thresholds (value 0 means
            # "any increment") and annually adjusted values, which legitimately
            # do not appear verbatim in the cited statute.
            skip_numeric = condition.value == 0 or condition_id in annual_adjusted

            numeric_match: Optional[bool] = None
            if condition.source_type in AUTHORITATIVE_SOURCE_TYPES and not skip_numeric:
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

            # Only a confirmed numeric match reaches the top tier; an unverified
            # (None) or failed (False) match stays at passages_grounded.
            tier = (
                SourceVerificationTier.numbers_confirmed
                if numeric_match is True
                else SourceVerificationTier.passages_grounded
            )

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


# A fixture must declare where its text came from, so AI-paraphrased "sources"
# (text written by an agent with no official origin) cannot ground a passage.
# Provenance = an explicit "Source"/"Sources" marker AND an http(s) URL within the
# header region. This is a static guardrail; it does not by itself prove the text
# is verbatim — that is the job of periodic live re-grounding against the URL.
_PROVENANCE_HEADER_CHARS = 1200
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SOURCE_MARKER_RE = re.compile(r"\bsource[s]?\b", re.IGNORECASE)
_FIXTURE_SUFFIXES = {".txt", ".html", ".htm"}


def fixture_provenance_issues(fixtures_dir: Path) -> list[str]:
    """Return the names of fixture files that lack a provenance header.

    A compliant fixture's first ~1200 characters contain both a "Source"/"Sources"
    marker and an http(s) URL pointing at the official document it was captured from.
    """
    issues: list[str] = []
    for path in sorted(fixtures_dir.glob("*")):
        if not path.is_file() or path.suffix.lower() not in _FIXTURE_SUFFIXES:
            continue
        head = path.read_text(encoding="utf-8")[:_PROVENANCE_HEADER_CHARS]
        if not (_URL_RE.search(head) and _SOURCE_MARKER_RE.search(head)):
            issues.append(path.name)
    return issues


def build_offline_fetch(fixtures_dir: Path) -> Callable[[str], SourceFetchResult]:
    # Map fixtures by filename and by the URL substrings used in tests.
    named: dict[str, Path] = {}
    for path in fixtures_dir.glob("*"):
        if path.is_file():
            named[path.name] = path
            if "uk_section" in path.name:
                named["legislation.gov.uk/ukpga/2002/40/section/23"] = path
            if "uk_dmcc" in path.name:
                named["legislation.gov.uk/ukpga/2024/13"] = path
            if "eu_merger" in path.name or "eu_article" in path.name:
                named["eur-lex.europa.eu"] = path
            if path.name == "us_hsr_18a.txt":
                named["uscode.house.gov"] = path
            elif path.name == "cz_s13.txt":
                named["zakonyprolidi.cz"] = path
            elif path.name == "dk_s12b.txt":
                named["en.kfst.dk"] = path
            elif path.name == "gr_art6.txt":
                named["epant.gr"] = path
            elif path.name == "hu_s24.txt":
                named["gvh.hu"] = path
            elif path.name == "ro_art14.txt":
                named["consiliulconcurentei.ro"] = path
                named["legeaz.net"] = path
            elif path.name == "cl_art48.txt":
                named["fne.gob.cl"] = path
            elif path.name == "id_pp57_p5.txt":
                named["kppu.go.id"] = path
                named["peraturan.go.id"] = path
            elif path.name == "pe_ley31112_art6.txt":
                named["per203283"] = path
                named["indecopi.gob.pe"] = path
            elif path.name == "ph_s17.txt":
                named["phcc.gov.ph"] = path
            elif path.name == "pt_art37.txt":
                named["concorrencia.pt"] = path
                named["dre.pt"] = path

    def fetch(url: str) -> SourceFetchResult:
        return _fetch_with_fixtures(
            url,
            named,
            lambda u: SourceFetchResult(
                url=u,
                fetch_status=FetchStatus.unsupported,
                error="offline fixture not found",
            ),
        )

    return fetch
