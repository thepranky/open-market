"""Tests for run_case_promotion.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.promotion_gate import GateResult, PromotionOutcome
from scripts.cases.promote.run_case_promotion import (
    check_draft_integrity,
    find_merged_draft,
    main,
)

CASE_ID = "eu_test_case_2020"
FOCUS = "market_definition"

_INTEGRITY_OUTPUT_PASS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) ...\n\n"
    "ok eu_test_case_2020  (2 doc(s), 3 passage(s))  0 error(s), 0 warning(s)\n\n"
    "Total: 1 case(s) - 0 error(s), 0 warning(s)\n"
)

_INTEGRITY_OUTPUT_WITH_ERRORS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) ...\n\n"
    "bad eu_test_case_2020  (2 doc(s), 3 passage(s))  1 error(s), 0 warning(s)\n\n"
    "Total: 1 case(s) - 1 error(s), 0 warning(s)\n"
)

_INTEGRITY_OUTPUT_WITH_WARNINGS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) ...\n\n"
    "warn eu_test_case_2020  (2 doc(s), 3 passage(s))  0 error(s), 2 warning(s)\n\n"
    "Total: 1 case(s) - 0 error(s), 2 warning(s)\n"
)


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _outcome(status: str = "promoted") -> PromotionOutcome:
    gates = {
        "candidate": GateResult("pass"),
        "schema": GateResult("pass"),
        "source_links": GateResult("pass"),
        "source_integrity": GateResult("pass", errors=0, warnings=0),
        "semantic_lint": GateResult("pass"),
        "conflict_gate": GateResult("skipped_no_reports", reports_checked=0),
    }
    return PromotionOutcome(
        case_id=CASE_ID,
        status=status,
        draft_path=Path(f"data/drafts/eu/{CASE_ID}.market_definition.draft.yaml"),
        draft_kind="market-definition",
        review_status="operator",
        output_path=Path(f"data/cases/eu/{CASE_ID}.yaml"),
        timestamp="2026-06-29 19:00 UTC",
        message="promoted after grounding gates" if status == "promoted" else status,
        gates=gates,
    )


class TestCheckDraftIntegrity:
    def test_parses_zero_errors_zero_warnings(self):
        with patch("scripts.cases.promote.run_case_promotion._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_PASS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 0
        assert warnings == 0

    def test_parses_errors(self):
        with patch("scripts.cases.promote.run_case_promotion._run_capture") as mock_run:
            mock_run.return_value = _proc(1, _INTEGRITY_OUTPUT_WITH_ERRORS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 1
        assert warnings == 0

    def test_parses_warnings(self):
        with patch("scripts.cases.promote.run_case_promotion._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_WITH_WARNINGS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 0
        assert warnings == 2

    def test_fallback_on_nonzero_exit_without_parseable_output(self):
        with patch("scripts.cases.promote.run_case_promotion._run_capture") as mock_run:
            mock_run.return_value = _proc(1, "unexpected output")
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 1
        assert warnings == 0

    def test_passes_correct_args_to_check_source_integrity(self):
        with patch("scripts.cases.promote.run_case_promotion._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_PASS)
            check_draft_integrity("eu_foo_bar_2021")
        cmd = mock_run.call_args[0][0]
        assert "check_source_integrity.py" in cmd[1]
        assert "--cases-dir" in cmd
        assert "data/drafts" in cmd
        assert "--case-id" in cmd
        assert "eu_foo_bar_2021" in cmd
        assert "--no-cache" in cmd


class TestRunCasePromotion:
    def test_real_promotion_calls_shared_gate_and_graph_seed(self):
        run_gate = MagicMock(return_value=_outcome("promoted"))
        graph_seed = MagicMock(return_value=GateResult("pass"))

        with (
            patch(
                "scripts.cases.promote.run_case_promotion._run_capture",
                return_value=_proc(0, _INTEGRITY_OUTPUT_PASS),
            ),
            patch("scripts.cases.promote.run_case_promotion.run_promotion_gate", run_gate),
            patch("scripts.cases.promote.run_case_promotion.run_graph_seed", graph_seed),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS, "--overwrite"])

        assert rc == 0
        run_gate.assert_called_once()
        graph_seed.assert_called_once()
        candidate = run_gate.call_args.args[0]
        policy = run_gate.call_args.kwargs["policy"]
        assert candidate.case_id == CASE_ID
        assert candidate.draft_kind == "market-definition"
        assert policy.overwrite is True

    def test_gate_failure_aborts_before_graph_seed(self):
        run_gate = MagicMock(return_value=_outcome("blocked_source_integrity"))
        graph_seed = MagicMock()

        with (
            patch(
                "scripts.cases.promote.run_case_promotion._run_capture",
                return_value=_proc(0, _INTEGRITY_OUTPUT_PASS),
            ),
            patch("scripts.cases.promote.run_case_promotion.run_promotion_gate", run_gate),
            patch("scripts.cases.promote.run_case_promotion.run_graph_seed", graph_seed),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])

        assert rc == 1
        graph_seed.assert_not_called()

    def test_draft_integrity_failure_aborts_before_shared_gate(self):
        run_gate = MagicMock()
        with (
            patch(
                "scripts.cases.promote.run_case_promotion._run_capture",
                return_value=_proc(1, _INTEGRITY_OUTPUT_WITH_WARNINGS),
            ),
            patch("scripts.cases.promote.run_case_promotion.run_promotion_gate", run_gate),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])

        assert rc == 1
        run_gate.assert_not_called()

    def test_dry_run_uses_transformer_dry_run_only(self):
        run_gate = MagicMock()
        calls = []

        def run_side_effect(cmd):
            calls.append(cmd)
            return _proc(0)

        with (
            patch(
                "scripts.cases.promote.run_case_promotion._run_capture",
                return_value=_proc(0, _INTEGRITY_OUTPUT_PASS),
            ),
            patch("scripts.cases.promote.run_case_promotion._run", side_effect=run_side_effect),
            patch("scripts.cases.promote.run_case_promotion.run_promotion_gate", run_gate),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS, "--dry-run"])

        assert rc == 0
        assert len(calls) == 1
        assert "promote_draft_to_canonical" in calls[0][1]
        assert "--dry-run" in calls[0]
        run_gate.assert_not_called()

    def test_explicit_merged_draft_skips_legacy_draft_integrity(self):
        run_gate = MagicMock(return_value=_outcome("promoted"))
        graph_seed = MagicMock(return_value=GateResult("pass"))
        run_capture = MagicMock()

        with (
            patch("scripts.cases.promote.run_case_promotion._run_capture", run_capture),
            patch("scripts.cases.promote.run_case_promotion.run_promotion_gate", run_gate),
            patch("scripts.cases.promote.run_case_promotion.run_graph_seed", graph_seed),
        ):
            rc = main([
                "--case-id",
                CASE_ID,
                "--draft",
                f"data/drafts/eu/{CASE_ID}.e2e.merged.draft.yaml",
                "--overwrite",
            ])

        assert rc == 0
        run_capture.assert_not_called()
        candidate = run_gate.call_args.args[0]
        assert candidate.draft_kind == "full-depth"


class TestFindMergedDraft:
    def test_returns_path_when_merged_draft_exists(self, tmp_path):
        jur_dir = tmp_path / "eu"
        jur_dir.mkdir(parents=True)
        merged = jur_dir / f"{CASE_ID}.merged.draft.yaml"
        merged.write_text("case_id: eu_test_case_2020\n", encoding="utf-8")
        assert find_merged_draft(CASE_ID, tmp_path) == merged

    def test_returns_none_when_merged_draft_absent(self, tmp_path):
        (tmp_path / "eu").mkdir(parents=True)
        assert find_merged_draft(CASE_ID, tmp_path) is None
