"""
Tests for promote_case_pipeline.py.

Covers:
  - promote_draft_to_canonical is NOT called when draft integrity fails (errors or warnings)
  - promote_draft_to_canonical IS called when draft integrity passes
  - Each downstream step is called with the expected command
  - Pipeline aborts and returns non-zero on any step failure
  - --dry-run skips downstream steps after promote
  - Summary is printed in all exit paths
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.promote_case_pipeline import check_draft_integrity, find_merged_draft, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CASE_ID = "eu_test_case_2020"
FOCUS = "market_definition"
STAGE = "phase1"

_INTEGRITY_OUTPUT_PASS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) …\n\n"
    "✓ eu_test_case_2020  (2 doc(s), 3 passage(s))  0 error(s), 0 warning(s)\n\n"
    "────────────────────────────────────────────────────────────\n"
    "Total: 1 case(s) — 0 error(s), 0 warning(s)\n"
)

_INTEGRITY_OUTPUT_WITH_ERRORS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) …\n\n"
    "✗ eu_test_case_2020  (2 doc(s), 3 passage(s))  1 error(s), 0 warning(s)\n\n"
    "────────────────────────────────────────────────────────────\n"
    "Total: 1 case(s) — 1 error(s), 0 warning(s)\n"
)

_INTEGRITY_OUTPUT_WITH_WARNINGS = (
    "Meridian Source Integrity Check (page cache: disabled)\n"
    "Checking 1 case file(s) …\n\n"
    "⚠ eu_test_case_2020  (2 doc(s), 3 passage(s))  0 error(s), 2 warning(s)\n\n"
    "────────────────────────────────────────────────────────────\n"
    "Total: 1 case(s) — 0 error(s), 2 warning(s)\n"
)


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# check_draft_integrity unit tests
# ---------------------------------------------------------------------------

class TestCheckDraftIntegrity:
    def test_parses_zero_errors_zero_warnings(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_PASS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 0
        assert warnings == 0

    def test_parses_errors(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(1, _INTEGRITY_OUTPUT_WITH_ERRORS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 1
        assert warnings == 0

    def test_parses_warnings(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_WITH_WARNINGS)
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 0
        assert warnings == 2

    def test_fallback_on_nonzero_exit_without_parseable_output(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(1, "unexpected output")
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 1
        assert warnings == 0

    def test_no_error_on_clean_exit_without_summary_line(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(0, "No YAML files found")
            errors, warnings = check_draft_integrity(CASE_ID)
        assert errors == 0
        assert warnings == 0

    def test_passes_correct_args_to_check_source_integrity(self):
        with patch("scripts.cases.promote.promote_case_pipeline._run_capture") as mock_run:
            mock_run.return_value = _proc(0, _INTEGRITY_OUTPUT_PASS)
            check_draft_integrity("eu_foo_bar_2021")
        cmd = mock_run.call_args[0][0]
        assert "check_source_integrity.py" in cmd[1]
        assert "--cases-dir" in cmd
        assert "data/drafts" in cmd
        assert "--case-id" in cmd
        assert "eu_foo_bar_2021" in cmd
        assert "--no-cache" in cmd


# ---------------------------------------------------------------------------
# Main pipeline integration tests (all subprocess calls mocked)
# ---------------------------------------------------------------------------

def _patch_all(
    *,
    integrity_stdout: str = _INTEGRITY_OUTPUT_PASS,
    integrity_rc: int = 0,
    promote_rc: int = 0,
    validate_rc: int = 0,
    source_links_rc: int = 0,
    canonical_integrity_rc: int = 0,
    graph_seed_rc: int = 0,
    learning_log_rc: int = 0,
    apply_learning_rc: int = 0,
):
    """
    Patch _run_capture (draft integrity) and _run (all other steps).
    Returns a dict with the mock objects.
    """
    run_capture_mock = MagicMock(
        return_value=_proc(integrity_rc, integrity_stdout)
    )
    returncodes = iter([
        promote_rc,
        validate_rc,
        source_links_rc,
        canonical_integrity_rc,
        graph_seed_rc,
        learning_log_rc,
        apply_learning_rc,
    ])

    def _run_side_effect(cmd):
        rc = next(returncodes)
        return _proc(rc)

    run_mock = MagicMock(side_effect=_run_side_effect)
    return {"run_capture": run_capture_mock, "run": run_mock}


class TestMainPipelineAbortOnDraftIntegrityErrors:
    """promote_draft_to_canonical must NOT be called when draft integrity fails."""

    def test_abort_on_errors(self, capsys):
        mocks = _patch_all(integrity_stdout=_INTEGRITY_OUTPUT_WITH_ERRORS, integrity_rc=1)
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture", mocks["run_capture"]),
            patch("scripts.cases.promote.promote_case_pipeline._run", mocks["run"]),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])

        assert rc == 1
        # _run (which drives promote and all downstream steps) must never be called
        mocks["run"].assert_not_called()

    def test_abort_on_warnings(self, capsys):
        mocks = _patch_all(integrity_stdout=_INTEGRITY_OUTPUT_WITH_WARNINGS, integrity_rc=0)
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture", mocks["run_capture"]),
            patch("scripts.cases.promote.promote_case_pipeline._run", mocks["run"]),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])

        assert rc == 1
        mocks["run"].assert_not_called()

    def test_abort_message_in_stderr(self, capsys):
        mocks = _patch_all(integrity_stdout=_INTEGRITY_OUTPUT_WITH_ERRORS, integrity_rc=1)
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture", mocks["run_capture"]),
            patch("scripts.cases.promote.promote_case_pipeline._run", mocks["run"]),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS])

        captured = capsys.readouterr()
        assert "aborted" in captured.err.lower() or "aborted" in captured.out.lower()


class TestMainPipelineHappyPath:
    def test_all_steps_called_in_order(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS, "--overwrite"])

        assert rc == 0
        script_names = [c[1] for c in calls_made]  # second element is the script path
        assert any("promote_draft_to_canonical" in s for s in script_names)
        assert any("validate_cases" in s for s in script_names)
        assert any("check_source_links" in s for s in script_names)
        assert any("check_source_integrity" in s for s in script_names)
        assert any("seed_graph" in s for s in script_names)
        assert any("create_review_learning_log" in s for s in script_names)
        assert any("apply_review_learning" in s for s in script_names)

    def test_promote_called_with_overwrite_flag(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS, "--overwrite"])

        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert "--overwrite" in promote_cmd

    def test_promote_called_with_procedure_stage(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS, "--procedure-stage", STAGE])

        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert "--procedure-stage" in promote_cmd
        assert STAGE in promote_cmd

    def test_returns_zero_on_success(self):
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", return_value=_proc(0)),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])
        assert rc == 0


class TestMainPipelineDownstreamFailures:
    def _run_with_nth_failure(self, fail_at: int) -> int:
        """Run pipeline where the Nth _run call returns rc=1."""
        counter = [0]

        def run_side_effect(cmd):
            counter[0] += 1
            return _proc(1 if counter[0] == fail_at else 0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            return main(["--case-id", CASE_ID, "--focus", FOCUS, "--overwrite"])

    def test_promote_failure_aborts(self):
        assert self._run_with_nth_failure(1) == 1

    def test_validate_cases_failure_aborts(self):
        assert self._run_with_nth_failure(2) == 1

    def test_source_links_failure_aborts(self):
        assert self._run_with_nth_failure(3) == 1

    def test_canonical_integrity_failure_aborts(self):
        assert self._run_with_nth_failure(4) == 1

    def test_graph_seed_failure_aborts(self):
        assert self._run_with_nth_failure(5) == 1

    def test_learning_log_failure_aborts(self):
        assert self._run_with_nth_failure(6) == 1

    def test_apply_learning_failure_aborts(self):
        assert self._run_with_nth_failure(7) == 1


class TestDryRun:
    def test_dry_run_skips_downstream_steps(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS, "--dry-run"])

        assert rc == 0
        # Only promote should be called (with --dry-run), no downstream steps
        assert len(calls_made) == 1
        promote_cmd = calls_made[0]
        assert "promote_draft_to_canonical" in promote_cmd[1]
        assert "--dry-run" in promote_cmd

    def test_dry_run_does_not_pass_overwrite(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS, "--dry-run", "--overwrite"])

        promote_cmd = calls_made[0]
        assert "--overwrite" not in promote_cmd

    def test_dry_run_still_checks_draft_integrity(self):
        run_capture_mock = MagicMock(return_value=_proc(0, _INTEGRITY_OUTPUT_PASS))

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture", run_capture_mock),
            patch("scripts.cases.promote.promote_case_pipeline._run", return_value=_proc(0)),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS, "--dry-run"])

        run_capture_mock.assert_called_once()
        cmd = run_capture_mock.call_args[0][0]
        assert "check_source_integrity.py" in cmd[1]

    def test_dry_run_aborts_on_draft_integrity_failure(self):
        run_mock = MagicMock()

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(1, _INTEGRITY_OUTPUT_WITH_ERRORS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", run_mock),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS, "--dry-run"])

        assert rc == 1
        run_mock.assert_not_called()


class TestFindMergedDraft:
    def test_returns_path_when_merged_draft_exists(self, tmp_path):
        jur_dir = tmp_path / "eu"
        jur_dir.mkdir(parents=True)
        merged = jur_dir / "eu_test_case_2020.merged.draft.yaml"
        merged.write_text("case_id: eu_test_case_2020\n")
        result = find_merged_draft("eu_test_case_2020", tmp_path)
        assert result == merged

    def test_returns_none_when_merged_draft_absent(self, tmp_path):
        (tmp_path / "eu").mkdir(parents=True)
        result = find_merged_draft("eu_test_case_2020", tmp_path)
        assert result is None

    def test_returns_none_when_directory_absent(self, tmp_path):
        result = find_merged_draft("eu_test_case_2020", tmp_path)
        assert result is None


class TestDraftFlagPassthrough:
    """--draft is forwarded to promote_draft_to_canonical."""

    def test_explicit_draft_passed_to_promote(self):
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
            patch("scripts.cases.promote.promote_case_pipeline.find_merged_draft", return_value=None),
        ):
            rc = main([
                "--case-id", CASE_ID,
                "--draft", "data/drafts/eu/eu_test_case_2020.merged.draft.yaml",
            ])

        assert rc == 0
        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert "--draft" in promote_cmd
        assert "merged.draft.yaml" in " ".join(promote_cmd)
        assert "--focus" not in promote_cmd

    def test_merged_draft_autodetected_when_no_draft_flag(self, tmp_path):
        """When no --draft is given but a merged draft exists, it is used."""
        merged = tmp_path / "eu" / f"{CASE_ID}.merged.draft.yaml"
        merged.parent.mkdir(parents=True)
        merged.write_text("case_id: eu_test_case_2020\n")

        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
            patch("scripts.cases.promote.promote_case_pipeline._DRAFTS_DIR", tmp_path),
        ):
            rc = main(["--case-id", CASE_ID])

        assert rc == 0
        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert "--draft" in promote_cmd
        assert "merged.draft.yaml" in " ".join(promote_cmd)

    def test_focus_used_when_no_merged_draft_and_no_draft_flag(self, tmp_path):
        """Legacy path: no --draft, no merged draft → --focus is passed."""
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
            patch("scripts.cases.promote.promote_case_pipeline.find_merged_draft", return_value=None),
        ):
            rc = main(["--case-id", CASE_ID, "--focus", FOCUS])

        assert rc == 0
        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert "--focus" in promote_cmd
        assert FOCUS in promote_cmd
        assert "--draft" not in promote_cmd

    def test_explicit_draft_overrides_merged_draft_autodetect(self, tmp_path):
        """Explicit --draft takes priority over auto-detected merged draft."""
        merged = tmp_path / "eu" / f"{CASE_ID}.merged.draft.yaml"
        merged.parent.mkdir(parents=True)
        merged.write_text("case_id: eu_test_case_2020\n")

        explicit_draft = "data/drafts/eu/eu_test_case_2020.other.draft.yaml"
        calls_made = []

        def run_side_effect(cmd):
            calls_made.append(cmd)
            return _proc(0)

        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", side_effect=run_side_effect),
            patch("scripts.cases.promote.promote_case_pipeline._DRAFTS_DIR", tmp_path),
        ):
            rc = main(["--case-id", CASE_ID, "--draft", explicit_draft])

        assert rc == 0
        promote_cmd = next(c for c in calls_made if "promote_draft_to_canonical" in c[1])
        assert explicit_draft in promote_cmd

    def test_summary_shows_draft_path(self, capsys):
        """Promotion summary must print the draft path being promoted."""
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", return_value=_proc(0)),
            patch("scripts.cases.promote.promote_case_pipeline.find_merged_draft", return_value=None),
        ):
            main([
                "--case-id", CASE_ID,
                "--draft", "data/drafts/eu/eu_test_case_2020.merged.draft.yaml",
            ])

        captured = capsys.readouterr()
        assert "merged.draft.yaml" in captured.out


class TestSummaryOutput:
    def test_summary_printed_on_success(self, capsys):
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(0, _INTEGRITY_OUTPUT_PASS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", return_value=_proc(0)),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS])

        captured = capsys.readouterr()
        assert "Promotion Summary" in captured.out
        assert "COMPLETE" in captured.out

    def test_summary_printed_on_abort(self, capsys):
        with (
            patch("scripts.cases.promote.promote_case_pipeline._run_capture",
                  return_value=_proc(1, _INTEGRITY_OUTPUT_WITH_ERRORS)),
            patch("scripts.cases.promote.promote_case_pipeline._run", return_value=_proc(0)),
        ):
            main(["--case-id", CASE_ID, "--focus", FOCUS])

        captured = capsys.readouterr()
        assert "Promotion Summary" in captured.out
        assert "ABORTED" in captured.out
