"""
Minimal tests for apps/api/scripts/ingest_case.py.

Covers: extraction mode is recorded correctly in the review report.
No network access, no Claude calls, no filesystem writes to production YAML.
"""
import sys
import tempfile
from pathlib import Path

import pytest

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
