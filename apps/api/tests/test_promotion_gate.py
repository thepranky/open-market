"""Tests for shared promotion_gate.py policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.promotion_gate import (
    GateResult,
    PromotionCandidate,
    PromotionPaths,
    PromotionPolicy,
    parse_source_integrity_counts,
    run_conflict_gate,
    run_promotion_gate,
    run_source_integrity_gate,
)


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _candidate(tmp_path: Path) -> PromotionCandidate:
    draft = tmp_path / "data" / "drafts" / "eu" / "eu_test_2020.market_definition.draft.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("case_id: eu_test_2020\n", encoding="utf-8")
    return PromotionCandidate(
        case_id="eu_test_2020",
        jurisdiction="eu",
        draft_path=draft,
        draft_kind="market-definition",
        review_status="PASS",
        output_path=tmp_path / "data" / "cases" / "eu" / "eu_test_2020.yaml",
    )


def test_parse_source_integrity_counts_uses_final_summary():
    output = (
        "eu_test 0 error(s), 2 warning(s)\n"
        "Total: 1 case(s) - 1 error(s), 0 warning(s)\n"
    )
    assert parse_source_integrity_counts(output) == (1, 0)


def test_source_integrity_warnings_block_when_policy_requires(tmp_path):
    paths = PromotionPaths(repo_root=tmp_path, python=sys.executable)
    output = "Total: 1 case(s) - 0 error(s), 2 warning(s)\n"

    with patch(
        "scripts.cases.promote.promotion_gate._run_capture",
        return_value=_proc(0, stdout=output),
    ):
        result = run_source_integrity_gate(
            paths,
            "eu_test_2020",
            tmp_path / "cases",
            block_warnings=True,
        )

    assert result.status == "blocked_source_integrity"
    assert result.errors == 0
    assert result.warnings == 2


def test_source_integrity_warnings_can_be_nonblocking(tmp_path):
    paths = PromotionPaths(repo_root=tmp_path, python=sys.executable)
    output = "Total: 1 case(s) - 0 error(s), 2 warning(s)\n"

    with patch(
        "scripts.cases.promote.promotion_gate._run_capture",
        return_value=_proc(0, stdout=output),
    ):
        result = run_source_integrity_gate(
            paths,
            "eu_test_2020",
            tmp_path / "cases",
            block_warnings=False,
        )

    assert result.status == "pass"
    assert result.warnings == 2


def test_conflict_gate_skips_missing_reports(tmp_path):
    candidate = _candidate(tmp_path)
    result = run_conflict_gate(candidate)
    assert result.status == "skipped_no_reports"
    assert result.reports_checked == 0


def test_conflict_gate_blocks_unresolved_conflicts(tmp_path):
    candidate = _candidate(tmp_path)
    report = candidate.draft_path.parent / "eu_test_2020.market_definition.conflicts.yaml"
    report.write_text(
        yaml.dump(
            {
                "conflict_report": {
                    "conflicts": [
                        {"field": "outcome", "resolution": None},
                        {"field": "product_markets", "resolution": "keep"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_conflict_gate(candidate)
    assert result.status == "blocked_conflicts"
    assert "outcome" in result.message
    assert result.reports_checked == 1


def test_run_promotion_gate_fails_fast_after_schema_block(tmp_path):
    candidate = _candidate(tmp_path)
    temp_candidate = tmp_path / "candidate.yaml"
    temp_candidate.write_text("case_id: eu_test_2020\n", encoding="utf-8")

    source_links = MagicMock()
    with (
        patch(
            "scripts.cases.promote.promotion_gate.build_temp_candidate",
            return_value=(temp_candidate, GateResult("pass")),
        ),
        patch(
            "scripts.cases.promote.promotion_gate.run_schema_gate",
            return_value=GateResult("blocked_schema", "schema failed"),
        ),
        patch("scripts.cases.promote.promotion_gate.run_source_links_gate", source_links),
    ):
        outcome = run_promotion_gate(
            candidate,
            paths=PromotionPaths(repo_root=tmp_path),
            policy=PromotionPolicy(overwrite=True),
        )

    assert outcome.status == "blocked_schema"
    assert not candidate.output_path.exists()
    source_links.assert_not_called()


def test_run_promotion_gate_copies_exact_gated_candidate(tmp_path):
    candidate = _candidate(tmp_path)
    temp_candidate = tmp_path / "candidate.yaml"
    temp_candidate.write_text("case_id: eu_test_2020\nmarker: gated\n", encoding="utf-8")

    with (
        patch(
            "scripts.cases.promote.promotion_gate.build_temp_candidate",
            return_value=(temp_candidate, GateResult("pass")),
        ),
        patch("scripts.cases.promote.promotion_gate.run_schema_gate", return_value=GateResult("pass")),
        patch("scripts.cases.promote.promotion_gate.run_source_links_gate", return_value=GateResult("pass")),
        patch(
            "scripts.cases.promote.promotion_gate.run_source_integrity_gate",
            return_value=GateResult("pass", errors=0, warnings=0),
        ),
        patch("scripts.cases.promote.promotion_gate.run_semantic_lint_gate", return_value=GateResult("pass")),
        patch("scripts.cases.promote.promotion_gate.run_conflict_gate", return_value=GateResult("skipped_no_reports")),
    ):
        outcome = run_promotion_gate(
            candidate,
            paths=PromotionPaths(repo_root=tmp_path),
            policy=PromotionPolicy(overwrite=True),
        )

    assert outcome.status == "promoted"
    assert candidate.output_path.read_text(encoding="utf-8") == temp_candidate.read_text(encoding="utf-8")
