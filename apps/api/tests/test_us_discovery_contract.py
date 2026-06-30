import pytest
from pathlib import Path

from app.cases.models.case_index import CaseIndexEntry
from case_index_builder import CaseIndexParty
from pdf_resolvers import UsDojFtcResolver
from us_discovery_contract import (
    UsScrapedCase,
    generate_us_case_id,
    to_case_index_dict,
    to_case_index_seed,
)


def _us_record(**overrides):
    values = {
        "authority": "FTC",
        "case_name": "Illumina / GRAIL",
        "parties": (
            CaseIndexParty(name="Illumina", role="acquirer"),
            CaseIndexParty(name="GRAIL", role="target"),
        ),
        "source_url": (
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/"
            "201-0144-illumina-inc-grail-inc-matter"
        ),
        "decision_date": "2023-04-03",
        "outcome_guess": None,
        "sector": "pharma",
    }
    values.update(overrides)
    return UsScrapedCase(**values)


def test_generate_us_case_id_normalizes_authority_name_and_year():
    assert (
        generate_us_case_id("FTC", "Illumina / GRAIL", "2023")
        == "us_ftc_illumina_grail_2023"
    )
    assert (
        generate_us_case_id("DOJ", "JetBlue Airways + Spirit Airlines", "2024")
        == "us_doj_jetblue_spirit_2024"
    )
    assert (
        generate_us_case_id(
            "DOJ",
            "U.S. et al. v. JetBlue Airways Corporation and Spirit Airlines, Inc.",
            "2024",
        )
        == "us_doj_jetblue_spirit_2024"
    )
    assert (
        generate_us_case_id(
            "FTC",
            "Illumina, Inc., and GRAIL, Inc., In the Matter of",
            "2023",
        )
        == "us_ftc_illumina_grail_2023"
    )
    assert (
        generate_us_case_id("DOJ", "AT&T Inc. / Time Warner Inc.", "2018")
        == "us_doj_att_timewarner_2018"
    )


def test_to_case_index_seed_maps_us_defaults():
    seed = to_case_index_seed(_us_record())

    assert seed.case_id == "us_ftc_illumina_grail_2023"
    assert seed.jurisdiction == "US"
    assert seed.authority == "FTC"
    assert seed.outcome == "pending"
    assert seed.parties == (
        CaseIndexParty(name="Illumina", role="acquirer"),
        CaseIndexParty(name="GRAIL", role="target"),
    )


def test_to_case_index_seed_requires_decision_date():
    with pytest.raises(ValueError, match="decision_date"):
        to_case_index_seed(_us_record(decision_date=None))


def test_to_case_index_dict_validates_and_hands_off_to_us_resolver():
    record = to_case_index_dict(_us_record(outcome_guess="cleared_with_conditions"))
    entry = CaseIndexEntry.model_validate(record)

    assert record["case_id"] == "us_ftc_illumina_grail_2023"
    assert record["outcome"] == "cleared_with_conditions"
    assert "pdf_url" not in record
    assert "pdf_language" not in record
    assert "extraction_status" not in record
    assert UsDojFtcResolver(fetcher=object()).can_handle(entry) is True


def test_us_listing_fixtures_are_inert_html_samples():
    fixture_root = Path(__file__).parent / "fixtures"

    doj_html = (fixture_root / "us_doj" / "listing_sample.html").read_text()
    ftc_html = (fixture_root / "us_ftc" / "listing_sample.html").read_text()

    assert "data-authority=\"DOJ\"" in doj_html
    assert "data-authority=\"FTC\"" in ftc_html
    assert "httpx" not in doj_html
    assert "requests" not in ftc_html
