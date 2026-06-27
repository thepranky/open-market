"""
Minimal tests for apps/api/scripts/cases/extract/ingest_case.py.

Covers: extraction mode is recorded correctly in the review report.
No network access, no Claude calls, no filesystem writes to production YAML.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from extract_case_from_source import ExtractionReport
from ingest_case import stage_validate_draft, write_review_report


def _blank_report(case_id: str = "test_case") -> ExtractionReport:
    return ExtractionReport(case_id=case_id, yaml_path=Path("/dev/null"))


def _write(tmp_path: Path, mode: str) -> str:
    """Call write_review_report with the given extraction_mode; return file contents."""
    report_path = tmp_path / "review.md"
    write_review_report(
        report_path,
        case_id="test_case",
        focus="market_definition",
        draft_path=tmp_path / "draft.yaml",
        fetch_results=[],
        extraction_report=_blank_report(),
        extraction_mode=mode,
        schema_ok=True,
        schema_errors=[],
        integrity_errors=0,
        integrity_warnings=0,
        integrity_issues=[],
    )
    return report_path.read_text()


def test_review_report_records_single_batch_mode(tmp_path):
    assert "single-batch" in _write(tmp_path, "single-batch")


def test_review_report_records_batch_by_section_mode(tmp_path):
    assert "batch-by-section" in _write(tmp_path, "batch-by-section")


def test_stage_validate_draft_passes_clean_record():
    record = {
        "case_id": "test_case",
        "outcome": "cleared",
        "source_documents": [{"doc_id": "doc1"}],
        "product_markets_considered": [
            {"market_id": "pm_1", "definition_status": "defined"}
        ],
        "source_passages": [
            {
                "passage_id": "sp_1",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert ok
    assert errors == []
    assert warnings == []


def test_stage_validate_draft_requires_passage_language_to_match_non_english_doc():
    record = {
        "case_id": "test_case",
        "outcome": "cleared",
        "source_documents": [{"doc_id": "doc1", "language": "deu"}],
        "source_passages": [
            {
                "passage_id": "sp_1",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
                "source_language": "fra",
                "quote_translation": "Translated quote.",
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert not ok
    assert any("must match non-English source document language 'deu'" in e for e in errors)
    assert warnings == []


def test_stage_validate_draft_warns_when_non_english_translation_missing():
    record = {
        "case_id": "test_case",
        "outcome": "cleared",
        "source_documents": [{"doc_id": "doc1", "language": "deu"}],
        "source_passages": [
            {
                "passage_id": "sp_1",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
                "source_language": "deu",
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert ok
    assert errors == []
    assert warnings == ["passage sp_1: non-English quote is missing quote_translation"]


def test_stage_validate_draft_catches_invalid_outcome():
    record = {
        "case_id": "test_case",
        "outcome": "not_a_real_outcome",
        "source_documents": [{"doc_id": "doc1"}],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert not ok
    assert any("outcome" in e for e in errors)


def test_stage_validate_draft_catches_dangling_passage_reference():
    record = {
        "case_id": "test_case",
        "outcome": "unknown",
        "source_documents": [{"doc_id": "doc1"}],
        "source_passages": [
            {
                "passage_id": "sp_1",
                "source_document_id": "nonexistent_doc",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert not ok
    assert any("nonexistent_doc" in e for e in errors)


def test_stage_validate_draft_warns_conclusion_role_linked_to_market():
    record = {
        "case_id": "test_case",
        "outcome": "unknown",
        "source_documents": [{"doc_id": "doc1"}],
        "source_passages": [
            {
                "passage_id": "sp_out",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
                "source_role": "conclusion",
                "quote_snippet": "The Commission clears the transaction.",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert ok  # warnings do not block
    assert errors == []
    assert any("sp_out" in w and "conclusion" in w for w in warnings)


def test_stage_validate_draft_warns_outcome_language_linked_to_geographic_market():
    record = {
        "case_id": "test_case",
        "outcome": "unknown",
        "source_documents": [{"doc_id": "doc1"}],
        "source_passages": [
            {
                "passage_id": "sp_clear",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
                "source_role": "commission_assessment",
                "quote_snippet": (
                    "the Commission considers that the Transaction does not raise "
                    "serious doubts as to its compatibility with the internal market."
                ),
                "supports_markets": [],
                "supports_geographic_markets": ["gm_1"],
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert ok
    assert errors == []
    assert any("sp_clear" in w for w in warnings)


def test_stage_validate_draft_no_warning_for_unlinked_conclusion():
    record = {
        "case_id": "test_case",
        "outcome": "unknown",
        "source_documents": [{"doc_id": "doc1"}],
        "source_passages": [
            {
                "passage_id": "sp_out",
                "source_document_id": "doc1",
                "review_status": "unreviewed",
                "extraction_method": "pdf_extracted",
                "source_role": "conclusion",
                "quote_snippet": "The transaction does not raise serious doubts.",
                "supports_markets": [],
                "supports_geographic_markets": [],
            }
        ],
    }
    ok, errors, warnings = stage_validate_draft(record)
    assert ok
    assert errors == []
    assert warnings == []


# ---------------------------------------------------------------------------
# Coverage warning in review report
# ---------------------------------------------------------------------------

def _make_report_with_coverage(
    tmp_path: Path,
    selected_pages: int,
    total_pages: int,
    focus: str = "market_definition",
) -> str:
    """Write a review report with the given coverage stats and return its text."""
    report = _blank_report()
    report.selection_coverage = {
        "selected_pages": selected_pages,
        "total_non_toc_pages": total_pages,
        "ratio": selected_pages / total_pages if total_pages else 1.0,
    }
    report_path = tmp_path / "review.md"
    write_review_report(
        report_path,
        case_id="test_case",
        focus=focus,
        draft_path=tmp_path / "draft.yaml",
        fetch_results=[],
        extraction_report=report,
        extraction_mode="batch-by-section",
        schema_ok=True,
        schema_errors=[],
        integrity_errors=0,
        integrity_warnings=0,
        integrity_issues=[],
    )
    return report_path.read_text()


def test_review_report_coverage_warning_on_low_ratio(tmp_path):
    """Low coverage on a long decision emits a warning and shows PASS (coverage warning)."""
    text = _make_report_with_coverage(tmp_path, selected_pages=10, total_pages=65)
    assert "coverage warning" in text.lower()
    assert "PASS (coverage warning)" in text
    assert "--full-market-definition-pass" in text


def test_review_report_no_coverage_warning_on_short_doc(tmp_path):
    """Coverage warning is suppressed for short documents (< 30 pages)."""
    text = _make_report_with_coverage(tmp_path, selected_pages=5, total_pages=20)
    assert "coverage warning" not in text.lower()
    assert "PASS" in text


def test_review_report_no_coverage_warning_when_ratio_ok(tmp_path):
    """No coverage warning when selected pages / total pages >= threshold."""
    # 20/65 ≈ 31% > 25% threshold → no warning
    text = _make_report_with_coverage(tmp_path, selected_pages=20, total_pages=65)
    assert "coverage warning" not in text.lower()


def test_review_report_no_coverage_warning_for_other_focus(tmp_path):
    """Coverage warning only fires for market_definition focus."""
    text = _make_report_with_coverage(
        tmp_path, selected_pages=5, total_pages=65, focus="remedies"
    )
    assert "coverage warning" not in text.lower()


# ---------------------------------------------------------------------------
# --page-range argument parsing (tested via main() with a minimal YAML fixture)
# ---------------------------------------------------------------------------

import textwrap
from unittest.mock import patch


def _run_main_with_args(args: list[str], tmp_cases_dir: Path) -> int:
    """
    Import main from ingest_case and run it with a fake YAML and args.
    Patches _CASES_DIR so it resolves the fixture YAML without touching production data/.
    """
    import ingest_case as ic

    with patch.object(ic, "_CASES_DIR", tmp_cases_dir):
        with patch("sys.argv", ["ingest_case.py"] + args):
            return ic.main()


def _write_minimal_seed(tmp_path: Path, case_id: str = "eu_test_case_2023") -> Path:
    """Write a minimal seed YAML for argument-parsing tests."""
    seed = textwrap.dedent(f"""\
        case_id: {case_id}
        case_name: "Test Case"
        jurisdiction: EU
        authority: European Commission
        authority_reference: M.9999
        decision_date: "2023-01-01"
        case_type: merger
        procedure_stage: phase1
        sector: test
        outcome: unknown
        source_documents:
          - doc_id: test_doc
            title: "Test Decision"
            doc_type: decision
        source_passages: []
        metadata:
          extraction_method: manually_added
          review_status: unreviewed
          overall_confidence: 0.0
          created_date: "2023-01-01"
          last_updated_date: "2023-01-01"
    """)
    eu_dir = tmp_path / "eu"
    eu_dir.mkdir()
    yaml_path = eu_dir / f"{case_id}.yaml"
    yaml_path.write_text(seed)
    return yaml_path


class TestPageRangeParsing:
    """--page-range argument parsing and validation in main()."""

    def test_invalid_format_no_colon(self, tmp_path, capsys):
        """Non-colon format is rejected with a clear error."""
        _write_minimal_seed(tmp_path)
        rc = _run_main_with_args(
            ["--case-id", "eu_test_case_2023", "--page-range", "64309", "--no-claude"],
            tmp_path,
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "Invalid --page-range" in out

    def test_invalid_format_non_integer(self, tmp_path, capsys):
        """Non-integer values are rejected."""
        _write_minimal_seed(tmp_path)
        rc = _run_main_with_args(
            ["--case-id", "eu_test_case_2023", "--page-range", "start:end", "--no-claude"],
            tmp_path,
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "Invalid --page-range" in out

    def test_invalid_start_zero(self, tmp_path, capsys):
        """START=0 is rejected (pages are 1-indexed)."""
        _write_minimal_seed(tmp_path)
        rc = _run_main_with_args(
            ["--case-id", "eu_test_case_2023", "--page-range", "0:100", "--no-claude"],
            tmp_path,
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "START must be >= 1" in out

    def test_invalid_end_before_start(self, tmp_path, capsys):
        """END < START is rejected."""
        _write_minimal_seed(tmp_path)
        rc = _run_main_with_args(
            ["--case-id", "eu_test_case_2023", "--page-range", "100:50", "--no-claude"],
            tmp_path,
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "END" in out and "START" in out

    def test_valid_range_shown_in_header(self, tmp_path, capsys):
        """A valid --page-range is echoed in the header output and drives output-suffix."""
        _write_minimal_seed(tmp_path)
        # --no-claude so we don't need a real PDF cache; will fail at stage 1 or 2,
        # but the header (printed before any stage) should show the range.
        _run_main_with_args(
            ["--case-id", "eu_test_case_2023", "--page-range", "64:309",
             "--no-claude", "--focus", "theories"],
            tmp_path,
        )
        out = capsys.readouterr().out
        assert "pp64-309" in out

    def test_output_suffix_auto_derived_from_page_range(self, tmp_path):
        """Draft path uses pp{start}-{end} suffix when --output-suffix is omitted."""
        _write_minimal_seed(tmp_path)
        import ingest_case as ic

        with patch.object(ic, "_CASES_DIR", tmp_path):
            with patch("sys.argv", [
                "ingest_case.py",
                "--case-id", "eu_test_case_2023",
                "--page-range", "100:200",
                "--no-claude",
                "--focus", "theories",
            ]):
                # Capture the draft_path value by patching extract_case and reading
                # what path ingest_case derives. We just need the suffix in the
                # console header, which already includes Draft out: line.
                import io
                import contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    ic.main()
        output = buf.getvalue()
        assert "pp100-200" in output

    def test_explicit_output_suffix_overrides_page_range_default(self, tmp_path):
        """--output-suffix takes precedence over the auto-derived pp{start}-{end}."""
        _write_minimal_seed(tmp_path)
        import ingest_case as ic

        with patch.object(ic, "_CASES_DIR", tmp_path):
            with patch("sys.argv", [
                "ingest_case.py",
                "--case-id", "eu_test_case_2023",
                "--page-range", "100:200",
                "--output-suffix", "section_viii",
                "--no-claude",
                "--focus", "theories",
            ]):
                import io
                import contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    ic.main()
        output = buf.getvalue()
        assert "section_viii" in output
        # Draft path uses the explicit suffix, not the auto-derived pp{start}-{end}
        draft_line = next((line for line in output.splitlines() if "Draft out:" in line), "")
        assert "section_viii" in draft_line
        assert "pp100-200" not in draft_line

    def test_no_page_range_no_suffix_in_draft_path(self, tmp_path):
        """Without --page-range, draft path has no extra suffix component."""
        _write_minimal_seed(tmp_path)
        import ingest_case as ic

        with patch.object(ic, "_CASES_DIR", tmp_path):
            with patch("sys.argv", [
                "ingest_case.py",
                "--case-id", "eu_test_case_2023",
                "--no-claude",
                "--focus", "market_definition",
            ]):
                import io
                import contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    ic.main()
        output = buf.getvalue()
        # Draft out line should contain case_id.focus.draft.yaml with no extra token
        assert "eu_test_case_2023.market_definition.draft.yaml" in output
