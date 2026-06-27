"""
Tests for ingest_case.py --from-index PDF resolution order.

The resolution order is explicit --pdf-url > index pdf_url > shared resolver
registry. _resolve_from_index_pdf_url isolates that decision so it can be tested
without running the extraction pipeline; the registry call is injected.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cases" / "discovery"))

from pdf_resolvers import PdfCandidate, PdfResolution  # noqa: E402
from scripts.cases.extract.ingest_case import (  # noqa: E402
    _build_scaffold_from_index,
    _resolve_from_index_pdf_url,
)


def _entry(pdf_url=None):
    e = {
        "case_id": "us_test_2022", "case_name": "Test", "jurisdiction": "US",
        "authority": "DOJ", "decision_date": "2022-01-01", "sector": "x",
        "outcome": "blocked", "case_type": "merger",
        "source_url": "https://www.justice.gov/atr/case/x",
    }
    if pdf_url:
        e["pdf_url"] = pdf_url
    return e


def _boom(_entry):
    raise AssertionError("registry must not be consulted when a pdf_url is known")


def test_explicit_pdf_url_wins():
    pdf_url, resolution = _resolve_from_index_pdf_url(
        _entry(pdf_url="https://x/index.pdf"), "https://x/explicit.pdf",
        resolve_fn=_boom)
    assert pdf_url == "https://x/explicit.pdf"
    assert resolution is None  # registry not consulted


def test_index_pdf_url_used_when_no_explicit():
    pdf_url, resolution = _resolve_from_index_pdf_url(
        _entry(pdf_url="https://x/index.pdf"), None, resolve_fn=_boom)
    assert pdf_url == "https://x/index.pdf"
    assert resolution is None


def test_registry_fallback_resolves():
    resolved = PdfResolution.resolved("us_doj_ftc", "https://x/opinion.pdf", "ok")
    pdf_url, resolution = _resolve_from_index_pdf_url(
        _entry(), None, resolve_fn=lambda e: resolved)
    assert pdf_url == "https://x/opinion.pdf"
    assert resolution is resolved


def test_registry_failure_returns_none_and_reason():
    manual = PdfResolution.manual(
        "us_doj_ftc", "multiple_close_merits_docs",
        [PdfCandidate("u", "Opinion", "s", 95, "r")])
    pdf_url, resolution = _resolve_from_index_pdf_url(
        _entry(), None, resolve_fn=lambda e: manual)
    assert pdf_url is None
    assert resolution.status == "manual_required"
    assert resolution.candidates


def test_scaffold_copies_pdf_language_to_source_document():
    entry = _entry(pdf_url="https://x/index.pdf")
    entry["pdf_language"] = "deu"

    scaffold = _build_scaffold_from_index(entry, "https://x/index.pdf")

    assert scaffold["source_documents"][0]["language"] == "deu"
