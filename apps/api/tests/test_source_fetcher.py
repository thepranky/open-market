"""Tests for jurisdiction source fetcher."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.screening.models.jurisdiction_verification import FetchStatus
from app.screening.services.source_fetcher import (
    bytes_to_text,
    cache_key_for_url,
    fetch_source,
    html_to_text,
    normalize_text,
    quote_in_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "jurisdiction_sources"


def test_normalize_text_collapses_whitespace():
    assert normalize_text("EUR   5 000\r\nmillion") == "EUR 5 000 million"


def test_html_fixture_extracts_eu_article_text():
    html = (FIXTURES / "eu_article_1_2.html").read_text()
    text = html_to_text(html)
    assert "EUR 5 000 million" in text
    assert quote_in_text("more than EUR 5 000 million", text)


def test_html_fixture_extracts_uk_section_text():
    html = (FIXTURES / "uk_section_23.html").read_text()
    text = html_to_text(html)
    assert "£70 million" in text
    assert quote_in_text("exceeds £70 million", text)


def test_us_hsr_statute_fixture_quote_match():
    text = normalize_text((FIXTURES / "us_hsr_18a.txt").read_text())
    assert quote_in_text(
        "no person shall acquire, directly or indirectly, any voting securities or assets",
        text,
    )


def test_quote_in_text_fuzzy_match():
    quote = "combined aggregate worldwide turnover of all the undertakings concerned is more than EUR 5 000 million"
    target = "the combined aggregate worldwide turnover of all the undertakings concerned is more than EUR 5,000 million"
    assert quote_in_text(quote, target)


def test_quote_in_text_fuzzy_match_in_long_document():
    # Demonstrates the sliding-window approach: the old Jaccard-on-full-document
    # would yield near-zero similarity here because the denominator grows with
    # document length, making 0.95 unreachable.
    quote = "the aggregate Community-wide turnover of each at least two undertakings is more than EUR 250 million"
    noise = "Article defines concentration dimensions relevant markets and turnover thresholds. " * 30
    document = (
        noise
        + "the aggregate Community-wide turnover of each of at least two of the undertakings concerned is more than EUR 250 million"
        + noise
    )
    assert quote_in_text(quote, document)


def test_quote_not_in_unrelated_text():
    assert not quote_in_text("turnover exceeds EUR 5000 million", "The weather is fine today.")


def test_fetch_source_html_ok():
    html = (FIXTURES / "uk_section_23.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = fetch_source("https://example.test/uk/s23", client=client)

    assert result.fetch_status == FetchStatus.ok
    assert "£70 million" in result.text


def test_fetch_source_bot_protected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = fetch_source("https://example.test/forbidden", client=client)

    assert result.fetch_status == FetchStatus.bot_protected
    assert not result.text


def test_fetch_source_400_is_broken_not_bot_protected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = fetch_source("https://example.test/bad", client=client)

    assert result.fetch_status == FetchStatus.broken
    assert "400" in result.error


def test_fetch_source_broken_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = fetch_source("https://example.test/missing", client=client)

    assert result.fetch_status == FetchStatus.broken
    assert not result.ok


def test_fetch_source_ssl_uncertain():
    class _SSLErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.RequestError(
                "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate",
                request=request,
            )

    with httpx.Client(transport=_SSLErrorTransport()) as client:
        result = fetch_source("https://example.test/secure", client=client)

    assert result.fetch_status == FetchStatus.ssl_uncertain
    assert not result.text


def test_bytes_to_text_plain_html():
    html_bytes = b"<html><body><p>hello world</p></body></html>"
    result = bytes_to_text(html_bytes, "text/plain")
    assert result is not None
    assert "hello world" in result


def test_bytes_to_text_pdf_magic_overrides_text_content_type():
    # A server serving a PDF with Content-Type: text/plain should still be
    # routed to the PDF extractor, not html_to_text.
    pdf_bytes = b"%PDF-1.4 fake"
    result = bytes_to_text(pdf_bytes, "text/plain")
    # pdf_bytes_to_text returns "" for an invalid PDF, not None — key point is
    # we don't try to HTML-parse raw PDF bytes.
    assert result is not None
    assert "<" not in (result or "")


def test_cache_key_for_url():
    key = cache_key_for_url("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32004R0139")
    assert "/" not in key
    assert "?" not in key
    assert len(key) <= 120
    assert key  # non-empty


def test_cache_key_for_url_is_stable():
    url = "https://legislation.gov.uk/ukpga/2002/40/section/23"
    assert cache_key_for_url(url) == cache_key_for_url(url)
