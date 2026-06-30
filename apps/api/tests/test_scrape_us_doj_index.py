import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cases" / "discovery"))

from app.cases.models.case_index import CaseIndexEntry  # noqa: E402
from scrape_us_doj_index import (  # noqa: E402
    _listing_page_url,
    parse_doj_case_detail,
    parse_doj_listing_page,
    run,
    to_us_scraped_case,
)
from us_discovery_contract import to_case_index_dict  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures" / "us_doj"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_doj_listing_page_filters_to_civil_merger_rows():
    listings = parse_doj_listing_page(_fixture("listing_sample.html"))

    assert len(listings) == 1
    listing = listings[0]
    assert listing.case_title == "U.S. v. Columbus McKinnon Corporation, et al."
    assert listing.case_type == "Civil Merger"
    assert listing.listing_open_date == "2026-01-29"
    assert listing.case_page_url == (
        "https://www.justice.gov/atr/case/"
        "us-v-columbus-mckinnon-corporation-et-al"
    )
    assert listing.industry_labels == (
        "Overhead Traveling Crane, Hoist, and Monorail System Manufacturing",
    )
    assert "Complaint" in listing.document_labels


def test_parse_doj_case_detail_selects_true_disposition_date_not_open_date():
    facts = parse_doj_case_detail(_fixture("detail_sample.html"))

    assert facts.decision_date == "2026-04-27"
    assert facts.selected_label == "Final Judgment"
    assert facts.outcome_guess == "cleared_with_conditions"
    assert facts.decision_date != "2026-01-29"
    assert all("[Proposed]" not in doc.label for doc in facts.documents[:1])


def test_to_us_scraped_case_uses_shared_case_index_contract():
    listing = parse_doj_listing_page(_fixture("listing_sample.html"))[0]
    facts = parse_doj_case_detail(_fixture("detail_sample.html"))

    scraped = to_us_scraped_case(listing, facts)
    record = to_case_index_dict(scraped)
    entry = CaseIndexEntry.model_validate(record)

    assert entry.case_id == "us_doj_columbus_mckinnon_corporation_2026"
    assert entry.case_name == "Columbus McKinnon Corporation"
    assert entry.decision_date.isoformat() == "2026-04-27"
    assert entry.outcome == "cleared_with_conditions"
    assert entry.sector == "manufacturing"
    assert record["parties"] == [
        {"name": "Columbus McKinnon Corporation", "role": "third_party"}
    ]
    assert "pdf_url" not in record
    assert "pdf_language" not in record
    assert "extraction_status" not in record


def test_to_us_scraped_case_requires_true_decision_date():
    listing = parse_doj_listing_page(_fixture("listing_sample.html"))[0]
    facts = parse_doj_case_detail(
        """
        <p><a href="https://www.justice.gov/atr/media/1/dl?inline">
        Proposed Final Judgment</a> (January 29, 2026)</p>
        <p><a href="https://www.justice.gov/atr/media/2/dl?inline">
        Complaint</a> (January 29, 2026)</p>
        """
    )

    assert facts.decision_date is None
    with pytest.raises(ValueError, match="missing_decision_date"):
        to_us_scraped_case(listing, facts)


def test_run_dry_run_builds_record_without_writing(tmp_path, capsys):
    listing_html = _fixture("listing_sample.html")
    detail_html = _fixture("detail_sample.html")
    detail_url = parse_doj_listing_page(listing_html)[0].case_page_url

    def fetch_text(url: str, timeout: float) -> str:
        assert timeout == 20
        if url == _listing_page_url(0):
            return listing_html
        if url == detail_url:
            return detail_html
        raise AssertionError(f"unexpected URL: {url}")

    counts = run(
        output_dir=tmp_path,
        dry_run=True,
        limit=1,
        force=False,
        delay=0,
        timeout=20,
        start_page=0,
        fetch_text=fetch_text,
        sleep_fn=lambda _seconds: None,
    )

    out = capsys.readouterr().out
    assert counts["built"] == 1
    assert counts["dry_run"] == 1
    assert counts["written"] == 0
    assert counts["skipped_non_merger"] == 2
    assert not list(tmp_path.glob("*.yaml"))
    assert "us_doj_columbus_mckinnon_corporation_2026" in out
    assert "decision_date=2026-04-27" in out
    assert "outcome=cleared_with_conditions" in out
    assert detail_url in out
    assert "pdf_url" not in out
    assert "pdf_language" not in out
    assert "extraction_status" not in out


def test_run_reports_missing_decision_date_skip(tmp_path):
    listing_html = _fixture("listing_sample.html")
    detail_url = parse_doj_listing_page(listing_html)[0].case_page_url

    def fetch_text(url: str, _timeout: float) -> str:
        if url == _listing_page_url(0):
            return listing_html
        if url == detail_url:
            return """
            <p><a href="https://www.justice.gov/atr/media/1/dl?inline">
            Proposed Final Judgment</a> (January 29, 2026)</p>
            <p><a href="https://www.justice.gov/atr/media/2/dl?inline">
            Complaint</a> (January 29, 2026)</p>
            """
        raise AssertionError(f"unexpected URL: {url}")

    counts = run(
        output_dir=tmp_path,
        dry_run=True,
        limit=1,
        force=False,
        delay=0,
        timeout=20,
        start_page=0,
        fetch_text=fetch_text,
        sleep_fn=lambda _seconds: None,
    )

    assert counts["built"] == 0
    assert counts["missing_decision_date"] == 1
    assert counts["written"] == 0
