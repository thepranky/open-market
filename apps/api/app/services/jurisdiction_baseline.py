"""Baseline source-coverage metrics for jurisdiction YAML profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.models.jurisdiction import JurisdictionRule, SourceType
from app.models.jurisdiction_verification import (
    AUTHORITATIVE_SOURCE_TYPES,
    ArchetypeConfig,
    BaselineCoverageReport,
    BaselineJurisdictionRow,
)
from app.services.threshold_engine import load_all_jurisdictions


def _load_archetypes(path: Path) -> ArchetypeConfig:
    raw = yaml.safe_load(path.read_text())
    return ArchetypeConfig.model_validate(raw)


def supported_condition_ids(rule: JurisdictionRule) -> set[str]:
    supported: set[str] = set()
    for passage in rule.source_passages:
        supported.update(passage.supports_conditions)
    return supported


def _is_authoritative(source_type: SourceType) -> bool:
    return source_type in AUTHORITATIVE_SOURCE_TYPES


def compute_baseline_report(
    data_dir: Path,
    archetypes_path: Path | None = None,
) -> BaselineCoverageReport:
    rules = load_all_jurisdictions(str(data_dir))
    archetypes = (
        _load_archetypes(archetypes_path)
        if archetypes_path and archetypes_path.exists()
        else ArchetypeConfig()
    )

    rows: list[BaselineJurisdictionRow] = []
    total_conditions = 0
    primary_count = 0
    authoritative_count = 0
    with_source_url = 0
    passage_count = 0
    supported_total = 0
    authoritative_missing = 0
    no_passages: list[str] = []
    annual_tests = 0

    for rule in sorted(rules, key=lambda r: r.jurisdiction_id):
        supported = supported_condition_ids(rule)
        jid = rule.jurisdiction_id
        if not rule.source_passages:
            no_passages.append(jid)

        row_conditions = 0
        row_authoritative = 0
        row_missing = 0
        row_annual = 0

        for test in rule.threshold_tests:
            if test.annual_adjustment:
                row_annual += 1
                annual_tests += 1
            for condition in test.conditions:
                row_conditions += 1
                total_conditions += 1
                if condition.source_type == SourceType.primary_legislation:
                    primary_count += 1
                if _is_authoritative(condition.source_type):
                    row_authoritative += 1
                    authoritative_count += 1
                    if condition.condition_id not in supported:
                        row_missing += 1
                        authoritative_missing += 1
                if condition.source_url:
                    with_source_url += 1

        passage_count += len(rule.source_passages)
        supported_total += len(supported)

        rows.append(
            BaselineJurisdictionRow(
                jurisdiction_id=jid,
                condition_count=row_conditions,
                authoritative_condition_count=row_authoritative,
                source_passage_count=len(rule.source_passages),
                supported_condition_count=len(supported),
                missing_passage_support_count=row_missing,
                annual_adjustment_test_count=row_annual,
                archetypes=[name for name, _ in archetypes.archetypes_for(jid)],
            )
        )

    return BaselineCoverageReport(
        generated_at=datetime.now(timezone.utc),
        jurisdiction_count=len(rules),
        threshold_condition_count=total_conditions,
        primary_legislation_condition_count=primary_count,
        authoritative_condition_count=authoritative_count,
        condition_with_source_url_count=with_source_url,
        source_passage_count=passage_count,
        supported_condition_count=supported_total,
        authoritative_missing_passage_count=authoritative_missing,
        jurisdictions_without_source_passages=sorted(no_passages),
        annual_adjustment_test_count=annual_tests,
        jurisdictions=rows,
    )


def render_baseline_markdown(report: BaselineCoverageReport) -> str:
    generated = report.generated_at.strftime("%Y-%m-%d")
    no_passages = ", ".join(f"`{jid}`" for jid in report.jurisdictions_without_source_passages)
    lines = [
        "# Jurisdiction Verification Baseline",
        "",
        f"*Generated {generated} by `report_jurisdiction_verification_baseline.py`.*",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Jurisdiction YAML profiles | {report.jurisdiction_count} |",
        f"| Threshold conditions | {report.threshold_condition_count} |",
        f"| Conditions with `source_type: primary_legislation` | {report.primary_legislation_condition_count} |",
        f"| Authoritative hard-fact conditions | {report.authoritative_condition_count} |",
        f"| Conditions with direct `source_url` | {report.condition_with_source_url_count} |",
        f"| `source_passages[]` entries | {report.source_passage_count} |",
        f"| Condition IDs supported by passages | {report.supported_condition_count} |",
        f"| Authoritative conditions missing passage support | {report.authoritative_missing_passage_count} |",
        f"| Jurisdictions with no `source_passages` | {len(report.jurisdictions_without_source_passages)} |",
        f"| Annual-adjustment threshold tests | {report.annual_adjustment_test_count} |",
        "",
        "## Jurisdictions without source passages",
        "",
        no_passages or "_None_",
        "",
        "## Per-jurisdiction coverage",
        "",
        "| Jurisdiction | Conditions | Auth. | Passages | Supported | Missing support | Annual tests | Archetypes |",
        "|--------------|------------|-------|----------|-----------|-----------------|--------------|------------|",
    ]

    for row in report.jurisdictions:
        archetypes = ", ".join(row.archetypes) if row.archetypes else "—"
        lines.append(
            f"| `{row.jurisdiction_id}` | {row.condition_count} | {row.authoritative_condition_count} | "
            f"{row.source_passage_count} | {row.supported_condition_count} | "
            f"{row.missing_passage_support_count} | {row.annual_adjustment_test_count} | {archetypes} |"
        )

    lines.extend(["", "---", "", "Regenerate with:", "", "```bash", "python apps/api/scripts/report_jurisdiction_verification_baseline.py --write", "```", ""])
    return "\n".join(lines)
