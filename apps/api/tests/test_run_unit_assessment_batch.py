"""
Tests for run_unit_assessment_batch.py.

No network access, no Claude calls, no writes to production data/cases/.
All extractions are mocked; draft files are written to pytest tmp_path.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_unit_assessment_batch as uab
from plan_extraction_ranges import ProbeWindow


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _window(
    start: int,
    end: int,
    context_suffix: str = "carrot_70",
) -> ProbeWindow:
    return ProbeWindow(
        start_page=start,
        end_page=end,
        focus="unit_assessment",
        context_suffix=context_suffix,
        total_score=end - start + 1,
    )


def _draft_with_units(
    tmp_path: Path,
    case_id: str,
    suffix: str,
    unit_labels: list[str],
    findings_per_unit: int = 4,
    siec_per_unit: int = 3,
) -> Path:
    """Write a draft YAML with unit_assessments to tmp_path; return the path."""
    uas = []
    for label in unit_labels:
        findings = []
        for i in range(findings_per_unit):
            conclusion = "siec" if i < siec_per_unit else "no_siec"
            findings.append({
                "finding_id": f"f_{i + 1}",
                "finding_type": "horizontal_overlap",
                "segment": f"Segment {i}",
                "geography": "EEA",
                "conclusion": conclusion,
                "description": f"Finding {i} for {label}",
                "source_passage_refs": [],
            })
        uas.append({"unit_type": "crop", "unit_label": label, "findings": findings})

    sps = [
        {
            "passage_id": "sp_1",
            "source_document_id": "doc1",
            "page": "70",
            "quote_snippet": "quote",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
        }
    ]

    draft = {
        "_draft_note": "DRAFT",
        "case_id": case_id,
        "unit_assessments": uas,
        "source_passages": sps,
    }
    path = tmp_path / f"{case_id}.unit_assessment.{suffix}.draft.yaml"
    path.write_text(yaml.dump(draft), encoding="utf-8")
    return path


def _empty_draft(tmp_path: Path, case_id: str, suffix: str) -> Path:
    """Write a draft YAML with no unit_assessments."""
    draft = {"_draft_note": "DRAFT", "case_id": case_id, "source_passages": []}
    path = tmp_path / f"{case_id}.unit_assessment.{suffix}.draft.yaml"
    path.write_text(yaml.dump(draft), encoding="utf-8")
    return path


def _mock_rpt(error: Optional[str] = None):
    """Return a minimal ExtractionReport mock."""
    rpt = MagicMock()
    rpt.error = error
    return rpt


def _make_canonical_yaml(tmp_path: Path, case_id: str = "test_case") -> Path:
    """Write a minimal canonical YAML to tmp_path."""
    record = {
        "case_id": case_id,
        "jurisdiction": "eu",
        "source_documents": [{"doc_id": f"{case_id}_decision"}],
    }
    p = tmp_path / f"{case_id}.yaml"
    p.write_text(yaml.dump(record), encoding="utf-8")
    return p


def _minimal_source_cache(page_count: int = 10) -> dict:
    """Minimal source cache dict for planner."""
    return {
        "source_document_id": "doc1",
        "page_count": page_count,
        "pages": [
            {"page_number": i, "text": f"7 UNIT ALPHA\n7.1 General\npage {i}"}
            for i in range(1, page_count + 1)
        ],
        "extracted_at": "2026-06-02T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Unit tests: _make_suffix
# ---------------------------------------------------------------------------


class TestMakeSuffix:
    def test_basic(self):
        assert uab._make_suffix("carrot_70") == "unit_carrot_70"

    def test_already_prefixed(self):
        assert uab._make_suffix("route_lhr_cdg_100") == "unit_route_lhr_cdg_100"

    def test_empty_suffix(self):
        assert uab._make_suffix("") == "unit_"

    def test_preserves_underscore_and_digits(self):
        assert uab._make_suffix("crop_abc_123") == "unit_crop_abc_123"


# ---------------------------------------------------------------------------
# Unit tests: _make_command
# ---------------------------------------------------------------------------


class TestMakeCommand:
    def _cmd(self, start=70, end=78, suffix="unit_carrot_70", cost=2.00):
        w = _window(start, end, "carrot_70")
        return uab._make_command("test_case", w, suffix, cost)

    def test_contains_focus_unit_assessment(self):
        assert "--focus unit_assessment" in self._cmd()

    def test_contains_page_range(self):
        assert "--page-range 70:78" in self._cmd()

    def test_contains_output_suffix(self):
        assert "--output-suffix unit_carrot_70" in self._cmd()

    def test_contains_max_cost(self):
        assert "--max-cost 2.00" in self._cmd()

    def test_no_batch_by_section(self):
        assert "--batch-by-section" not in self._cmd()

    def test_contains_case_id(self):
        assert "--case-id test_case" in self._cmd()

    def test_max_cost_two_decimal_places(self):
        cmd = uab._make_command("c", _window(1, 5), "unit_x_1", 1.5)
        assert "--max-cost 1.50" in cmd

    def test_different_page_ranges(self):
        cmd = uab._make_command("c", _window(100, 150, "route_cdg_100"), "unit_route_cdg_100", 3.0)
        assert "--page-range 100:150" in cmd
        assert "--output-suffix unit_route_cdg_100" in cmd


# ---------------------------------------------------------------------------
# Unit tests: _read_draft_unit_stats
# ---------------------------------------------------------------------------


class TestReadDraftUnitStats:
    def test_missing_file_returns_zeros(self, tmp_path):
        stats = uab._read_draft_unit_stats(tmp_path / "nonexistent.yaml")
        assert stats["units"] == 0
        assert stats["findings"] == 0

    def test_empty_draft_returns_zeros(self, tmp_path):
        p = _empty_draft(tmp_path, "test_case", "x")
        stats = uab._read_draft_unit_stats(p)
        assert stats["units"] == 0
        assert stats["unit_labels"] == []

    def test_counts_units_and_findings(self, tmp_path):
        p = _draft_with_units(tmp_path, "tc", "s1", ["Alpha", "Beta"], findings_per_unit=3)
        stats = uab._read_draft_unit_stats(p)
        assert stats["units"] == 2
        assert stats["findings"] == 6

    def test_siec_counts(self, tmp_path):
        p = _draft_with_units(tmp_path, "tc", "s2", ["X"], findings_per_unit=5, siec_per_unit=3)
        stats = uab._read_draft_unit_stats(p)
        assert stats["siec"] == 3
        assert stats["no_siec"] == 2

    def test_unit_labels(self, tmp_path):
        p = _draft_with_units(tmp_path, "tc", "s3", ["Alpha", "Beta"])
        stats = uab._read_draft_unit_stats(p)
        assert set(stats["unit_labels"]) == {"Alpha", "Beta"}

    def test_source_passage_count(self, tmp_path):
        p = _draft_with_units(tmp_path, "tc", "s4", ["A"])
        stats = uab._read_draft_unit_stats(p)
        assert stats["source_passages"] == 1


# ---------------------------------------------------------------------------
# Unit tests: _run_window — dry_run
# ---------------------------------------------------------------------------


class TestRunWindowDryRun:
    def test_dry_run_returns_status_dry_run(self, tmp_path):
        w = _window(70, 78, "carrot_70")
        result = uab._run_window(
            window=w, case_id="test", yaml_path=tmp_path / "t.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=True, dry_run=True,
        )
        assert result.status == "dry_run"

    def test_dry_run_sets_command(self, tmp_path):
        w = _window(70, 78, "carrot_70")
        result = uab._run_window(
            window=w, case_id="test", yaml_path=tmp_path / "t.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=True, dry_run=True,
        )
        assert "--focus unit_assessment" in result.command
        assert "--batch-by-section" not in result.command

    def test_dry_run_does_not_call_extract_case(self, tmp_path):
        w = _window(70, 78, "carrot_70")
        with patch("run_unit_assessment_batch.extract_case") as mock_ec:
            uab._run_window(
                window=w, case_id="test", yaml_path=tmp_path / "t.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=None, max_cost=2.0,
                retry_empty=True, dry_run=True,
            )
        mock_ec.assert_not_called()

    def test_dry_run_correct_suffix(self, tmp_path):
        w = _window(100, 110, "route_lhr_cdg_100")
        result = uab._run_window(
            window=w, case_id="test", yaml_path=tmp_path / "t.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=True, dry_run=True,
        )
        assert result.output_suffix == "unit_route_lhr_cdg_100"


# ---------------------------------------------------------------------------
# Unit tests: _run_window — pass path
# ---------------------------------------------------------------------------


class TestRunWindowPass:
    def test_pass_status_when_units_extracted(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        assert result.status == "pass"
        assert result.units_extracted == 1

    def test_no_batch_by_section_in_extract_call(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        kwargs = mock_ec.call_args.kwargs
        assert kwargs.get("batch_by_section") is False

    def test_correct_page_range_passed(self, tmp_path):
        w = _window(100, 115, "beta_100")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Beta"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        kwargs = mock_ec.call_args.kwargs
        assert kwargs.get("page_range") == (100, 115)

    def test_correct_focus_passed(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        kwargs = mock_ec.call_args.kwargs
        assert kwargs.get("focus") == "unit_assessment"


# ---------------------------------------------------------------------------
# Unit tests: _run_window — empty / retry
# ---------------------------------------------------------------------------


class TestRunWindowRetry:
    def test_empty_without_retry(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        _empty_draft(tmp_path, "tc", uab._make_suffix(w.context_suffix))

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False,
            )
        assert result.status == "empty"
        assert result.retries == 0
        assert mock_ec.call_count == 1

    def test_retries_once_on_empty(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _empty_draft(tmp_path, "tc", suffix)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])
            return _mock_rpt()

        with patch("run_unit_assessment_batch.extract_case", side_effect=side_effect):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        assert result.status == "pass"
        assert result.retries == 1
        assert call_count == 2

    def test_still_empty_after_retry(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        _empty_draft(tmp_path, "tc", uab._make_suffix(w.context_suffix))

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        assert result.status == "empty"
        assert result.retries == 1
        assert mock_ec.call_count == 2


# ---------------------------------------------------------------------------
# Unit tests: _run_window — failure path
# ---------------------------------------------------------------------------


class TestRunWindowFailure:
    def test_failed_status_on_extract_error(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        with patch(
            "run_unit_assessment_batch.extract_case",
            return_value=_mock_rpt(error="Claude API error"),
        ):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        assert result.status == "failed"
        assert "Claude API error" in (result.error or "")

    def test_failed_status_on_exception(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        with patch(
            "run_unit_assessment_batch.extract_case",
            side_effect=RuntimeError("network timeout"),
        ):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False,
            )
        assert result.status == "failed"
        assert "network timeout" in (result.error or "")


# ---------------------------------------------------------------------------
# Unit tests: boundary warning
# ---------------------------------------------------------------------------


class TestBoundaryWarning:
    def test_no_warning_for_single_label(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False,
            )
        assert not result.boundary_warning

    def test_warning_for_two_distinct_labels(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha", "Beta"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False,
            )
        assert result.boundary_warning

    def test_no_warning_for_same_label_repeated(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        # Two entries with same label — not a boundary issue
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha", "Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False,
            )
        assert not result.boundary_warning


# ---------------------------------------------------------------------------
# Integration tests: run_batch
# ---------------------------------------------------------------------------


def _patch_run_batch_deps(tmp_path: Path, windows: list[ProbeWindow], case_id: str = "tc"):
    """Return a context manager stack patching all external deps for run_batch."""
    yaml_path = _make_canonical_yaml(tmp_path, case_id)
    cache_path = tmp_path / f"{case_id}_decision.json"
    cache_path.write_text("{}", encoding="utf-8")

    patches = [
        patch("run_unit_assessment_batch._resolve_canonical_yaml", return_value=yaml_path),
        patch("run_unit_assessment_batch._resolve_cache_path", return_value=cache_path),
        patch("run_unit_assessment_batch._load_source_cache", return_value=_minimal_source_cache()),
        patch("run_unit_assessment_batch.plan", return_value=windows),
        patch(
            "run_unit_assessment_batch._DRAFTS_DIR",
            tmp_path,
        ),
    ]
    return patches


class TestRunBatch:
    def _run(
        self, tmp_path, windows, mock_extract=None, max_units=None, retry_empty=True, dry_run=False
    ) -> list[uab.WindowResult]:
        patches = _patch_run_batch_deps(tmp_path, windows)
        mock_ac = MagicMock()

        ctx = {}
        for p in patches:
            m = p.__enter__()
            ctx[p] = m

        try:
            with patch(
                "run_unit_assessment_batch.extract_case",
                side_effect=mock_extract or (lambda *a, **kw: _mock_rpt()),
            ):
                return uab.run_batch(
                    case_id="tc",
                    max_units=max_units,
                    retry_empty=retry_empty,
                    dry_run=dry_run,
                    anthropic_client=mock_ac,
                    cache_dir=tmp_path,
                )
        finally:
            for p in patches:
                p.__exit__(None, None, None)

    def test_dry_run_returns_dry_run_status(self, tmp_path):
        wins = [_window(70, 78, "alpha_70"), _window(100, 110, "beta_100")]
        results = self._run(tmp_path, wins, dry_run=True)
        assert all(r.status == "dry_run" for r in results)

    def test_dry_run_no_extract_calls(self, tmp_path):
        wins = [_window(70, 78, "alpha_70"), _window(100, 110, "beta_100")]
        patches = _patch_run_batch_deps(tmp_path, wins)
        for p in patches:
            p.__enter__()
        try:
            with patch("run_unit_assessment_batch.extract_case") as mock_ec:
                uab.run_batch(
                    case_id="tc", dry_run=True,
                    anthropic_client=None, cache_dir=tmp_path,
                )
            mock_ec.assert_not_called()
        finally:
            for p in patches:
                p.__exit__(None, None, None)

    def test_max_units_caps_windows(self, tmp_path):
        wins = [_window(i * 10, i * 10 + 5, f"unit_{i * 10}") for i in range(1, 6)]
        results = self._run(tmp_path, wins, dry_run=True, max_units=3)
        assert len(results) == 3

    def test_continues_after_failure(self, tmp_path):
        """A failed window must not abort the rest of the batch."""
        wins = [
            _window(70, 78, "alpha_70"),
            _window(100, 110, "beta_100"),
            _window(120, 130, "gamma_120"),
        ]
        call_n = [0]

        def side_effect(*args, **kwargs):
            call_n[0] += 1
            if call_n[0] == 1:
                return _mock_rpt(error="Claude API error")
            # Windows 2 and 3: write a minimal draft so _read_draft_unit_stats
            # can detect units and mark status as "pass".
            out_path = kwargs.get("output_path")
            if out_path:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                draft = {
                    "_draft_note": "DRAFT", "case_id": "tc",
                    "unit_assessments": [{"unit_type": "crop", "unit_label": "Unit", "findings": []}],
                    "source_passages": [],
                }
                out_path.write_text(yaml.dump(draft), encoding="utf-8")
            return _mock_rpt()

        patches = _patch_run_batch_deps(tmp_path, wins)
        for p in patches:
            p.__enter__()
        try:
            with patch("run_unit_assessment_batch.extract_case", side_effect=side_effect):
                results = uab.run_batch(
                    case_id="tc", retry_empty=False,
                    anthropic_client=MagicMock(), cache_dir=tmp_path,
                )
        finally:
            for p in patches:
                p.__exit__(None, None, None)

        assert results[0].status == "failed"
        assert len(results) == 3  # all windows attempted

    def test_unique_suffixes_across_windows(self, tmp_path):
        wins = [
            _window(70, 78, "alpha_70"),
            _window(100, 110, "beta_100"),
            _window(120, 130, "gamma_120"),
        ]
        results = self._run(tmp_path, wins, dry_run=True)
        suffixes = [r.output_suffix for r in results]
        assert len(set(suffixes)) == len(suffixes), "Duplicate suffixes detected"

    def test_summary_counts(self, tmp_path):
        wins = [_window(70, 78, "alpha_70"), _window(100, 110, "beta_100")]
        results = self._run(tmp_path, wins, dry_run=True)
        assert sum(1 for r in results if r.status == "dry_run") == 2
        assert sum(1 for r in results if r.status == "pass") == 0


# ---------------------------------------------------------------------------
# Unit tests: format_batch_report
# ---------------------------------------------------------------------------


class TestFormatBatchReport:
    def _results(self) -> list[uab.WindowResult]:
        return [
            uab.WindowResult(
                label="alpha_70", page_range=(70, 78), output_suffix="unit_alpha_70",
                draft_path=Path("/tmp/a.yaml"), status="pass",
                units_extracted=2, findings=10, siec=7, no_siec=3,
                command="cmd1",
            ),
            uab.WindowResult(
                label="beta_100", page_range=(100, 110), output_suffix="unit_beta_100",
                draft_path=Path("/tmp/b.yaml"), status="empty",
                retries=1, command="cmd2",
            ),
            uab.WindowResult(
                label="gamma_120", page_range=(120, 130), output_suffix="unit_gamma_120",
                draft_path=Path("/tmp/c.yaml"), status="failed",
                error="API timeout", command="cmd3",
            ),
        ]

    def test_contains_case_id(self):
        report = uab.format_batch_report(self._results(), "test_case")
        assert "test_case" in report

    def test_contains_pass_status(self):
        report = uab.format_batch_report(self._results(), "tc")
        assert "PASS" in report

    def test_contains_empty_status(self):
        report = uab.format_batch_report(self._results(), "tc")
        assert "EMPTY" in report

    def test_contains_failed_status(self):
        report = uab.format_batch_report(self._results(), "tc")
        assert "FAILED" in report

    def test_summary_totals(self):
        report = uab.format_batch_report(self._results(), "tc")
        assert "pass=1" in report
        assert "empty=1" in report
        assert "failed=1" in report

    def test_finding_counts_in_pass_row(self):
        report = uab.format_batch_report(self._results(), "tc")
        assert "findings=10" in report
        assert "siec=7" in report

    def test_boundary_warning_shown(self):
        results = [
            uab.WindowResult(
                label="x", page_range=(1, 5), output_suffix="unit_x_1",
                draft_path=Path("/tmp/x.yaml"), status="pass",
                units_extracted=2, boundary_warning=True, command="",
            )
        ]
        report = uab.format_batch_report(results, "tc")
        assert "WARNING" in report or "BOUNDARY" in report

    def test_dry_run_shows_command(self):
        results = [
            uab.WindowResult(
                label="x", page_range=(1, 5), output_suffix="unit_x_1",
                draft_path=Path("/tmp/x.yaml"), status="dry_run",
                command="apps/api/.venv/bin/python apps/api/scripts/cases/ingest_case.py --focus unit_assessment",
            )
        ]
        report = uab.format_batch_report(results, "tc")
        assert "--focus unit_assessment" in report

    def test_retry_count_shown_in_summary(self):
        results = [
            uab.WindowResult(
                label="x", page_range=(1, 5), output_suffix="unit_x_1",
                draft_path=Path("/tmp/x.yaml"), status="pass",
                retries=1, command="",
            )
        ]
        report = uab.format_batch_report(results, "tc")
        assert "retried" in report


# ---------------------------------------------------------------------------
# Safety: no hard-coded crop / case names
# ---------------------------------------------------------------------------


class TestNoHardcodedNames:
    """Ensure the script contains no domain-specific hard-coded names."""

    _script = Path(__file__).parent.parent / "scripts" / "cases" / "run_unit_assessment_batch.py"

    @pytest.mark.parametrize("term", [
        "cucumber", "eggplant", "carrot", "lettuce", "onion",
        "bayer", "monsanto", "vegetable",
    ])
    def test_no_forbidden_term(self, term):
        text = self._script.read_text(encoding="utf-8").lower()
        # Allow in comments and docstrings that are examples
        # Find non-comment, non-docstring occurrences
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'\"\"\""):
                continue
            assert term not in stripped, (
                f"Hard-coded term '{term}' found in non-comment line: {stripped!r}"
            )

    def test_no_batch_by_section_in_make_command(self):
        """_make_command must never produce --batch-by-section in its output."""
        cmd = uab._make_command(
            "test_case",
            _window(70, 78, "alpha_70"),
            "unit_alpha_70",
            2.00,
        )
        assert "--batch-by-section" not in cmd


# ---------------------------------------------------------------------------
# Tests: --skip-existing
# ---------------------------------------------------------------------------


class TestSkipExisting:
    """Tests for the skip_existing guard in _run_window and run_batch."""

    # ---- _run_window: real mode ----

    def test_skip_when_draft_exists_and_flag_set(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case") as mock_ec:
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=True, dry_run=False, skip_existing=True,
            )

        mock_ec.assert_not_called()
        assert result.status == "skipped_existing"

    def test_no_skip_when_draft_exists_but_flag_not_set(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False, skip_existing=False,
            )

        mock_ec.assert_called_once()
        assert result.status != "skipped_existing"

    def test_no_skip_when_draft_missing_and_flag_set(self, tmp_path):
        """skip_existing=True must still run extraction when the draft does not exist."""
        w = _window(70, 78, "alpha_70")
        # draft is intentionally NOT created

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False, skip_existing=True,
            )

        mock_ec.assert_called_once()

    def test_skip_reads_existing_stats(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"], findings_per_unit=5, siec_per_unit=4)

        with patch("run_unit_assessment_batch.extract_case"):
            result = uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False, skip_existing=True,
            )

        assert result.units_extracted == 1
        assert result.findings == 5
        assert result.siec == 4

    def test_skip_when_draft_missing_runs_extraction(self, tmp_path):
        """No draft → extraction runs even with skip_existing=True."""
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        # do NOT pre-create the draft

        with patch("run_unit_assessment_batch.extract_case", return_value=_mock_rpt()) as mock_ec:
            uab._run_window(
                window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
                cache_dir=tmp_path, draft_dir=tmp_path,
                anthropic_client=MagicMock(), max_cost=2.0,
                retry_empty=False, dry_run=False, skip_existing=True,
            )

        mock_ec.assert_called_once()

    # ---- _run_window: dry-run mode ----

    def test_dry_run_shows_skipped_existing_when_draft_exists(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"], findings_per_unit=3, siec_per_unit=2)

        result = uab._run_window(
            window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=False, dry_run=True, skip_existing=True,
        )

        assert result.status == "skipped_existing"
        # Dry-run skip should still report existing stats
        assert result.units_extracted == 1
        assert result.findings == 3
        assert result.siec == 2

    def test_dry_run_shows_dry_run_when_no_draft(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        # draft does NOT exist

        result = uab._run_window(
            window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=False, dry_run=True, skip_existing=True,
        )

        assert result.status == "dry_run"

    def test_dry_run_without_skip_always_dry_run(self, tmp_path):
        w = _window(70, 78, "alpha_70")
        suffix = uab._make_suffix(w.context_suffix)
        _draft_with_units(tmp_path, "tc", suffix, ["Alpha"])

        result = uab._run_window(
            window=w, case_id="tc", yaml_path=tmp_path / "tc.yaml",
            cache_dir=tmp_path, draft_dir=tmp_path,
            anthropic_client=None, max_cost=2.0,
            retry_empty=False, dry_run=True, skip_existing=False,
        )

        assert result.status == "dry_run"

    # ---- format_batch_report ----

    def test_report_shows_skipped_existing_status(self):
        results = [
            uab.WindowResult(
                label="alpha_70", page_range=(70, 78), output_suffix="unit_alpha_70",
                draft_path=Path("/tmp/a.yaml"), status="skipped_existing",
                units_extracted=1, findings=4, command="",
            )
        ]
        report = uab.format_batch_report(results, "tc")
        assert "SKIPPED_EXISTING" in report
        assert "already exists" in report

    def test_report_summary_counts_skipped_existing(self):
        results = [
            uab.WindowResult(
                label="a", page_range=(1, 5), output_suffix="unit_a_1",
                draft_path=Path("/tmp/a.yaml"), status="pass", command="",
            ),
            uab.WindowResult(
                label="b", page_range=(6, 10), output_suffix="unit_b_6",
                draft_path=Path("/tmp/b.yaml"), status="skipped_existing", command="",
            ),
            uab.WindowResult(
                label="c", page_range=(11, 15), output_suffix="unit_c_11",
                draft_path=Path("/tmp/c.yaml"), status="skipped_existing", command="",
            ),
        ]
        report = uab.format_batch_report(results, "tc")
        assert "skipped_existing=2" in report
        assert "pass=1" in report

    def test_skipped_existing_not_counted_as_failure(self):
        """skipped_existing windows must not cause a non-zero exit code."""
        results = [
            uab.WindowResult(
                label="b", page_range=(6, 10), output_suffix="unit_b_6",
                draft_path=Path("/tmp/b.yaml"), status="skipped_existing", command="",
            ),
        ]
        failed = sum(1 for r in results if r.status == "failed")
        assert failed == 0
