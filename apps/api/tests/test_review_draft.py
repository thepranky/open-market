"""
Tests for apps/api/scripts/review_draft.py.

Covers: preflight checks, prompt building, output validation, and file writing.
No network access and no real Claude calls.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from review_draft import (
    _VALID_TRIAGE_STATUSES,
    _build_review_prompt,
    _check_preflight,
    _find_draft_path,
    _get_page_context,
    _validate_review_output,
    write_llm_review_json,
    write_llm_review_md,
)


# ---------------------------------------------------------------------------
# Minimal draft fixture
# ---------------------------------------------------------------------------

_MINIMAL_DRAFT = {
    "case_id": "test_case_2024",
    "case_name": "Test Corp / Other Corp",
    "authority": "European Commission",
    "jurisdiction": "EU",
    "decision_date": "2024-01-15",
    "source_documents": [{"doc_id": "test_doc"}],
    "product_markets_considered": [
        {
            "market_id": "pm_1",
            "name": "Widget manufacturing",
            "definition_status": "defined",
            "notes": "Commission concluded widgets form a distinct market.",
            "market_importance": "core_assessed",
        }
    ],
    "geographic_markets_considered": [],
    "theories_of_harm": [],
    "source_passages": [
        {
            "passage_id": "sp_1",
            "source_document_id": "test_doc",
            "page": "5",
            "quote_snippet": "The Commission concludes that widgets constitute a separate product market.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "supports_markets": ["pm_1"],
            "supports_geographic_markets": [],
            "supports_theories": [],
        },
        {
            "passage_id": "sp_2",
            "source_document_id": "test_doc",
            "page": "12",
            "quote_snippet": "The Transaction does not raise serious doubts as to its compatibility.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "supports_markets": ["pm_1"],
            "supports_geographic_markets": [],
            "supports_theories": [],
        },
    ],
}

_VALID_REVIEW = {
    "triage_status": "needs_light_review",
    "triage_rationale": "One passage is an outcome conclusion, not market definition support.",
    "passage_reviews": [
        {
            "passage_id": "sp_1",
            "linked_to": ["pm_1"],
            "source_role_in_draft": "not_set",
            "support_verdict": "strong",
            "role_verdict": "correct",
            "note": "",
        },
        {
            "passage_id": "sp_2",
            "linked_to": ["pm_1"],
            "source_role_in_draft": "not_set",
            "support_verdict": "none",
            "role_verdict": "correct",
            "note": "Outcome conclusion, not market definition analysis.",
        },
    ],
    "market_reviews": [
        {
            "market_id": "pm_1",
            "market_name": "Widget manufacturing",
            "market_type": "product",
            "definition_status_verdict": "likely_correct",
            "definition_status_note": "",
            "scope_verdict": "appropriate",
            "scope_note": "",
            "passage_support_verdict": "weakly_supported",
            "outcome_passage_misuse": True,
            "outcome_passage_misuse_note": "sp_2 is an outcome conclusion.",
        }
    ],
    "theory_reviews": [],
    "gap_findings": [],
    "role_misuse_flags": [],
    "definition_status_flags": [],
}


# ---------------------------------------------------------------------------
# _find_draft_path
# ---------------------------------------------------------------------------

def test_find_draft_path_finds_existing(tmp_path):
    draft_dir = tmp_path / "eu"
    draft_dir.mkdir()
    draft_file = draft_dir / "mycase.market_definition.draft.yaml"
    draft_file.write_text("case_id: mycase\n")
    result = _find_draft_path("mycase", "market_definition", tmp_path)
    assert result == draft_file


def test_find_draft_path_returns_none_when_missing(tmp_path):
    result = _find_draft_path("nonexistent_case", "market_definition", tmp_path)
    assert result is None


def test_find_draft_path_searches_nested_dirs(tmp_path):
    draft_dir = tmp_path / "us" / "subdir"
    draft_dir.mkdir(parents=True)
    draft_file = draft_dir / "us_case.market_definition.draft.yaml"
    draft_file.write_text("case_id: us_case\n")
    result = _find_draft_path("us_case", "market_definition", tmp_path)
    assert result == draft_file


# ---------------------------------------------------------------------------
# _check_preflight
# ---------------------------------------------------------------------------

def test_preflight_fails_when_draft_missing(tmp_path):
    draft = tmp_path / "draft.yaml"
    review = tmp_path / "review.md"
    err = _check_preflight(draft, review)
    assert err is not None
    assert "Draft not found" in err


def test_preflight_fails_when_review_md_missing(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text("case_id: x\n")
    review = tmp_path / "review.md"
    err = _check_preflight(draft, review)
    assert err is not None
    assert "Review report not found" in err


def test_preflight_fails_when_review_shows_blocked(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text("case_id: x\n")
    review = tmp_path / "review.md"
    review.write_text("# Review\n\n**Status: BLOCKED**\n")
    err = _check_preflight(draft, review)
    assert err is not None
    assert "BLOCKED" in err


def test_preflight_passes_when_review_shows_pass(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text("case_id: x\n")
    review = tmp_path / "review.md"
    review.write_text("# Review\n\n**Status: PASS**\n")
    err = _check_preflight(draft, review)
    assert err is None


def test_preflight_passes_when_review_shows_pass_with_warnings(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text("case_id: x\n")
    review = tmp_path / "review.md"
    review.write_text("# Review\n\n**Status: PASS**\n\n⚠ Some warning\n")
    err = _check_preflight(draft, review)
    assert err is None


# ---------------------------------------------------------------------------
# _build_review_prompt
# ---------------------------------------------------------------------------

def test_build_review_prompt_includes_passages(tmp_path):
    prompt = _build_review_prompt(_MINIMAL_DRAFT, tmp_path)
    assert "sp_1" in prompt
    assert "sp_2" in prompt
    assert "The Commission concludes that widgets" in prompt


def test_build_review_prompt_includes_market_names(tmp_path):
    prompt = _build_review_prompt(_MINIMAL_DRAFT, tmp_path)
    assert "Widget manufacturing" in prompt
    assert "pm_1" in prompt


def test_build_review_prompt_includes_case_context(tmp_path):
    prompt = _build_review_prompt(_MINIMAL_DRAFT, tmp_path)
    assert "test_case_2024" in prompt
    assert "European Commission" in prompt


def test_build_review_prompt_does_not_exceed_sanity_length(tmp_path):
    prompt = _build_review_prompt(_MINIMAL_DRAFT, tmp_path)
    # A reasonable upper bound for a small case (well under 200K chars)
    assert len(prompt) < 50_000


# ---------------------------------------------------------------------------
# _validate_review_output
# ---------------------------------------------------------------------------

def test_validate_review_output_passes_clean_review():
    known_ids = {"sp_1", "sp_2"}
    errors = _validate_review_output(_VALID_REVIEW, known_ids)
    assert errors == []


def test_validate_review_output_catches_invalid_triage_status():
    bad = dict(_VALID_REVIEW, triage_status="approved")
    errors = _validate_review_output(bad, {"sp_1", "sp_2"})
    assert any("triage_status" in e for e in errors)


def test_validate_review_output_catches_dangling_source_evidence():
    review = dict(_VALID_REVIEW)
    review["gap_findings"] = [
        {
            "gap_type": "missing_geographic_market",
            "description": "EEA-wide not covered",
            "source_evidence": "sp_nonexistent",
            "confidence": "source_backed",
        }
    ]
    errors = _validate_review_output(review, {"sp_1", "sp_2"})
    assert any("sp_nonexistent" in e for e in errors)


def test_validate_review_output_catches_null_evidence_not_speculative():
    review = dict(_VALID_REVIEW)
    review["gap_findings"] = [
        {
            "gap_type": "missing_geographic_market",
            "description": "EEA-wide not covered",
            "source_evidence": None,
            "confidence": "source_backed",  # wrong: should be speculative
        }
    ]
    errors = _validate_review_output(review, {"sp_1", "sp_2"})
    assert any("speculative" in e for e in errors)


def test_validate_review_output_allows_null_evidence_when_speculative():
    review = dict(_VALID_REVIEW)
    review["gap_findings"] = [
        {
            "gap_type": "missing_geographic_market",
            "description": "EEA-wide not covered",
            "source_evidence": None,
            "confidence": "speculative",
        }
    ]
    errors = _validate_review_output(review, {"sp_1", "sp_2"})
    assert errors == []


def test_validate_review_output_catches_lawyer_reviewed_string():
    review = dict(_VALID_REVIEW)
    review["triage_rationale"] = "Passage sp_1 is lawyer_reviewed already."
    errors = _validate_review_output(review, {"sp_1", "sp_2"})
    assert any("lawyer_reviewed" in e for e in errors)


def test_all_valid_triage_statuses_pass_validation():
    known_ids = {"sp_1", "sp_2"}
    for status in _VALID_TRIAGE_STATUSES:
        review = dict(_VALID_REVIEW, triage_status=status)
        errors = _validate_review_output(review, known_ids)
        assert errors == [], f"Status {status!r} should be valid but got: {errors}"


# ---------------------------------------------------------------------------
# _get_page_context
# ---------------------------------------------------------------------------

def test_get_page_context_returns_none_when_no_cache(tmp_path):
    result = _get_page_context("some quote", "missing_doc", "5", tmp_path)
    assert result is None


def test_get_page_context_returns_none_when_page_missing(tmp_path):
    cache = {"pages": [{"page_number": 3, "text": "page three content"}]}
    (tmp_path / "test_doc.json").write_text(json.dumps(cache))
    result = _get_page_context("some quote", "test_doc", "7", tmp_path)
    assert result is None


def test_get_page_context_returns_surrounding_text(tmp_path):
    prefix = "A" * 500
    quote = "The Commission concludes that widgets form a market."
    suffix = "B" * 500
    page_text = prefix + quote + suffix
    cache = {"pages": [{"page_number": 5, "text": page_text}]}
    (tmp_path / "test_doc.json").write_text(json.dumps(cache))
    result = _get_page_context(quote, "test_doc", "5", tmp_path)
    assert result is not None
    assert "Commission concludes" in result
    # Should be shorter than the full page text
    assert len(result) < len(page_text)


# ---------------------------------------------------------------------------
# write_llm_review_json
# ---------------------------------------------------------------------------

def test_write_llm_review_json_creates_file(tmp_path):
    out = tmp_path / "review.json"
    write_llm_review_json(out, _VALID_REVIEW, "test_case", "market_definition",
                          "claude-sonnet-4-6", "2026-05-30T12:00:00Z")
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["case_id"] == "test_case"
    assert data["schema_version"] == "1"
    assert data["triage_status"] == "needs_light_review"


def test_write_llm_review_json_does_not_contain_lawyer_reviewed(tmp_path):
    out = tmp_path / "review.json"
    write_llm_review_json(out, _VALID_REVIEW, "test_case", "market_definition",
                          "claude-sonnet-4-6", "2026-05-30T12:00:00Z")
    assert "lawyer_reviewed" not in out.read_text()


def test_write_llm_review_json_contains_model_and_timestamp(tmp_path):
    out = tmp_path / "review.json"
    write_llm_review_json(out, _VALID_REVIEW, "test_case", "market_definition",
                          "claude-sonnet-4-6", "2026-05-30T12:00:00Z")
    data = json.loads(out.read_text())
    assert data["llm_model"] == "claude-sonnet-4-6"
    assert data["generated_at"] == "2026-05-30T12:00:00Z"


# ---------------------------------------------------------------------------
# write_llm_review_md
# ---------------------------------------------------------------------------

def _write_md(tmp_path: Path) -> str:
    out = tmp_path / "review.md"
    json_path = tmp_path / "review.json"
    write_llm_review_md(
        out, _VALID_REVIEW, "test_case", "market_definition",
        "claude-sonnet-4-6", "2026-05-30T12:00:00Z",
        json_path, [],
    )
    return out.read_text()


def test_write_llm_review_md_creates_file(tmp_path):
    _write_md(tmp_path)
    assert (tmp_path / "review.md").exists()


def test_write_llm_review_md_contains_triage_status(tmp_path):
    content = _write_md(tmp_path)
    assert "needs_light_review" in content


def test_write_llm_review_md_contains_passage_review_section(tmp_path):
    content = _write_md(tmp_path)
    assert "Passage-to-proposition review" in content
    assert "sp_1" in content
    assert "sp_2" in content


def test_write_llm_review_md_contains_market_scope_section(tmp_path):
    content = _write_md(tmp_path)
    assert "Market scope review" in content
    assert "pm_1" in content


def test_write_llm_review_md_contains_gap_findings_section(tmp_path):
    content = _write_md(tmp_path)
    assert "Gap findings" in content


def test_write_llm_review_md_contains_theory_section(tmp_path):
    content = _write_md(tmp_path)
    assert "Theory-of-harm review" in content


def test_write_llm_review_md_contains_outcome_misuse_section(tmp_path):
    content = _write_md(tmp_path)
    assert "serious-doubts" in content or "Outcome" in content


def test_write_llm_review_md_contains_disclaimer(tmp_path):
    content = _write_md(tmp_path)
    assert "not substitute for human or legal" in content
    assert "data/cases/" in content


def test_write_llm_review_md_does_not_contain_lawyer_reviewed(tmp_path):
    content = _write_md(tmp_path)
    assert "lawyer_reviewed" not in content


def test_write_llm_review_md_contains_triage_recommendation(tmp_path):
    content = _write_md(tmp_path)
    assert "Triage recommendation" in content


def test_write_llm_review_md_shows_validation_warnings(tmp_path):
    out = tmp_path / "review.md"
    json_path = tmp_path / "review.json"
    errors = ["triage_status 'foo' is invalid"]
    write_llm_review_md(
        out, _VALID_REVIEW, "test_case", "market_definition",
        "claude-sonnet-4-6", "2026-05-30T12:00:00Z",
        json_path, errors,
    )
    content = out.read_text()
    assert "Validation warnings" in content
    assert "triage_status" in content


# ---------------------------------------------------------------------------
# ingest_case.py integration: write_review_report with llm_triage_status
# ---------------------------------------------------------------------------

def test_write_review_report_includes_llm_triage_section(tmp_path):
    """write_review_report should include Stage 5 LLM section when triage provided."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from extract_case_from_source import ExtractionReport
    from ingest_case import write_review_report

    report_path = tmp_path / "review.md"
    er = ExtractionReport(case_id="test", yaml_path=Path("/dev/null"))
    json_path = tmp_path / "llm_review.json"

    write_review_report(
        report_path,
        case_id="test_case",
        focus="market_definition",
        draft_path=tmp_path / "draft.yaml",
        fetch_results=[],
        extraction_report=er,
        schema_ok=True,
        schema_errors=[],
        integrity_errors=0,
        integrity_warnings=0,
        integrity_issues=[],
        llm_triage_status="needs_light_review",
        llm_review_path=json_path,
    )
    content = report_path.read_text()
    assert "Stage 5" in content
    assert "needs_light_review" in content


def test_write_review_report_unchanged_without_llm_flag(tmp_path):
    """write_review_report with no llm args should not include LLM triage section."""
    from extract_case_from_source import ExtractionReport
    from ingest_case import write_review_report

    report_path = tmp_path / "review.md"
    er = ExtractionReport(case_id="test", yaml_path=Path("/dev/null"))

    write_review_report(
        report_path,
        case_id="test_case",
        focus="market_definition",
        draft_path=tmp_path / "draft.yaml",
        fetch_results=[],
        extraction_report=er,
        schema_ok=True,
        schema_errors=[],
        integrity_errors=0,
        integrity_warnings=0,
        integrity_issues=[],
    )
    content = report_path.read_text()
    # LLM section should not appear when not requested
    assert "Stage 5 — LLM review" not in content
