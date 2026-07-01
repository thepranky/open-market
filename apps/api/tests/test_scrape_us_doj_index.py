import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cases" / "discovery"))

from app.cases.models.case_index import CaseIndexEntry  # noqa: E402
from case_index_builder import CaseIndexParty  # noqa: E402
from scrape_us_doj_index import (  # noqa: E402
    DojListingCase,
    _listing_page_url,
    _parse_parties,
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


def test_parse_doj_case_detail_accepts_consent_decree_disposition():
    facts = parse_doj_case_detail(
        """
        <p><a href="https://www.justice.gov/atr/media/1/dl?inline">
        Consent Decree</a> (June 15, 2023)</p>
        <p><a href="https://www.justice.gov/atr/media/2/dl?inline">
        Complaint</a> (January 10, 2023)</p>
        """
    )

    assert facts.decision_date == "2023-06-15"
    assert facts.selected_label == "Consent Decree"
    assert facts.outcome_guess == "cleared_with_conditions"


def test_parse_doj_case_detail_maps_blocked_opinion_outcome():
    facts = parse_doj_case_detail(
        """
        <p><a href="https://www.justice.gov/atr/media/1/dl?inline">
        Memorandum Opinion</a> (March 5, 2024)</p>
        <p>The court entered a permanent injunction blocking the merger.</p>
        """
    )

    assert facts.decision_date == "2024-03-05"
    assert facts.outcome_guess == "blocked"


def test_parse_doj_case_detail_leaves_ambiguous_outcome_pending():
    facts = parse_doj_case_detail(
        """
        <p><a href="https://www.justice.gov/atr/media/1/dl?inline">
        Memorandum Opinion</a> (March 5, 2024)</p>
        <p>Background and procedural history only.</p>
        """
    )

    assert facts.decision_date == "2024-03-05"
    assert facts.outcome_guess is None

    listing = DojListingCase(
        case_title="U.S. v. Example Corp., et al.",
        case_page_url="https://www.justice.gov/atr/case/us-v-example-corp-et-al",
        listing_open_date="2024-01-01",
        case_type="Civil Merger",
        industry_labels=(),
        document_labels=(),
    )
    record = to_case_index_dict(to_us_scraped_case(listing, facts))
    assert record["outcome"] == "pending"


def test_parse_parties_splits_clear_two_party_captions():
    parties = _parse_parties(
        "U.S. v. JetBlue Airways Corporation and Spirit Airlines, Inc."
    )

    assert parties == (
        CaseIndexParty(name="JetBlue Airways Corporation", role="acquirer"),
        CaseIndexParty(name="Spirit Airlines, Inc", role="target"),
    )


def _run_fixture_once(tmp_path, *, force: bool, existing_case_id: str | None = None):
    listing_html = _fixture("listing_sample.html")
    detail_html = _fixture("detail_sample.html")
    detail_url = parse_doj_listing_page(listing_html)[0].case_page_url
    case_id = "us_doj_columbus_mckinnon_corporation_2026"
    if existing_case_id is not None:
        (tmp_path / f"{existing_case_id}.yaml").write_text(
            "case_id: placeholder\n", encoding="utf-8"
        )

    def fetch_text(url: str, _timeout: float) -> str:
        if url == _listing_page_url(0):
            return listing_html
        if url == detail_url:
            return detail_html
        raise AssertionError(f"unexpected URL: {url}")

    return run(
        output_dir=tmp_path,
        dry_run=False,
        limit=1,
        force=force,
        delay=0,
        timeout=20,
        start_page=0,
        fetch_text=fetch_text,
        sleep_fn=lambda _seconds: None,
    ), case_id


def test_run_skips_existing_output_without_force(tmp_path):
    counts, case_id = _run_fixture_once(
        tmp_path, force=False, existing_case_id="us_doj_columbus_mckinnon_corporation_2026"
    )

    assert counts["skipped_existing"] == 1
    assert counts["written"] == 0
    assert (tmp_path / f"{case_id}.yaml").read_text(encoding="utf-8") == "case_id: placeholder\n"


def test_run_overwrites_existing_output_with_force(tmp_path):
    counts, case_id = _run_fixture_once(
        tmp_path, force=True, existing_case_id="us_doj_columbus_mckinnon_corporation_2026"
    )

    assert counts["written"] == 1
    assert counts["skipped_existing"] == 0
    written = (tmp_path / f"{case_id}.yaml").read_text(encoding="utf-8")
    assert "case_id: placeholder" not in written
    assert "us_doj_columbus_mckinnon_corporation_2026" in written
