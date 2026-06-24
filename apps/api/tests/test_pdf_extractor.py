"""
Unit tests for app/utils/pdf_extractor.py

PDF download calls are mocked — no network access required.
A minimal real PDF is built with pypdf so pdfplumber can extract from it.
"""
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.shared.utils.pdf_extractor import (
    DEFAULT_CACHE_DIR,
    extract_pages,
    fetch_and_extract,
    get_page_text,
    iter_pages,
    load_cache,
    save_cache,
)


# ---------------------------------------------------------------------------
# Helpers — build a minimal PDF fixture with known text per page
# ---------------------------------------------------------------------------

def _make_pdf_bytes(pages_text: list[str]) -> bytes:
    """
    Build a minimal multi-page PDF with the given text on each page.

    Uses pypdf's PdfWriter + a canvas approach.  Falls back to a raw
    PDF stub when neither reportlab nor fpdf is available, so tests that
    exercise pdfplumber extraction are skipped if the text is not readable.
    """
    try:
        import reportlab.pdfgen.canvas as rlcanvas
        buf = io.BytesIO()
        c = rlcanvas.Canvas(buf)
        for text in pages_text:
            c.drawString(72, 720, text)
            c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        pass

    try:
        from fpdf import FPDF
        pdf = FPDF()
        for text in pages_text:
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(200, 10, txt=text)
        return pdf.output(dest="S").encode("latin-1")
    except ImportError:
        pass

    # Minimal raw PDF (single page, no real text layer) — used only to test
    # cache I/O; extraction tests are skipped when this path is taken.
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" \
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" \
           b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n" \
           b"xref\n0 4\n0000000000 65535 f\n" \
           b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"


# ---------------------------------------------------------------------------
# extract_pages
# ---------------------------------------------------------------------------

class TestExtractPages:
    def test_returns_list_of_page_dicts(self):
        """extract_pages must return a list of {page_number, text} dicts."""
        pdf_bytes = _make_pdf_bytes(["Page one text.", "Page two text."])
        pages = extract_pages(pdf_bytes)
        assert isinstance(pages, list)
        assert len(pages) >= 1  # at least one page
        for p in pages:
            assert "page_number" in p
            assert "text" in p
            assert isinstance(p["page_number"], int)
            assert isinstance(p["text"], str)

    def test_page_numbers_are_one_indexed(self):
        pdf_bytes = _make_pdf_bytes(["First page.", "Second page."])
        pages = extract_pages(pdf_bytes)
        page_nums = [p["page_number"] for p in pages]
        assert page_nums[0] == 1

    def test_text_extraction_with_pdfplumber(self):
        try:
            import pdfplumber
            import reportlab.pdfgen.canvas as _
        except ImportError:
            pytest.skip("pdfplumber + reportlab not available")

        pdf_bytes = _make_pdf_bytes(["The Court finds market X relevant."])
        pages = extract_pages(pdf_bytes)
        full_text = " ".join(p["text"] for p in pages)
        # Check that some meaningful text was extracted
        assert len(full_text) > 5


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

class TestCacheIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        data = {
            "source_document_id": "test_doc",
            "source_url": "https://example.com/test.pdf",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "text": "Page one content here."},
                {"page_number": 2, "text": "Page two content here."},
            ],
            "extracted_at": "2026-05-23T12:00:00+00:00",
        }
        path = save_cache(data, cache_dir=tmp_path)
        assert path.exists()
        loaded = load_cache("test_doc", cache_dir=tmp_path)
        assert loaded is not None
        assert loaded["source_document_id"] == "test_doc"
        assert loaded["page_count"] == 2
        assert loaded["pages"][0]["text"] == "Page one content here."

    def test_load_cache_returns_none_when_missing(self, tmp_path):
        result = load_cache("nonexistent_doc", cache_dir=tmp_path)
        assert result is None

    def test_save_creates_dir_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b"
        data = {
            "source_document_id": "doc_x",
            "source_url": "https://example.com/x.pdf",
            "page_count": 0,
            "pages": [],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }
        save_cache(data, cache_dir=nested)
        assert (nested / "doc_x.json").exists()


# ---------------------------------------------------------------------------
# get_page_text
# ---------------------------------------------------------------------------

class TestGetPageText:
    def _cache(self) -> dict:
        return {
            "source_document_id": "doc1",
            "pages": [
                {"page_number": 1, "text": "First page text."},
                {"page_number": 2, "text": "Second page text."},
                {"page_number": 3, "text": "Third page text."},
            ],
        }

    def test_returns_text_for_existing_page(self):
        assert get_page_text(self._cache(), 2) == "Second page text."

    def test_returns_none_for_missing_page(self):
        assert get_page_text(self._cache(), 99) is None

    def test_page_one_indexed(self):
        assert get_page_text(self._cache(), 1) == "First page text."


# ---------------------------------------------------------------------------
# iter_pages
# ---------------------------------------------------------------------------

class TestIterPages:
    def test_yields_page_number_and_text(self):
        cache = {
            "pages": [
                {"page_number": 1, "text": "Alpha"},
                {"page_number": 2, "text": "Beta"},
            ]
        }
        pairs = list(iter_pages(cache))
        assert pairs == [(1, "Alpha"), (2, "Beta")]

    def test_empty_cache(self):
        assert list(iter_pages({})) == []


# ---------------------------------------------------------------------------
# fetch_and_extract — mocked network
# ---------------------------------------------------------------------------

class TestFetchAndExtract:
    def _mock_pdf_response(self, pages_text: list[str]) -> MagicMock:
        pdf_bytes = _make_pdf_bytes(pages_text)
        resp = MagicMock()
        resp.content = pdf_bytes
        resp.raise_for_status = MagicMock()
        return resp

    def test_builds_cache_when_missing(self, tmp_path):
        mock_client = MagicMock()
        mock_client.get.return_value = self._mock_pdf_response(["Page one.", "Page two."])

        result = fetch_and_extract(
            "my_doc", "https://example.com/my.pdf",
            cache_dir=tmp_path, client=mock_client,
        )
        assert result["source_document_id"] == "my_doc"
        assert result["page_count"] >= 1
        # Cache file written
        assert (tmp_path / "my_doc.json").exists()

    def test_reads_from_cache_without_download(self, tmp_path):
        # Pre-populate cache
        data = {
            "source_document_id": "cached_doc",
            "source_url": "https://example.com/cached.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "Cached content."}],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }
        save_cache(data, cache_dir=tmp_path)

        mock_client = MagicMock()
        result = fetch_and_extract(
            "cached_doc", "https://example.com/cached.pdf",
            cache_dir=tmp_path, client=mock_client,
        )
        # Should NOT have called the network
        mock_client.get.assert_not_called()
        assert result["pages"][0]["text"] == "Cached content."

    def test_force_flag_bypasses_cache(self, tmp_path):
        # Pre-populate cache
        old_data = {
            "source_document_id": "force_doc",
            "source_url": "https://example.com/force.pdf",
            "page_count": 0,
            "pages": [],
            "extracted_at": "2020-01-01T00:00:00+00:00",
        }
        save_cache(old_data, cache_dir=tmp_path)

        mock_client = MagicMock()
        mock_client.get.return_value = self._mock_pdf_response(["New page."])

        result = fetch_and_extract(
            "force_doc", "https://example.com/force.pdf",
            cache_dir=tmp_path, client=mock_client, force=True,
        )
        mock_client.get.assert_called_once()
        assert result["page_count"] >= 1
