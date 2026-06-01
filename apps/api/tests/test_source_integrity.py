"""
Unit tests for check_source_integrity.py

All HTTP calls are mocked — no network access required.
"""
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_source_integrity import (
    FetchResult,
    Issue,
    Level,
    _doc_type_hints_in_url,
    _pdf_url_looks_like_portal,
    _title_tokens_in_url,
    _url_uses_opaque_id,
    check_document,
    check_passage,
    check_record,
    extract_text,
    quote_found_in_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_html(body: str = "<html><body>Some content</body></html>") -> FetchResult:
    return FetchResult(
        ok=True, status=200, content_type="text/html; charset=utf-8",
        final_url="https://example.com/page",
        content=body.encode(), error=None,
    )


def _ok_pdf(text: str = "The Court finds the relevant market is X.") -> FetchResult:
    # Build a minimal in-memory PDF using pypdf's writer so extract_text works
    try:
        import pypdf
        writer = pypdf.PdfWriter()
        # pypdf 4.x: add_blank_page then add annotation for text is complex;
        # instead we just return raw bytes that pypdf can partially parse.
        # For test purposes, we mock extract_text directly where needed.
    except ImportError:
        pass
    return FetchResult(
        ok=True, status=200, content_type="application/pdf",
        final_url="https://example.com/doc.pdf",
        content=b"%PDF-1.4 fake",  # real extraction is tested separately
        error=None,
    )


def _broken(status: int = 404) -> FetchResult:
    return FetchResult(
        ok=False, status=status, content_type="",
        final_url="https://example.com/missing.pdf",
        content=None, error=None,
    )


def _timeout() -> FetchResult:
    return FetchResult(
        ok=False, status=None, content_type="",
        final_url="https://example.com/slow.pdf",
        content=None, error="timeout",
    )


def _make_client(result: FetchResult) -> MagicMock:
    """Return a mock httpx.Client whose .get() always returns the given result."""
    mock_response = MagicMock()
    mock_response.status_code = result.status or 200
    mock_response.headers = {"content-type": result.content_type}
    mock_response.content = result.content or b""
    mock_response.url = result.final_url

    if result.error == "timeout":
        import httpx
        client = MagicMock()
        client.get.side_effect = httpx.TimeoutException("timeout")
        return client

    client = MagicMock()
    client.get.return_value = mock_response
    return client


# ---------------------------------------------------------------------------
# quote_found_in_text
# ---------------------------------------------------------------------------

class TestQuoteFoundInText:
    def test_exact_match(self):
        assert quote_found_in_text("The Court finds X", "Before. The Court finds X. After.")

    def test_normalised_match(self):
        # Punctuation and case differences should not prevent matching
        assert quote_found_in_text(
            '"The Court finds the relevant market is X."',
            "The court finds the relevant market is x and more text follows.",
        )

    def test_not_found(self):
        assert not quote_found_in_text(
            "The Court finds the relevant market is X",
            "This document is about something entirely different.",
        )

    def test_empty_quote(self):
        assert not quote_found_in_text("", "Some document text here to search in.")

    def test_empty_text(self):
        assert not quote_found_in_text("The Court finds X", "")

    def test_fragment_match(self):
        # Quote larger than a single fragment — multi-fragment path
        long_quote = (
            "The evidence demonstrates a robust and consistent Spirit effect "
            "Spirit entry on a route is associated with substantial fare reductions"
        )
        text = (
            "Other content here. "
            "The evidence demonstrates a robust and consistent spirit effect "
            "spirit entry on a route is associated with substantial fare reductions "
            "by incumbent carriers and more text after that."
        )
        assert quote_found_in_text(long_quote, text)

    def test_short_quote_too_short_for_fragments(self):
        # Quote shorter than min_fragment falls back to direct check
        assert quote_found_in_text("markets X", "The markets X are defined below.")


# ---------------------------------------------------------------------------
# URL heuristics
# ---------------------------------------------------------------------------

class TestUrlHeuristics:
    def test_portal_detection_bare_domain(self):
        assert _pdf_url_looks_like_portal("https://www.ftc.gov/")

    def test_portal_detection_short_path_no_id(self):
        assert _pdf_url_looks_like_portal("https://www.ftc.gov/mergers")

    def test_not_portal_with_case_id(self):
        assert not _pdf_url_looks_like_portal(
            "https://www.ftc.gov/system/files/ftc_gov/pdf/D09412MicrosoftComplaint.pdf"
        )

    def test_not_portal_ec_case_page(self):
        assert not _pdf_url_looks_like_portal(
            "https://competition-cases.ec.europa.eu/cases/M.9660"
        )

    def test_doc_type_complaint_in_url(self):
        assert _doc_type_hints_in_url(
            "complaint",
            "https://www.ftc.gov/pdf/D09412MicrosoftActivisionComplaint.pdf",
        )

    def test_doc_type_alj_decision_in_url(self):
        assert _doc_type_hints_in_url(
            "alj_decision",
            "https://www.ftc.gov/pdf/d09412initialdecision.pdf",
        )

    def test_doc_type_missing_from_url(self):
        # A complaint URL used for an alj_decision entry should warn
        assert not _doc_type_hints_in_url(
            "alj_decision",
            "https://www.ftc.gov/pdf/D09412MicrosoftActivisionComplaint.pdf",
        )

    def test_title_token_in_url(self):
        assert _title_tokens_in_url(
            "FTC Complaint: Microsoft / Activision Blizzard",
            "https://www.ftc.gov/pdf/D09412MicrosoftActivisionComplaint.pdf",
        )

    def test_title_token_missing(self):
        # Title says "Initial Decision" but URL only contains "complaint"
        assert not _title_tokens_in_url(
            "FTC ALJ Initial Decision Document",
            "https://www.ftc.gov/pdf/D09412SomethingComplaint.pdf",
        )

    def test_unknown_doc_type_skips_check(self):
        assert _doc_type_hints_in_url("press_release", "https://example.com/news/item")

    # --- opaque ID detection ---

    def test_opaque_id_doj_file_download(self):
        assert _url_uses_opaque_id("https://www.justice.gov/atr/case-document/file/1573131/dl")

    def test_opaque_id_doj_media_download(self):
        assert _url_uses_opaque_id("https://www.justice.gov/atr/media/1380311/dl")

    def test_opaque_id_ec_pdf_numeric_dir(self):
        assert _url_uses_opaque_id(
            "https://ec.europa.eu/competition/mergers/cases1/202120/m9660_3314_3.pdf"
        )

    def test_opaque_id_cma_hex_hash(self):
        assert _url_uses_opaque_id(
            "https://assets.publishing.service.gov.uk/media/63b6a80f8fa8f52732a24662/Final_Order.pdf"
        )

    def test_opaque_id_ec_old_format_pdf(self):
        # Old EC URL format (/cases/decisions/mNNNN_NNN_N.pdf) — no 5-digit numeric dir.
        assert _url_uses_opaque_id(
            "https://ec.europa.eu/competition/mergers/cases/decisions/m9276_298_3.pdf"
        )

    def test_title_check_skipped_for_old_ec_format(self):
        # Old-format EC URL: title tokens absent but check should pass (opaque ID).
        assert _title_tokens_in_url(
            "Case M.9276 – Sika / Financière Dry Mix Solutions: Commission Decision",
            "https://ec.europa.eu/competition/mergers/cases/decisions/m9276_298_3.pdf",
        )

    def test_opaque_id_ec_new_format_pdf_with_language_suffix(self):
        # New EC URL format: mNNNN_YYYYMMDD_NNNNN_NNNNNNN_EN.pdf — four numeric
        # segments plus language suffix; the old two-segment pattern did not match.
        assert _url_uses_opaque_id(
            "https://ec.europa.eu/competition/mergers/cases/decisions/m7217_20141003_20310_3962132_EN.pdf"
        )

    def test_title_check_skipped_for_new_ec_format(self):
        assert _title_tokens_in_url(
            "Case M.7217 – Facebook / WhatsApp: Commission Decision",
            "https://ec.europa.eu/competition/mergers/cases/decisions/m7217_20141003_20310_3962132_EN.pdf",
        )

    def test_not_opaque_descriptive_ftc_url(self):
        assert not _url_uses_opaque_id(
            "https://www.ftc.gov/system/files/ftc_gov/pdf/D09412MicrosoftActivisionComplaint.pdf"
        )

    def test_doc_type_check_skipped_for_opaque_id(self):
        # DOJ /file/…/dl URL: complaint keyword absent but check should pass (opaque ID)
        assert _doc_type_hints_in_url(
            "complaint",
            "https://www.justice.gov/atr/case-document/file/1573131/dl",
        )

    def test_title_check_skipped_for_opaque_id(self):
        # EC PDF URL: title tokens absent but check should pass (opaque ID)
        assert _title_tokens_in_url(
            "Case M.9660 – Google / Fitbit: Commission Decision",
            "https://ec.europa.eu/competition/mergers/cases1/202120/m9660_3314_3.pdf",
        )

    def test_doc_type_mismatch_on_descriptive_url(self):
        # Descriptive URL with wrong doc type — should still flag
        assert not _doc_type_hints_in_url(
            "alj_decision",
            "https://www.ftc.gov/pdf/D09412MicrosoftActivisionComplaint.pdf",
        )


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_html_extraction(self):
        html = b"<html><body><p>The Court finds X.</p><script>var x=1</script></body></html>"
        text = extract_text(html, "text/html; charset=utf-8")
        assert text is not None
        assert "The Court finds X" in text
        assert "var x=1" not in text

    def test_unknown_content_type_returns_none(self):
        assert extract_text(b"binary data", "application/octet-stream") is None


# ---------------------------------------------------------------------------
# check_document — mocked fetch
# ---------------------------------------------------------------------------

class TestCheckDocument:
    def _run(self, doc: dict, fetch_result: FetchResult, passage_count: int = 0):
        client = _make_client(fetch_result)
        with patch("check_source_integrity.fetch", return_value=fetch_result):
            return check_document(client, "test_case", doc, passage_count, timeout=5)

    def test_broken_link_is_error(self):
        doc = {"doc_id": "doc1", "pdf_url": "https://example.com/missing.pdf",
               "doc_type": "decision", "title": "Decision X"}
        issues, text = self._run(doc, _broken(404))
        levels = [i.level for i in issues]
        assert Level.ERROR in levels
        errors = [i for i in issues if i.level == Level.ERROR]
        assert "404" in errors[0].message or "Broken" in errors[0].message

    def test_timeout_is_error(self):
        doc = {"doc_id": "doc1", "pdf_url": "https://example.com/slow.pdf",
               "doc_type": "decision", "title": "Decision X"}
        issues, text = self._run(doc, _timeout())
        levels = [i.level for i in issues]
        assert Level.ERROR in levels

    def test_ok_pdf_passes(self):
        doc = {
            "doc_id": "doc1",
            "pdf_url": "https://example.com/cases/D09412MicrosoftComplaint.pdf",
            "doc_type": "complaint",
            "title": "FTC Complaint Microsoft Activision",
        }
        result = FetchResult(True, 200, "application/pdf",
                             "https://example.com/cases/D09412MicrosoftComplaint.pdf",
                             b"%PDF-1.4 placeholder", None)
        issues, _ = self._run(doc, result)
        errors = [i for i in issues if i.level == Level.ERROR]
        assert not errors

    def test_pdf_url_returning_html_is_warning(self):
        doc = {
            "doc_id": "doc1",
            "pdf_url": "https://example.com/decision.pdf",
            "doc_type": "decision",
            "title": "Some Decision",
        }
        html_result = FetchResult(True, 200, "text/html",
                                  "https://example.com/landing",
                                  b"<html></html>", None)
        issues, _ = self._run(doc, html_result)
        warnings = [i for i in issues if i.level == Level.WARNING]
        assert any("text/html" in w.message for w in warnings)

    def test_no_url_is_error(self):
        doc = {"doc_id": "doc1", "doc_type": "decision", "title": "X"}
        # Should not need to call fetch at all
        client = MagicMock()
        issues, text = check_document(client, "test_case", doc, 0, timeout=5)
        assert any(i.level == Level.ERROR for i in issues)
        assert any("No URL" in i.message for i in issues)

    def test_alj_decision_fake_url_broken(self):
        """Reproduces the microsoft_activision fake ALJ decision scenario."""
        doc = {
            "doc_id": "ftc_msft_activision_alj_decision",
            "title": "FTC ALJ Initial Decision: Microsoft / Activision Blizzard",
            "pdf_url": "https://www.ftc.gov/system/files/ftc_gov/pdf/d09412microsoftactivisioninitialdecision.pdf",
            "case_page_url": "https://www.ftc.gov/legal-library/browse/cases-proceedings/2210077-...",
            "doc_type": "alj_decision",
            "retrieval_status": "direct",
        }
        issues, _ = self._run(doc, _broken(404))
        assert any(i.level == Level.ERROR for i in issues), (
            "A 404 ALJ decision URL must raise ERROR — "
            "this is the scenario the gate was built to catch"
        )


# ---------------------------------------------------------------------------
# check_passage
# ---------------------------------------------------------------------------

class TestCheckPassage:
    def _doc_map(self) -> dict:
        return {
            "doc1": {"doc_id": "doc1", "title": "Real Doc", "pdf_url": "https://x.com/doc.pdf"}
        }

    def test_dangling_source_document_id(self):
        passage = {"passage_id": "sp1", "source_document_id": "nonexistent",
                   "quote_snippet": "Some quote text here"}
        issues = check_passage("case1", passage, self._doc_map(), {"doc1": "doc text"})
        assert any(i.level == Level.ERROR for i in issues)
        assert any("not found" in i.message for i in issues)

    def test_empty_quote_is_error(self):
        passage = {"passage_id": "sp1", "source_document_id": "doc1",
                   "quote_snippet": ""}
        issues = check_passage("case1", passage, self._doc_map(), {"doc1": "doc text"})
        assert any(i.level == Level.ERROR for i in issues)
        assert any("empty" in i.message for i in issues)

    def test_missing_source_document_id_field(self):
        passage = {"passage_id": "sp1", "quote_snippet": "Some text"}
        issues = check_passage("case1", passage, self._doc_map(), {})
        assert any(i.level == Level.ERROR and "Missing source_document_id" in i.message
                   for i in issues)

    def test_quote_found(self):
        text = "The Court finds the relevant market is defined as X."
        passage = {"passage_id": "sp1", "source_document_id": "doc1",
                   "quote_snippet": "The Court finds the relevant market is defined as X."}
        issues = check_passage("case1", passage, self._doc_map(), {"doc1": text})
        assert any(i.level == Level.INFO and "found" in i.message for i in issues)
        assert not any(i.level == Level.ERROR for i in issues)

    def test_quote_not_found_is_warning(self):
        text = "This document discusses a completely different topic with no relevant passage."
        passage = {"passage_id": "sp1", "source_document_id": "doc1",
                   "quote_snippet": "The Court finds the relevant market is defined as X and Y."}
        issues = check_passage("case1", passage, self._doc_map(), {"doc1": text})
        assert any(i.level == Level.WARNING for i in issues)

    def test_no_text_available_is_info_skip(self):
        passage = {"passage_id": "sp1", "source_document_id": "doc1",
                   "quote_snippet": "Some important quote from the decision."}
        issues = check_passage("case1", passage, self._doc_map(), {"doc1": None})
        assert any(i.level == Level.INFO and "skipped" in i.message for i in issues)
        assert not any(i.level == Level.ERROR for i in issues)


# ---------------------------------------------------------------------------
# check_record — integration (mocked)
# ---------------------------------------------------------------------------

class TestCheckRecord:
    def _record_with_alj_fake(self) -> dict:
        """The pre-fix microsoft_activision record with the fake ALJ decision."""
        return {
            "case_id": "us_microsoft_activision_2023",
            "source_documents": [
                {
                    "doc_id": "ftc_msft_activision_complaint",
                    "title": "FTC Complaint Microsoft Activision",
                    "pdf_url": "https://www.ftc.gov/pdf/D09412Complaint.pdf",
                    "doc_type": "complaint",
                },
                {
                    "doc_id": "ftc_msft_activision_alj_decision",
                    "title": "FTC ALJ Initial Decision: Microsoft / Activision Blizzard",
                    "pdf_url": "https://www.ftc.gov/pdf/d09412initialdecision.pdf",
                    "doc_type": "alj_decision",
                },
            ],
            "source_passages": [
                {
                    "passage_id": "sp_1",
                    "source_document_id": "ftc_msft_activision_alj_decision",
                    "quote_snippet": "The relevant product market is high-performance gaming.",
                    "extraction_method": "manually_added",
                    "review_status": "spot_checked",
                    "confidence_score": 0.87,
                    "last_checked_date": "2025-01-01",
                },
            ],
        }

    def _fetch_side_effect(self, url: str, **kwargs) -> MagicMock:
        resp = MagicMock()
        if "initialdecision" in url:
            resp.status_code = 404
            resp.headers = {"content-type": "text/html"}
            resp.content = b""
            resp.url = url
        else:
            resp.status_code = 200
            resp.headers = {"content-type": "application/pdf"}
            resp.content = b"%PDF-1.4 placeholder"
            resp.url = url
        return resp

    def test_fake_alj_decision_raises_errors(self):
        record = self._record_with_alj_fake()
        mock_client = MagicMock()
        mock_client.get.side_effect = self._fetch_side_effect

        with patch("check_source_integrity.fetch") as mock_fetch:
            def fake_fetch(client, url, timeout):
                if "initialdecision" in url:
                    return FetchResult(False, 404, "text/html", url, None, None)
                return FetchResult(True, 200, "application/pdf", url,
                                   b"%PDF-1.4 placeholder", None)
            mock_fetch.side_effect = fake_fetch
            issues = check_record(mock_client, record, timeout=5)

        errors = [i for i in issues if i.level == Level.ERROR]
        # Expect: broken link ERROR for alj_decision doc
        assert any("ftc_msft_activision_alj_decision" in i.scope for i in errors), (
            "Should raise ERROR for the broken ALJ decision source document"
        )
        # Expect: passage sp_1 references a broken doc → still has issue
        # (passage check skips quote check but doc reference itself is broken)
        assert len(errors) >= 1

    def test_clean_record_no_errors(self):
        record = {
            "case_id": "clean_case",
            "source_documents": [
                {
                    "doc_id": "real_doc",
                    "title": "Court Decision JetBlue Spirit",
                    "pdf_url": "https://example.com/decision_jetblue_spirit.pdf",
                    "doc_type": "court_opinion",
                }
            ],
            "source_passages": [
                {
                    "passage_id": "sp_1",
                    "source_document_id": "real_doc",
                    "quote_snippet": "The Court finds the relevant market is city-pair routes.",
                    "extraction_method": "manually_added",
                    "review_status": "spot_checked",
                    "confidence_score": 0.93,
                    "last_checked_date": "2025-01-01",
                }
            ],
        }
        quote_text = "The Court finds the relevant market is city-pair routes."
        with patch("check_source_integrity.fetch") as mock_fetch:
            mock_fetch.return_value = FetchResult(
                True, 200, "text/html",
                "https://example.com/decision_jetblue_spirit.pdf",
                f"<html><body>{quote_text}</body></html>".encode(),
                None,
            )
            mock_client = MagicMock()
            issues = check_record(mock_client, record, timeout=5)

        errors = [i for i in issues if i.level == Level.ERROR]
        assert not errors, f"Unexpected errors: {errors}"

    def test_dangling_passage_reference(self):
        record = {
            "case_id": "case_x",
            "source_documents": [
                {"doc_id": "doc_a", "title": "Complaint",
                 "pdf_url": "https://example.com/complaint.pdf", "doc_type": "complaint"},
            ],
            "source_passages": [
                {"passage_id": "sp_1", "source_document_id": "doc_DOES_NOT_EXIST",
                 "quote_snippet": "Some quote here in the document text."},
            ],
        }
        with patch("check_source_integrity.fetch") as mock_fetch:
            mock_fetch.return_value = FetchResult(
                True, 200, "application/pdf",
                "https://example.com/complaint.pdf", b"%PDF-1.4", None,
            )
            mock_client = MagicMock()
            issues = check_record(mock_client, record, timeout=5)

        errors = [i for i in issues if i.level == Level.ERROR]
        assert any("not found" in i.message for i in errors)

    def test_empty_passages_no_errors(self):
        record = {
            "case_id": "case_y",
            "source_documents": [
                {"doc_id": "doc_a", "title": "FTC Complaint Microsoft",
                 "pdf_url": "https://example.com/complaint_microsoft.pdf",
                 "doc_type": "complaint"},
            ],
            "source_passages": [],
        }
        with patch("check_source_integrity.fetch") as mock_fetch:
            mock_fetch.return_value = FetchResult(
                True, 200, "application/pdf",
                "https://example.com/complaint_microsoft.pdf", b"%PDF-1.4", None,
            )
            mock_client = MagicMock()
            issues = check_record(mock_client, record, timeout=5)

        errors = [i for i in issues if i.level == Level.ERROR]
        assert not errors
