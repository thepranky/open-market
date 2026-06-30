from app.cases.models.case_index import CaseIndexEntry
from scrape_eu_index import EuScrapedCase, build_yaml, make_case_id, to_case_index_seed


def test_eu_scraped_case_converts_through_shared_case_index_builder():
    scraped = EuScrapedCase(
        case_number="11141",
        decision_celex="32023M11141",
        decision_date="2023-09-14",
        outcome="cleared",
        nace_codes=["J62.01"],
        case_name="WENDEL / TOPSCALE",
        parties=["WENDEL", "TOPSCALE"],
    )

    case_id = make_case_id(scraped)
    seed = to_case_index_seed(scraped, case_id)
    record = build_yaml(scraped, case_id)

    assert case_id == "eu_wendel_topscale_2023"
    assert seed.jurisdiction == "EU"
    assert seed.authority == "European Commission"
    assert seed.sector == "tech"
    assert record["source_url"] == "https://competition-cases.ec.europa.eu/cases/M.11141"
    assert record["parties"] == [
        {"name": "WENDEL", "role": "acquirer"},
        {"name": "TOPSCALE", "role": "target"},
    ]
    assert "pdf_url" not in record
    assert "pdf_language" not in record
    assert "extraction_status" not in record
    CaseIndexEntry.model_validate(record)


def test_eu_scraped_case_uses_case_number_fallback_when_name_missing():
    scraped = EuScrapedCase(
        case_number="10999",
        decision_celex="32022M10999",
        decision_date="2022-12-01",
        outcome="cleared",
        nace_codes=[],
    )

    record = build_yaml(scraped, "eu_ec_m10999_2022")

    assert record["case_name"] == "M.10999"
    assert record["sector"] == "other"
    assert record["parties"] == []
