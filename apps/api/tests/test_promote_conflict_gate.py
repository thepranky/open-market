"""
Tests for the --conflict-report gate in promote_case_pipeline.py (ROADMAP 5.9).

The gate is report-only and runs before any subprocess, so the block paths are
testable without invoking the real promotion steps.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.promote_case_pipeline import (
    main,
    unresolved_conflicts,
)


def _report(conflicts):
    return {"conflict_report": {
        "case_id": "eu_test_2023", "focus": "market_definition",
        "conflicts": conflicts, "auto_resolved": [],
    }}


def _write(tmp_path, conflicts):
    p = tmp_path / "eu_test_2023.market_definition.conflicts.yaml"
    p.write_text(yaml.dump(_report(conflicts)), encoding="utf-8")
    return p


def test_unresolved_conflicts_lists_open_fields(tmp_path):
    p = _write(tmp_path, [
        {"field": "product_markets/Cement/definition_status", "resolution": "defined"},
        {"field": "outcome", "resolution": None},
        {"field": "product_markets", "resolution": "   "},
    ])
    open_fields = unresolved_conflicts(p)
    assert open_fields == ["outcome", "product_markets"]


def test_fully_resolved_report_is_clean(tmp_path):
    p = _write(tmp_path, [
        {"field": "outcome", "resolution": "blocked"},
        {"field": "product_markets", "resolution": "keep"},
    ])
    assert unresolved_conflicts(p) == []


def test_main_blocks_on_unresolved_report(tmp_path):
    p = _write(tmp_path, [{"field": "outcome", "resolution": None}])
    rc = main(["--case-id", "eu_test_2023", "--conflict-report", str(p)])
    assert rc == 1  # aborts at the gate, before any promotion subprocess


def test_main_blocks_on_missing_report(tmp_path):
    rc = main([
        "--case-id", "eu_test_2023",
        "--conflict-report", str(tmp_path / "does_not_exist.yaml"),
    ])
    assert rc == 1
