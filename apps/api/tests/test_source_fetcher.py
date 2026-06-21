"""Tests for jurisdiction source fetcher."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.services.source_fetcher import (
    fetch_source,
    html_to_text,
    normalize_text,
    quote_in_text,
)
from app.models.jurisdiction_verification import FetchStatus

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


def test_us_notice_fixture_quote_match():
    text = normalize_text((FIXTURES / "us_hsr_notice.txt").read_text())
    assert quote_in_text("greater than $119.5 million", text)
    assert quote_in_text("adjusted annually", text)


def test_quote_in_text_fuzzy_match():
    quote = "combined aggregate worldwide turnover of all the undertakings concerned is more than EUR 5 000 million"
    target = "the combined aggregate worldwide turnover of all the undertakings concerned is more than EUR 5,000 million"
    assert quote_in_text(quote, target)


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
