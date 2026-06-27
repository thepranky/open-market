"""
Tests for pdf_resolvers.py — the shared PDF-resolution contract and the EU / UK /
US authority adapters.

HTTP is injected through a fake Fetcher, so every test runs with no network.
Cover CELEX derivation + Phase II handling (EU), report ranking / disqualification
/ lone-survivor fallback (UK), conservative merits ranking (US), and the resolver
status semantics shared across all three.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cases" / "discovery"))

from pdf_resolvers import (  # noqa: E402
    EuCellarResolver,
    HeadResult,
    PdfResolution,
    UkGovUkResolver,
    UsDojFtcResolver,
    resolve_pdf_url,
    select_resolver,
)


@dataclass
class _Entry:
    """Minimal structural stand-in for CaseIndexEntry (adapters read 5 attrs)."""
    jurisdiction: str = "EU"
    authority: str = ""
    outcome: str = "cleared"
    source_url: Optional[str] = "https://competition-cases.ec.europa.eu/cases/M.10852"
    decision_date: str = "2022-10-12"


class _FakeFetcher:
    """Returns canned HEAD results / page text keyed by url; raises if asked for an unset url."""

    def __init__(self, *, heads=None, pages=None, raise_on=None):
        self._heads = heads or {}
        self._pages = pages or {}
        self._raise_on = raise_on

    def head(self, url, *, timeout):
        if self._raise_on == "head":
            raise ConnectionError("boom")
        # An unset URL behaves like a real 404 (the manifestation doesn't exist).
        return self._heads.get(url, HeadResult(404, "", url))

    def get_text(self, url, *, timeout):
        if self._raise_on == "get":
            raise ConnectionError("boom")
        return self._pages.get(url, "")


# --------------------------------------------------------------------------- EU

_CELLAR = "http://publications.europa.eu/resource/celex/32022M10852.ENG.pdf"


def test_eu_resolves_phase1_via_cellar():
    fetcher = _FakeFetcher(heads={_CELLAR: HeadResult(200, "application/pdf", _CELLAR)})
    res = EuCellarResolver(fetcher).resolve(_Entry(), timeout=5)
    assert res.status == "resolved"
    assert res.pdf_url == _CELLAR
    assert "32022M10852" in res.reason


def test_eu_phase2_outcome_is_manual_without_fetch():
    # Phase II is not in Cellar — must return manual_required and never hit HTTP.
    fetcher = _FakeFetcher(raise_on="head")
    res = EuCellarResolver(fetcher).resolve(
        _Entry(outcome="cleared_with_conditions"), timeout=5)
    assert res.status == "manual_required"
    assert res.reason == "phase_ii_not_in_cellar"


@pytest.mark.parametrize("outcome",
                         ["cleared_with_conditions", "blocked", "annulled",
                          "partially_annulled", "under_appeal"])
def test_eu_all_manual_outcomes_skip_cellar(outcome):
    # Every outcome not published in Cellar must return manual_required, no HTTP.
    res = EuCellarResolver(_FakeFetcher(raise_on="head")).resolve(
        _Entry(outcome=outcome), timeout=5)
    assert res.status == "manual_required"


def test_eu_no_case_number_is_not_found():
    res = EuCellarResolver(_FakeFetcher()).resolve(
        _Entry(source_url="https://competition-cases.ec.europa.eu/cases/foo"), timeout=5)
    assert res.status == "not_found"
    assert res.reason == "no_case_number_in_source_url"


def test_eu_cellar_miss_is_not_found():
    fetcher = _FakeFetcher(heads={_CELLAR: HeadResult(404, "text/html", _CELLAR)})
    res = EuCellarResolver(fetcher).resolve(_Entry(), timeout=5)
    assert res.status == "not_found"


def _cellar(lang):
    return f"http://publications.europa.eu/resource/celex/32022M10852.{lang}.pdf"


def test_eu_falls_back_to_non_english_language():
    # No English manifestation, but a German one exists → resolve to German.
    fetcher = _FakeFetcher(heads={_cellar("DEU"): HeadResult(200, "application/pdf",
                                                             _cellar("DEU"))})
    res = EuCellarResolver(fetcher).resolve(_Entry(), timeout=5)
    assert res.status == "resolved"
    assert res.pdf_url == _cellar("DEU")
    assert res.reason.endswith("_deu")


def test_eu_prefers_english_when_both_exist():
    # English is tried first, so it wins even when other languages also exist.
    fetcher = _FakeFetcher(heads={
        _cellar("ENG"): HeadResult(200, "application/pdf", _cellar("ENG")),
        _cellar("DEU"): HeadResult(200, "application/pdf", _cellar("DEU")),
    })
    res = EuCellarResolver(fetcher).resolve(_Entry(), timeout=5)
    assert res.pdf_url == _cellar("ENG")
    assert res.reason.endswith("_eng")


def test_eu_no_manifestation_in_any_language_is_not_found():
    res = EuCellarResolver(_FakeFetcher()).resolve(_Entry(), timeout=5)
    assert res.status == "not_found"


def test_eu_transport_error_is_error_status():
    res = EuCellarResolver(_FakeFetcher(raise_on="head")).resolve(_Entry(), timeout=5)
    assert res.status == "error"


# --------------------------------------------------------------------------- UK

_UK_URL = "https://www.gov.uk/cma-cases/example"
_HOST = "https://assets.publishing.service.gov.uk/media/abc"


def _uk_page(*filenames):
    links = "".join(f'<a href="{_HOST}/{n}">{n}</a>' for n in filenames)
    return f"<html><body>{links}</body></html>"


def _uk(pages):
    return UkGovUkResolver(_FakeFetcher(pages={_UK_URL: pages}))


def test_uk_ranks_final_report_above_provisional():
    page = _uk_page("provisional_findings_report.pdf", "final_report.pdf",
                    "final_order.pdf")
    res = _uk(page).resolve(_Entry(jurisdiction="UK", outcome="blocked",
                                   source_url=_UK_URL), timeout=5)
    assert res.status == "resolved"
    assert res.pdf_url.endswith("final_report.pdf")


def test_uk_disqualifies_orders_and_undertakings():
    page = _uk_page("final_order.pdf", "interim_undertaking.pdf", "appendix_a.pdf")
    res = _uk(page).resolve(_Entry(jurisdiction="UK", outcome="blocked",
                                   source_url=_UK_URL), timeout=5)
    # All disqualified, none survive uniquely → manual_required.
    assert res.status == "manual_required"


def test_uk_lone_surviving_pdf_is_resolved():
    # A single non-disqualified PDF that matches no report pattern is the decision.
    page = _uk_page("Acteon_Viking.pdf", "final_order.pdf")
    res = _uk(page).resolve(_Entry(jurisdiction="UK", outcome="blocked",
                                   source_url=_UK_URL), timeout=5)
    assert res.status == "resolved"
    assert res.pdf_url.endswith("Acteon_Viking.pdf")
    assert res.reason == "lone_surviving_pdf"


def test_uk_no_pdf_links_is_not_found():
    res = _uk("<html>no pdfs here</html>").resolve(
        _Entry(jurisdiction="UK", outcome="blocked", source_url=_UK_URL), timeout=5)
    assert res.status == "not_found"


def test_uk_ignores_non_asset_host_pdfs():
    page = '<a href="https://example.com/final_report.pdf">report</a>'
    res = _uk(page).resolve(_Entry(jurisdiction="UK", outcome="blocked",
                                   source_url=_UK_URL), timeout=5)
    assert res.status == "not_found"


# --------------------------------------------------------------------------- US

_US_URL = "https://www.justice.gov/atr/case/example"


def _us_page(*pairs):
    links = "".join(f'<a href="https://x/doc{i}.pdf">{text}</a>'
                    for i, text in enumerate(pairs))
    return f"<html><body>{links}</body></html>"


def _us(page):
    return UsDojFtcResolver(_FakeFetcher(pages={_US_URL: page}))


def _us_entry():
    return _Entry(jurisdiction="US", authority="DOJ", outcome="blocked",
                  source_url=_US_URL)


def test_us_single_merits_doc_resolves():
    page = _us_page("Memorandum Opinion", "Complaint", "Press Release")
    res = _us(page).resolve(_us_entry(), timeout=5)
    assert res.status == "resolved"
    assert res.reason == "single_merits_doc"


def test_us_only_complaints_is_manual():
    page = _us_page("Complaint", "Proposed Final Judgment", "Competitive Impact Statement")
    res = _us(page).resolve(_us_entry(), timeout=5)
    assert res.status == "manual_required"
    assert res.reason == "no_merits_match"


def test_us_multiple_close_merits_is_manual():
    # Two opinions of equal score — too close to pick → manual_required, listed.
    page = _us_page("Opinion", "Findings of Fact")
    res = _us(page).resolve(_us_entry(), timeout=5)
    assert res.status == "manual_required"
    assert res.reason == "multiple_close_merits_docs"
    assert len(res.candidates) == 2


def test_us_pdf_url_with_query_string_is_extracted():
    # Asset URLs sometimes carry a ?query / #fragment — must still be seen.
    page = ('<a href="https://x/415418.pdf?download=1">Memorandum Opinion</a>'
            '<a href="https://x/complaint.pdf">Complaint</a>')
    res = UsDojFtcResolver(_FakeFetcher(pages={_US_URL: page})).resolve(
        _us_entry(), timeout=5)
    assert res.status == "resolved"
    assert res.pdf_url == "https://x/415418.pdf?download=1"


def test_us_clear_winner_among_multiple_resolves():
    # Memorandum opinion (100) clearly beats decision-and-order (90) by >=10.
    page = _us_page("Memorandum Opinion", "Decision and Order")
    res = _us(page).resolve(_us_entry(), timeout=5)
    assert res.status == "resolved"
    assert res.reason == "top_merits_doc"


# ----------------------------------------------------------------- registry

def test_select_resolver_routes_by_jurisdiction():
    resolvers = [EuCellarResolver(_FakeFetcher()),
                 UkGovUkResolver(_FakeFetcher()),
                 UsDojFtcResolver(_FakeFetcher())]
    assert select_resolver(_Entry(jurisdiction="UK"), resolvers).name == "uk_govuk"
    assert select_resolver(_Entry(jurisdiction="US"), resolvers).name == "us_doj_ftc"


def test_resolve_pdf_url_unknown_jurisdiction_is_error():
    res = resolve_pdf_url(_Entry(jurisdiction="ZZ"), resolvers=[])
    assert res.status == "error"
    assert isinstance(res, PdfResolution)
