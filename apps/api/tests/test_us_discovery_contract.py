import re
from pathlib import Path

import pytest
import yaml

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


def _href_from_fixture(relative_path: str) -> str:
    html = (Path(__file__).parent / "fixtures" / relative_path).read_text()
    match = re.search(r'href="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_generate_us_case_id_from_fixture_urls():
    doj_href = _href_from_fixture("us_doj/listing_sample.html")
    ftc_href = _href_from_fixture("us_ftc/listing_sample.html")

    assert (
        generate_us_case_id("DOJ", doj_href, "2026")
        == "us_doj_cal_maine_foods_inc_2026"
    )
    assert generate_us_case_id("FTC", ftc_href, "2023") == "us_ftc_201_0144_2023"


def test_generate_us_case_id_accepts_absolute_doj_urls():
    assert (
        generate_us_case_id(
            "DOJ",
            (
                "https://www.justice.gov/atr/case/"
                "us-v-att-inc-directv-group-holdings-llc-and-time-warner-inc"
            ),
            "2018",
        )
        == "us_doj_att_inc_directv_group_holdings_llc_and_time_warner_inc_2018"
    )


def test_generate_us_case_id_parses_concatenated_ftc_matter_numbers():
    assert (
        generate_us_case_id(
            "FTC",
            (
                "https://www.ftc.gov/legal-library/browse/cases-proceedings/"
                "2210077-microsoftactivision-blizzard-matter"
            ),
            "2023",
        )
        == "us_ftc_221_0077_2023"
    )


def test_generate_us_case_id_ftc_fallback_when_matter_number_missing():
    assert (
        generate_us_case_id(
            "FTC",
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/custom-slug",
            "2024",
        )
        == "us_ftc_custom_slug_2024"
    )


@pytest.mark.parametrize(
    ("authority", "source_url", "year", "expected"),
    [
        (
            "DOJ",
            "https://www.justice.gov/atr/case/us-and-plaintiff-states-v-aetna-inc-and-humana-inc",
            "2017",
            "us_doj_aetna_inc_and_humana_inc_2017",
        ),
        (
            "DOJ",
            (
                "https://www.justice.gov/atr/case/"
                "us-and-plaintiff-states-v-american-airlines-group-inc-and-jetblue-airways-corporation"
            ),
            "2023",
            "us_doj_american_airlines_group_inc_and_jetblue_airways_corpora_2023",
        ),
        (
            "DOJ",
            "https://www.justice.gov/atr/case/us-v-bertelsmann-se-co-kgaa-et-al",
            "2022",
            "us_doj_bertelsmann_se_co_kgaa_2022",
        ),
        (
            "DOJ",
            "https://www.justice.gov/atr/case/us-v-sabre-corp-et-al",
            "2020",
            "us_doj_sabre_corp_2020",
        ),
        (
            "FTC",
            (
                "https://www.ftc.gov/legal-library/browse/cases-proceedings/"
                "221-0040-meta-platforms-incmark-zuckerbergwithin-unlimited-ftc-v"
            ),
            "2023",
            "us_ftc_221_0040_2023",
        ),
    ],
)
def test_generate_us_case_id_seed_source_urls(authority, source_url, year, expected):
    assert generate_us_case_id(authority, source_url, year) == expected


def test_seed_yaml_case_ids_match_source_urls():
    root = Path(__file__).resolve().parents[2] / "data" / "case_index" / "us"
    for path in sorted(root.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        year = str(entry["decision_date"])[:4]
        expected = generate_us_case_id(entry["authority"], entry["source_url"], year)
        assert entry["case_id"] == expected, (path.name, entry["case_id"], expected)
        assert path.stem == entry["case_id"], (path.name, entry["case_id"])


def test_to_case_index_seed_maps_us_defaults():
    seed = to_case_index_seed(_us_record())

    assert seed.case_id == "us_ftc_201_0144_2023"
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

    assert record["case_id"] == "us_ftc_201_0144_2023"
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
