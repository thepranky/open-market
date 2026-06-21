"""Tests for jurisdiction completeness gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.models.jurisdiction import (
    Authority,
    FilingDeadlines,
    GunJumping,
    JurisdictionRule,
    LegalBasis,
    MinorityThresholdRule,
    MinorityThresholds,
    Regime,
    ReviewPeriod,
    ReviewPeriods,
    SourcePassage,
    SourceType,
    ThresholdCondition,
    ThresholdTest,
)
from app.models.jurisdiction_verification import (
    ArchetypeConfig,
    ArchetypeRequirements,
    GateStatus,
    SourceVerificationTier,
)
from app.services.jurisdiction_completeness import build_sidecar_update, evaluate_all, evaluate_completeness

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
ARCHETYPES_PATH = DATA_DIR / "_archetypes.yaml"


def _minimal_rule(**overrides) -> JurisdictionRule:
    base = JurisdictionRule(
        jurisdiction_id="xx",
        jurisdiction_name="Test",
        last_verified=date(2026, 1, 1),
        authority=Authority(name="A", abbreviation="A", url="https://a.test", filing_url="https://a.test/f"),
        regime=Regime(mandatory=True, suspensory=True, voluntary=False),
        legal_basis=[LegalBasis(citation="Act s.1", url="https://a.test/act")],
        filing=FilingDeadlines(pre_closing_required=True),
        review_periods=ReviewPeriods(phase_1=ReviewPeriod(days=30, legal_basis="s.1")),
        threshold_tests=[
            ThresholdTest(
                test_id="t1",
                description="test",
                legal_basis="s.1",
                source_url="https://a.test/s1",
                annual_adjustment=False,
                conditions=[
                    ThresholdCondition(
                        condition_id="c1",
                        metric="revenue",
                        scope="domestic",
                        party="target_group",
                        operator=">",
                        value=100,
                        currency="EUR",
                        source="s.1",
                        source_type=SourceType.primary_legislation,
                    )
                ],
            )
        ],
        source_passages=[
            SourcePassage(
                passage_id="p1",
                document_title="Act",
                article_reference="s.1",
                document_url="https://a.test/s1",
                quoted_text="100",
                supports_conditions=["c1"],
            )
        ],
        gun_jumping=GunJumping(automatic_void=True, legal_basis="s.9", legal_basis_url="https://a.test/s9"),
    )
    return base.model_copy(update=overrides)


def test_duplicate_condition_id_fails():
    rule = _minimal_rule(
        threshold_tests=[
            ThresholdTest(
                test_id="t1",
                description="test",
                legal_basis="s.1",
                source_url="https://a.test/s1",
                annual_adjustment=False,
                conditions=[
                    ThresholdCondition(
                        condition_id="dup",
                        metric="revenue",
                        scope="domestic",
                        party="target_group",
                        operator=">",
                        value=100,
                        currency="EUR",
                        source="s.1",
                    ),
                    ThresholdCondition(
                        condition_id="dup",
                        metric="revenue",
                        scope="domestic",
                        party="acquirer_group",
                        operator=">",
                        value=100,
                        currency="EUR",
                        source="s.1",
                    ),
                ],
            )
        ]
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert not report.passed
    assert any(f.code == "duplicate_condition_id" for f in report.failures)


def test_mandatory_suspensory_requires_gun_jumping():
    rule = _minimal_rule(gun_jumping=None)
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "missing_gun_jumping" for f in report.failures)


def test_missing_effective_date_on_annual_adjustment_test():
    rule = _minimal_rule(
        threshold_tests=[
            ThresholdTest(
                test_id="t1",
                description="annual test",
                legal_basis="s.1",
                source_url="https://a.test/s1",
                annual_adjustment=True,
                effective_date=None,
                conditions=[
                    ThresholdCondition(
                        condition_id="c1",
                        metric="revenue",
                        scope="domestic",
                        party="target_group",
                        operator=">",
                        value=100,
                        currency="EUR",
                        source="s.1",
                        source_type=SourceType.primary_legislation,
                    )
                ],
            )
        ]
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "missing_effective_date" for f in report.failures)


def test_practitioner_condition_requires_note():
    rule = _minimal_rule(
        threshold_tests=[
            ThresholdTest(
                test_id="t1",
                description="test",
                legal_basis="s.1",
                source_url="https://a.test/s1",
                annual_adjustment=False,
                conditions=[
                    ThresholdCondition(
                        condition_id="c1",
                        metric="revenue",
                        scope="domestic",
                        party="target_group",
                        operator=">",
                        value=100,
                        currency="EUR",
                        source="s.1",
                        source_type=SourceType.practitioner,
                        note=None,
                    )
                ],
            )
        ],
        source_passages=[],
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "practitioner_missing_note" for f in report.failures)


def test_orphan_passage_support_fails():
    rule = _minimal_rule(
        source_passages=[
            SourcePassage(
                passage_id="p_orphan",
                document_title="Act",
                article_reference="s.1",
                document_url="https://a.test/s1",
                quoted_text="100",
                supports_conditions=["nonexistent_condition"],
            )
        ]
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "orphan_passage_support" for f in report.failures)


def test_minority_thresholds_applies_without_rules_fails():
    rule = _minimal_rule(
        minority_thresholds=MinorityThresholds(applies=True, standard="percentage_based", rules=[])
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "minority_missing_rules" for f in report.failures)


def test_minority_thresholds_rule_missing_source_fails():
    rule = _minimal_rule(
        minority_thresholds=MinorityThresholds(
            applies=True,
            standard="percentage_based",
            rules=[
                MinorityThresholdRule(rule_id="m1", pct_threshold=25.0, source=""),
            ],
        )
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert any(f.code == "minority_missing_source" for f in report.failures)


def test_minority_thresholds_not_applies_is_skipped():
    rule = _minimal_rule(
        minority_thresholds=MinorityThresholds(applies=False, standard="none", rules=[])
    )
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert not any(f.code.startswith("minority_") for f in report.failures)


def test_eu_archetype_has_required_elements():
    reports = {r.jurisdiction_id: r for r in evaluate_all(DATA_DIR, ARCHETYPES_PATH)}
    eu = reports["eu"]
    assert not any(f.code == "archetype_requires_exclusions" for f in eu.failures)
    assert not any(f.code == "archetype_requires_gun_jumping" for f in eu.failures)


def test_build_sidecar_marks_structure_complete():
    report = evaluate_completeness(_minimal_rule(), ArchetypeConfig())
    sidecar = build_sidecar_update(report)
    assert sidecar.source_tier_breakdown.structure_complete == GateStatus.pass_
    assert sidecar.source_verification_tier == SourceVerificationTier.structure_complete


def test_build_sidecar_demotes_tier_on_failure():
    rule = _minimal_rule(gun_jumping=None)
    report = evaluate_completeness(rule, ArchetypeConfig())
    assert not report.passed
    sidecar = build_sidecar_update(report)
    assert sidecar.source_tier_breakdown.structure_complete == GateStatus.fail
    assert sidecar.source_verification_tier.value < SourceVerificationTier.structure_complete.value


def test_archetype_requires_passages_detects_missing():
    archetype_config = ArchetypeConfig(
        version=1,
        assignments={"xx": ["needs_passages"]},
        archetypes={
            "needs_passages": ArchetypeRequirements(description="test", requires_source_passages=True)
        },
    )
    report_missing = evaluate_completeness(_minimal_rule(source_passages=[]), archetype_config)
    assert any(f.code == "archetype_requires_passages" for f in report_missing.failures)

    report_present = evaluate_completeness(_minimal_rule(), archetype_config)
    assert not any(f.code == "archetype_requires_passages" for f in report_present.failures)
