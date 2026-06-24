"""Structural completeness checks for jurisdiction YAML profiles."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

from app.screening.models.jurisdiction import JurisdictionRule, SourceType
from app.screening.models.jurisdiction_verification import (
    AUTHORITATIVE_SOURCE_TYPES,
    ArchetypeConfig,
    ArchetypeRequirements,
    GateStatus,
    JurisdictionVerification,
    SourceVerificationTier,
    SourceTierBreakdown,
    VerificationFailure,
)
from app.screening.services.jurisdiction_baseline import supported_condition_ids
from app.screening.services.threshold_engine import load_all_jurisdictions


@dataclass
class CompletenessFailure:
    code: str
    message: str
    field_path: Optional[str] = None


@dataclass
class CompletenessReport:
    jurisdiction_id: str
    failures: list[CompletenessFailure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def _fail(code: str, message: str, field_path: Optional[str] = None) -> CompletenessFailure:
    return CompletenessFailure(code=code, message=message, field_path=field_path)


def _all_condition_ids(rule: JurisdictionRule) -> set[str]:
    ids: set[str] = set()
    for test in rule.threshold_tests:
        for condition in test.conditions:
            ids.add(condition.condition_id)
    return ids


def _check_duplicates(rule: JurisdictionRule) -> list[CompletenessFailure]:
    failures: list[CompletenessFailure] = []
    test_ids: list[str] = []
    condition_ids: list[str] = []
    for test in rule.threshold_tests:
        test_ids.append(test.test_id)
        for condition in test.conditions:
            condition_ids.append(condition.condition_id)
    for test_id in sorted(tid for tid, n in Counter(test_ids).items() if n > 1):
        failures.append(_fail("duplicate_test_id", f"Duplicate test_id '{test_id}'", f"threshold_tests.{test_id}"))
    for condition_id in sorted(cid for cid, n in Counter(condition_ids).items() if n > 1):
        failures.append(
            _fail("duplicate_condition_id", f"Duplicate condition_id '{condition_id}'", f"conditions.{condition_id}")
        )
    return failures


def _check_tests_and_conditions(rule: JurisdictionRule, supported: set[str]) -> list[CompletenessFailure]:
    failures: list[CompletenessFailure] = []
    condition_ids = _all_condition_ids(rule)

    for index, test in enumerate(rule.threshold_tests):
        prefix = f"threshold_tests[{index}]"
        if not test.legal_basis:
            failures.append(_fail("missing_legal_basis", "Threshold test missing legal_basis", prefix))
        if not test.source_url:
            failures.append(_fail("missing_source_url", "Threshold test missing source_url", prefix))
        if test.annual_adjustment and not test.effective_date:
            failures.append(
                _fail(
                    "missing_effective_date",
                    "annual_adjustment test requires effective_date",
                    f"{prefix}.effective_date",
                )
            )

        for condition in test.conditions:
            if condition.source_type == SourceType.practitioner and not condition.note:
                failures.append(
                    _fail(
                        "practitioner_missing_note",
                        f"Practitioner condition '{condition.condition_id}' requires note",
                        f"conditions.{condition.condition_id}.note",
                    )
                )
            if condition.source_type in AUTHORITATIVE_SOURCE_TYPES:
                has_passage = condition.condition_id in supported
                has_url = bool(condition.source_url or test.source_url)
                if not has_passage and not has_url:
                    failures.append(
                        _fail(
                            "authoritative_missing_source",
                            f"Authoritative condition '{condition.condition_id}' lacks passage support and source_url",
                            f"conditions.{condition.condition_id}",
                        )
                    )

    for passage in rule.source_passages:
        for condition_id in passage.supports_conditions:
            if condition_id not in condition_ids:
                failures.append(
                    _fail(
                        "orphan_passage_support",
                        f"Passage '{passage.passage_id}' supports unknown condition '{condition_id}'",
                        f"source_passages.{passage.passage_id}",
                    )
                )

    return failures


def _check_regime(rule: JurisdictionRule) -> list[CompletenessFailure]:
    failures: list[CompletenessFailure] = []
    if rule.regime.mandatory and rule.regime.suspensory and rule.gun_jumping is None:
        failures.append(
            _fail(
                "missing_gun_jumping",
                "Mandatory suspensory regime requires gun_jumping section",
                "gun_jumping",
            )
        )
    return failures


def _check_archetype(rule: JurisdictionRule, archetype: ArchetypeRequirements, name: str) -> list[CompletenessFailure]:
    failures: list[CompletenessFailure] = []
    prefix = f"archetype.{name}"

    if len(rule.threshold_tests) < archetype.min_threshold_tests:
        failures.append(
            _fail(
                "archetype_min_tests",
                f"Expected at least {archetype.min_threshold_tests} threshold tests",
                prefix,
            )
        )

    if archetype.requires_exclusions and not any(test.exclusions for test in rule.threshold_tests):
        failures.append(_fail("archetype_requires_exclusions", "Expected at least one exclusion", prefix))

    if archetype.requires_gun_jumping and rule.gun_jumping is None:
        failures.append(_fail("archetype_requires_gun_jumping", "Expected gun_jumping section", prefix))

    if archetype.requires_voluntary_regime and not rule.regime.voluntary:
        failures.append(_fail("archetype_requires_voluntary", "Expected voluntary regime flag", "regime.voluntary"))

    if archetype.requires_mandatory_regime and not rule.regime.mandatory:
        failures.append(_fail("archetype_requires_mandatory", "Expected mandatory regime flag", "regime.mandatory"))

    if archetype.requires_suspensory_regime and not rule.regime.suspensory:
        failures.append(_fail("archetype_requires_suspensory", "Expected suspensory regime flag", "regime.suspensory"))

    if archetype.requires_annual_adjustment_flag and not any(t.annual_adjustment for t in rule.threshold_tests):
        failures.append(_fail("archetype_requires_annual_adjustment", "Expected annual_adjustment test", prefix))

    if archetype.requires_fdi_screening:
        if rule.fdi_screening is None or not rule.fdi_screening.applicable:
            failures.append(_fail("archetype_requires_fdi", "Expected applicable fdi_screening section", "fdi_screening"))

    if archetype.requires_source_passages and not rule.source_passages:
        failures.append(_fail("archetype_requires_passages", "Expected source_passages entries", "source_passages"))

    return failures


def _check_minority_thresholds(rule: JurisdictionRule) -> list[CompletenessFailure]:
    failures: list[CompletenessFailure] = []
    block = rule.minority_thresholds
    if block is None or not block.applies:
        return failures

    if not block.rules:
        failures.append(_fail("minority_missing_rules", "minority_thresholds.applies but no rules listed", "minority_thresholds.rules"))
        return failures

    for rule_index, item in enumerate(block.rules):
        if not item.source:
            failures.append(
                _fail(
                    "minority_missing_source",
                    f"Minority rule '{item.rule_id}' missing source citation",
                    f"minority_thresholds.rules[{rule_index}].source",
                )
            )
    return failures


def evaluate_completeness(
    rule: JurisdictionRule,
    archetypes: ArchetypeConfig,
) -> CompletenessReport:
    supported = supported_condition_ids(rule)
    failures: list[CompletenessFailure] = []
    failures.extend(_check_duplicates(rule))
    failures.extend(_check_tests_and_conditions(rule, supported))
    failures.extend(_check_regime(rule))
    failures.extend(_check_minority_thresholds(rule))

    for name, archetype in archetypes.archetypes_for(rule.jurisdiction_id):
        failures.extend(_check_archetype(rule, archetype, name))

    return CompletenessReport(jurisdiction_id=rule.jurisdiction_id, failures=failures)


def evaluate_all(data_dir: Path, archetypes_path: Path) -> list[CompletenessReport]:
    raw = yaml.safe_load(archetypes_path.read_text())
    archetypes = ArchetypeConfig.model_validate(raw)
    rules = load_all_jurisdictions(str(data_dir))
    return [evaluate_completeness(rule, archetypes) for rule in sorted(rules, key=lambda r: r.jurisdiction_id)]


def failures_to_verification_failures(failures: Iterable[CompletenessFailure]) -> list[VerificationFailure]:
    return [
        VerificationFailure(
            gate="verify_jurisdiction_completeness",
            code=f.code,
            message=f.message,
            field_path=f.field_path,
        )
        for f in failures
    ]


def build_sidecar_update(report: CompletenessReport, existing: Optional[JurisdictionVerification] = None) -> JurisdictionVerification:
    sidecar = existing or JurisdictionVerification(jurisdiction_id=report.jurisdiction_id)
    sidecar.source_tier_breakdown.structure_complete = GateStatus.pass_ if report.passed else GateStatus.fail
    sidecar.failures = [f for f in sidecar.failures if f.gate != "verify_jurisdiction_completeness"]
    sidecar.failures.extend(failures_to_verification_failures(report.failures))

    if report.passed:
        if sidecar.source_verification_tier.value < SourceVerificationTier.structure_complete.value:
            sidecar.source_verification_tier = SourceVerificationTier.structure_complete
    elif sidecar.source_verification_tier.value >= SourceVerificationTier.structure_complete.value:
        # Demote to one tier below structure_complete when this gate fails
        sidecar.source_verification_tier = SourceVerificationTier(
            SourceVerificationTier.structure_complete.value - 1
        )

    return sidecar


def load_sidecar(path: Path) -> Optional[JurisdictionVerification]:
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text()) or {}
    return JurisdictionVerification.model_validate(raw)


def write_sidecar(path: Path, sidecar: JurisdictionVerification) -> None:
    payload = sidecar.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
