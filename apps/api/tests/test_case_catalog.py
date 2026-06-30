"""Direct tests for the case research catalog policy seam."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CASES_DIR = str(REPO_ROOT / "data" / "cases")
INDEX_DIR = str(REPO_ROOT / "data" / "case_index")


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")

    from app.cases.services.case_catalog import CaseCatalog
    from app.cases.services import case_service, index_case_service
    from app.shared.core import config

    with patch.object(config, "settings", SimpleNamespace(
        data_cases_path=CASES_DIR,
        data_case_index_path=INDEX_DIR,
    )):
        case_service.invalidate_cache()
        index_case_service.invalidate_cache()
        yield CaseCatalog()
        case_service.invalidate_cache()
        index_case_service.invalidate_cache()


def test_list_filters_canonical_records(catalog):
    from app.cases.services.case_catalog import CatalogListQuery

    records = catalog.list(CatalogListQuery(
        scope="canonical",
        jurisdiction="US",
        sector="digital",
        outcome="cleared",
        theory="cloud gaming",
        year_from=2023,
        year_to=2023,
    ))

    assert any(record.case_id == "us_microsoft_activision_2023" for record in records)
    assert all(record.data_layer == "canonical" for record in records)
    assert all(record.jurisdiction == "US" for record in records)
    assert all("digital" in record.sector.lower() for record in records)
    assert all(record.outcome_value == "cleared" for record in records)
    assert all(record.decision_date.year == 2023 for record in records)


def test_list_filters_indexed_records(catalog):
    from app.cases.services.case_catalog import CatalogListQuery

    records = catalog.list(CatalogListQuery(
        scope="indexed",
        jurisdiction="UK",
        sector="media",
        outcome="cleared_with_conditions",
        year_from=2023,
        year_to=2023,
    ))

    assert any(record.case_id == "uk_microsoft_activision_2023" for record in records)
    assert all(record.data_layer == "indexed" for record in records)
    assert all(record.jurisdiction == "UK" for record in records)
    assert all("media" in record.sector.lower() for record in records)
    assert all(record.outcome_value == "cleared_with_conditions" for record in records)
    assert all(record.decision_date.year == 2023 for record in records)


def test_get_prefers_canonical_when_case_id_exists_in_both_layers(catalog):
    default_record = catalog.get("eu_microsoft_activision_2023")
    indexed_record = catalog.get("eu_microsoft_activision_2023", data_layer="indexed")

    assert default_record is not None
    assert default_record.data_layer == "canonical"
    assert default_record.record_status == "canonical_reviewed"
    assert indexed_record is not None
    assert indexed_record.data_layer == "indexed"
    assert indexed_record.record_status == "indexed_metadata"


def test_href_policy_matches_record_layer(catalog):
    canonical = catalog.get("us_microsoft_activision_2023")
    indexed = catalog.get("uk_microsoft_activision_2023", data_layer="indexed")

    assert canonical is not None
    assert indexed is not None
    assert catalog.href_for(canonical) == "/cases/us_microsoft_activision_2023"
    assert catalog.href_for(indexed) == "/indexed-cases/uk_microsoft_activision_2023"


def test_project_hit_adds_status_href_and_quality_counts(catalog):
    canonical = catalog.get("us_microsoft_activision_2023")
    indexed = catalog.get("uk_microsoft_activision_2023", data_layer="indexed")

    assert canonical is not None
    assert indexed is not None
    canonical_hit = catalog.project_hit(canonical)
    indexed_hit = catalog.project_hit(indexed)

    assert canonical_hit.data_layer == "canonical"
    assert canonical_hit.record_status == "canonical_reviewed"
    assert canonical_hit.href == "/cases/us_microsoft_activision_2023"
    assert canonical_hit.product_market_count > 0
    assert canonical_hit.theory_count > 0
    assert canonical_hit.source_passage_count == len(canonical.canonical.source_passages)

    assert indexed_hit.data_layer == "indexed"
    assert indexed_hit.record_status == "indexed_metadata"
    assert indexed_hit.href == "/indexed-cases/uk_microsoft_activision_2023"
    assert indexed_hit.product_market_count == 0
    assert indexed_hit.theory_count == 0
    assert indexed_hit.source_passage_count == 0


def test_search_projects_both_layers_with_href(catalog):
    from app.cases.services.case_catalog import CatalogSearchQuery

    hits = catalog.search(CatalogSearchQuery(q="microsoft", scope="all"))

    assert any(hit.case_id == "us_microsoft_activision_2023" for hit in hits)
    assert any(hit.case_id == "uk_microsoft_activision_2023" for hit in hits)
    assert {hit.data_layer for hit in hits} >= {"canonical", "indexed"}
    assert all(hit.href for hit in hits)
