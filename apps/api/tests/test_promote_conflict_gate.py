"""
Tests for the --conflict-report gate in run_case_promotion.py (ROADMAP 5.9).

When --conflict-report is supplied, the gate runs before draft integrity and
promotion subprocesses so block paths stay testable without real gate work.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.run_case_promotion import (
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
    with (
        patch(
            "scripts.cases.promote.run_case_promotion.check_draft_integrity",
            side_effect=AssertionError("draft integrity should not run"),
        ),
        patch(
            "scripts.cases.promote.run_case_promotion.run_promotion_gate",
            side_effect=AssertionError("promotion gate should not run"),
        ),
    ):
        rc = main(["--case-id", "eu_test_2023", "--conflict-report", str(p)])
    assert rc == 1


def test_main_blocks_on_missing_report(tmp_path):
    with (
        patch(
            "scripts.cases.promote.run_case_promotion.check_draft_integrity",
            side_effect=AssertionError("draft integrity should not run"),
        ),
        patch(
            "scripts.cases.promote.run_case_promotion.run_promotion_gate",
            side_effect=AssertionError("promotion gate should not run"),
        ),
    ):
        rc = main([
            "--case-id", "eu_test_2023",
            "--conflict-report", str(tmp_path / "does_not_exist.yaml"),
        ])
    assert rc == 1


def test_non_report_yaml_is_rejected(tmp_path):
    p = tmp_path / "not_a_report.yaml"
    p.write_text(yaml.dump({
        "case_id": "eu_test_2023",
        "product_markets_considered": [{"name": "Cement", "definition_status": "defined"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="not a conflict report"):
        unresolved_conflicts(p)


def test_unwrapped_report_is_accepted(tmp_path):
    p = tmp_path / "unwrapped.yaml"
    p.write_text(yaml.dump({"conflicts": [{"field": "outcome", "resolution": None}]}), encoding="utf-8")
    assert unresolved_conflicts(p) == ["outcome"]


def test_main_blocks_on_non_report_file(tmp_path):
    p = tmp_path / "draft.yaml"
    p.write_text(yaml.dump({"product_markets_considered": []}), encoding="utf-8")
    with (
        patch(
            "scripts.cases.promote.run_case_promotion.check_draft_integrity",
            side_effect=AssertionError("draft integrity should not run"),
        ),
        patch(
            "scripts.cases.promote.run_case_promotion.run_promotion_gate",
            side_effect=AssertionError("promotion gate should not run"),
        ),
    ):
        rc = main(["--case-id", "eu_test_2023", "--conflict-report", str(p)])
    assert rc == 1
