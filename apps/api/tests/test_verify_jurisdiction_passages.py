"""Tests for jurisdiction passage verification gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from app.models.jurisdiction import (
    Authority,
    FilingDeadlines,
    GunJumping,
    JurisdictionRule,
    LegalBasis,
    Regime,
    ReviewPeriod,
    ReviewPeriods,
    SourcePassage,
    SourceType,
    ThresholdCondition,
    ThresholdTest,
)
from app.services.jurisdiction_numeric import value_in_text
from app.services.jurisdiction_passages import (
    build_offline_fetch,
    fixture_provenance_issues,
    verify_passages,
)
from app.models.jurisdiction import MetricType

FIXTURES = Path(__file__).parent / "fixtures" / "jurisdiction_sources"

# Fixtures still holding AI-paraphrased text pending replacement with verbatim
# official source text. This set must only ever shrink. Empty = goal reached.
PENDING_REAL_SOURCE: set[str] = set()


def test_fixtures_declare_provenance():
    """Every fixture must declare a Source + URL; no AI-paraphrase-only fixtures.

    The only permitted non-compliant fixtures are the documented PENDING_REAL_SOURCE
    set being migrated to verbatim official text. New violations fail the build.
    """
    issues = set(fixture_provenance_issues(FIXTURES))
    unexpected = issues - PENDING_REAL_SOURCE
    assert not unexpected, f"fixtures lack a Source+URL provenance header: {sorted(unexpected)}"
    resolved = PENDING_REAL_SOURCE - issues
    assert not resolved, (
        f"these fixtures now comply — remove them from PENDING_REAL_SOURCE: {sorted(resolved)}"
    )


def _uk_rule() -> JurisdictionRule:
    return JurisdictionRule(
        jurisdiction_id="uk",
        jurisdiction_name="United Kingdom",
        last_verified=date(2026, 1, 1),
        authority=Authority(name="CMA", abbreviation="CMA", url="https://gov.uk", filing_url="https://gov.uk/f"),
        regime=Regime(mandatory=False, suspensory=False, voluntary=True),
        legal_basis=[LegalBasis(citation="EA 2002", url="https://gov.uk")],
        filing=FilingDeadlines(pre_closing_required=False),
        review_periods=ReviewPeriods(phase_1=ReviewPeriod(days=40, legal_basis="s.34")),
        threshold_tests=[
            ThresholdTest(
                test_id="uk_turnover",
                description="UK turnover",
                legal_basis="s.23",
                source_url="https://www.legislation.gov.uk/ukpga/2002/40/section/23",
                annual_adjustment=False,
                conditions=[
                    ThresholdCondition(
                        condition_id="uk_turnover_target",
                        metric=MetricType.revenue,
                        scope="uk",
                        party="target_group",
                        operator=">",
                        value=70_000_000,
                        currency="GBP",
                        source="s.23",
                        source_type=SourceType.primary_legislation,
                    )
                ],
            )
        ],
        source_passages=[
            SourcePassage(
                passage_id="uk_ea2002_s23_1",
                document_title="Enterprise Act 2002",
                article_reference="s.23(1)",
                document_url="https://www.legislation.gov.uk/ukpga/2002/40/section/23",
                quoted_text=(
                    "the value of the turnover in the United Kingdom of the enterprise being taken over "
                    "exceeds £70 million."
                ),
                supports_conditions=["uk_turnover_target"],
            )
        ],
        gun_jumping=GunJumping(voidable=True),
    )


def test_numeric_parses_gbp_millions():
    text = "exceeds £70 million"
    assert value_in_text(text, 70_000_000, metric=MetricType.revenue, currency="GBP")


def test_bare_numbers_do_not_falsely_confirm():
    # Years, section numbers and day counts must not be read as monetary values.
    text = "Enterprise Act 2002, section 23, phase 1 is 40 working days."
    assert not value_in_text(text, 2002, metric=MetricType.revenue)
    assert not value_in_text(text, 40, metric=MetricType.revenue)
    assert not value_in_text(text, 23, metric=MetricType.revenue)


def test_share_value_requires_close_match():
    # The absolute floor must not let any share in [0, 1] match an expected share.
    text = "a combined market share of 60%"
    assert value_in_text(text, 0.60, metric=MetricType.market_share)
    assert not value_in_text(text, 0.25, metric=MetricType.market_share)


def test_share_fraction_words():
    text = "at least one-quarter of all the goods of that description"
    assert value_in_text(text, 0.25, metric=MetricType.market_share)


def test_offline_uk_passage_gate_passes():
    fetch = build_offline_fetch(FIXTURES)
    report = verify_passages(_uk_rule(), fetch_fn=fetch)
    assert report.passages_grounded
    assert report.numbers_confirmed
    assert "uk_turnover_target" in report.conditions_verified


def test_quote_mismatch_fails():
    rule = _uk_rule()
    rule.source_passages[0].quoted_text = "completely fabricated statutory language"
    report = verify_passages(rule, fetch_fn=build_offline_fetch(FIXTURES))
    assert not report.passages_grounded
    assert any(f.code == "quote_not_found" for f in report.failures)


def test_no_passages_is_unverified_not_confirmed():
    # A jurisdiction with no source_passages must not score as grounded/confirmed
    # just because there is nothing to check (the vacuous-pass flaw).
    rule = _uk_rule()
    rule.source_passages = []
    report = verify_passages(rule, fetch_fn=build_offline_fetch(FIXTURES))
    assert not report.conditions_verified
    assert not report.passages_grounded
    assert not report.numbers_confirmed


def test_annual_adjustment_value_skips_numeric_grounding():
    # Annually adjusted values live in the annual notice, not the statute, so a
    # numeric mismatch against the statute passage must NOT be reported.
    rule = _uk_rule()
    rule.threshold_tests[0].annual_adjustment = True
    rule.threshold_tests[0].effective_date = date(2026, 1, 1)
    rule.threshold_tests[0].conditions[0].value = 999_999_999  # not present in the fixture text
    report = verify_passages(rule, fetch_fn=build_offline_fetch(FIXTURES))
    assert report.passages_grounded  # quote still grounds
    assert not any(f.code == "numeric_mismatch" for f in report.failures)


def test_sentinel_zero_value_skips_numeric_grounding():
    rule = _uk_rule()
    rule.threshold_tests[0].conditions[0].value = 0  # "any" sentinel
    report = verify_passages(rule, fetch_fn=build_offline_fetch(FIXTURES))
    assert not any(f.code == "numeric_mismatch" for f in report.failures)


def test_sidecar_not_loaded_as_jurisdiction(tmp_path):
    # Verification sidecars live alongside jurisdiction YAML; load_all must skip
    # them rather than try to validate them as JurisdictionRule.
    from app.models.jurisdiction_verification import JurisdictionVerification
    from app.services.jurisdiction_verification_store import write_sidecar
    from app.services.threshold_engine import load_all_jurisdictions

    rule = _uk_rule()
    (tmp_path / "uk.yaml").write_text(
        yaml.safe_dump(rule.model_dump(mode="json", exclude_none=True))
    )
    write_sidecar(tmp_path, JurisdictionVerification(jurisdiction_id="uk"))

    rules = load_all_jurisdictions(str(tmp_path))
    assert [r.jurisdiction_id for r in rules] == ["uk"]
