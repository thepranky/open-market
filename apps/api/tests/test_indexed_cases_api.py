"""Integration tests for /indexed-cases and /search/all endpoints."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CASES_DIR = str(REPO_ROOT / "data" / "cases")
INDEX_DIR = str(REPO_ROOT / "data" / "case_index")


@pytest.fixture
def client():
    with patch("app.shared.core.config.settings") as mock_settings:
        mock_settings.data_cases_path = CASES_DIR
        mock_settings.data_case_index_path = INDEX_DIR
        mock_settings.app_title = "Meridian API"
        mock_settings.app_version = "0.1.0"
        mock_settings.neo4j_uri = "bolt://localhost:7687"
        mock_settings.neo4j_user = "neo4j"
        mock_settings.neo4j_password = "compmap_local"
        mock_settings.debug = False

        from app.cases.services import case_service, index_case_service
        case_service.invalidate_cache()
        index_case_service.invalidate_cache()

        from main import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# GET /indexed-cases
# ---------------------------------------------------------------------------

def test_list_indexed_cases_returns_entries(client):
    r = client.get("/indexed-cases")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_list_indexed_cases_provenance_fields(client):
    r = client.get("/indexed-cases")
    assert r.status_code == 200
    for item in r.json():
        assert item["data_layer"] == "indexed"
        assert item["record_status"] == "indexed_metadata"


def test_list_indexed_cases_no_canonical_fields(client):
    r = client.get("/indexed-cases")
    assert r.status_code == 200
    for item in r.json():
        assert "product_markets_considered" not in item
        assert "geographic_markets_considered" not in item
        assert "theories_of_harm" not in item
        assert "source_passages" not in item
        assert "source_documents" not in item
        assert "commitments" not in item
        assert "metadata" not in item


def test_list_indexed_cases_has_concept_refs(client):
    r = client.get("/indexed-cases")
    assert r.status_code == 200
    cases_with_refs = [c for c in r.json() if c["concept_refs"]]
    assert len(cases_with_refs) >= 1
    ref = cases_with_refs[0]["concept_refs"][0]
    assert "concept_id" in ref
    assert "quality_level" in ref
    assert "provenance" in ref


def test_filter_indexed_by_jurisdiction(client):
    r = client.get("/indexed-cases?jurisdiction=EU")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(c["jurisdiction"] == "EU" for c in data)


def test_filter_indexed_by_outcome(client):
    r = client.get("/indexed-cases?outcome=abandoned")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(c["outcome"] == "abandoned" for c in data)


def test_filter_indexed_by_sector(client):
    r = client.get("/indexed-cases?sector=tech")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1


def test_filter_indexed_no_match_returns_empty(client):
    r = client.get("/indexed-cases?jurisdiction=DE")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /indexed-cases/{case_id}
# ---------------------------------------------------------------------------

def test_indexed_case_detail_eu(client):
    r = client.get("/indexed-cases/eu_illumina_grail_2022")
    assert r.status_code == 200
    data = r.json()
    assert data["case_id"] == "eu_illumina_grail_2022"
    assert data["data_layer"] == "indexed"
    assert data["record_status"] == "indexed_metadata"
    assert data["jurisdiction"] == "EU"
    assert data["outcome"] == "annulled"


def test_indexed_case_detail_uk(client):
    r = client.get("/indexed-cases/uk_adobe_figma_2023")
    assert r.status_code == 200
    data = r.json()
    assert data["outcome"] == "abandoned"
    assert data["data_layer"] == "indexed"


def test_indexed_case_detail_us(client):
    r = client.get("/indexed-cases/us_ftc_microsoft_activision_2023")
    assert r.status_code == 200
    data = r.json()
    assert data["jurisdiction"] == "US"
    assert data["data_layer"] == "indexed"


def test_indexed_case_detail_has_source_url(client):
    r = client.get("/indexed-cases/eu_illumina_grail_2022")
    assert r.status_code == 200
    assert r.json()["source_url"] is not None


def test_indexed_case_detail_concept_refs_carry_quality_provenance(client):
    r = client.get("/indexed-cases/eu_illumina_grail_2022")
    assert r.status_code == 200
    refs = r.json()["concept_refs"]
    assert len(refs) >= 1
    for ref in refs:
        assert ref["quality_level"] in ("indexed", "canonical")
        assert ref["provenance"] in ("manually_tagged", "ai_extracted", "yaml_concept_field")


def test_indexed_case_not_found(client):
    r = client.get("/indexed-cases/nonexistent_xyz_2099")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /search/all
# ---------------------------------------------------------------------------

def test_search_all_returns_both_layers(client):
    # "microsoft" appears in both canonical (eu_microsoft_activision_2023) and indexed cases
    r = client.get("/search/all?q=microsoft")
    assert r.status_code == 200
    hits = r.json()
    layers = {h["data_layer"] for h in hits}
    assert "canonical" in layers
    assert "indexed" in layers


def test_search_all_provenance_fields_always_present(client):
    r = client.get("/search/all?q=microsoft")
    assert r.status_code == 200
    for hit in r.json():
        assert "data_layer" in hit
        assert "record_status" in hit
        assert hit["data_layer"] in ("canonical", "indexed")
        assert hit["record_status"] in ("canonical_reviewed", "indexed_metadata")


def test_search_all_canonical_hits_have_counts(client):
    r = client.get("/search/all?q=microsoft&scope=canonical")
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) >= 1
    for hit in hits:
        assert hit["data_layer"] == "canonical"
        assert hit["record_status"] == "canonical_reviewed"
        # Counts must be present (may be 0 if case has no markets, but key exists)
        assert "product_market_count" in hit
        assert "theory_count" in hit
        assert "source_passage_count" in hit


def test_search_all_indexed_hits_have_zero_counts(client):
    r = client.get("/search/all?q=microsoft&scope=indexed")
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) >= 1
    for hit in hits:
        assert hit["data_layer"] == "indexed"
        assert hit["product_market_count"] == 0
        assert hit["theory_count"] == 0
        assert hit["source_passage_count"] == 0


def test_search_all_scope_canonical_only(client):
    r = client.get("/search/all?q=microsoft&scope=canonical")
    assert r.status_code == 200
    assert all(h["data_layer"] == "canonical" for h in r.json())


def test_search_all_scope_indexed_only(client):
    r = client.get("/search/all?q=microsoft&scope=indexed")
    assert r.status_code == 200
    assert all(h["data_layer"] == "indexed" for h in r.json())


def test_search_all_empty_query_rejected(client):
    r = client.get("/search/all?q=")
    assert r.status_code == 422


def test_search_all_no_results(client):
    r = client.get("/search/all?q=zzznomatchxxx")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Existing /search behavior unchanged
# ---------------------------------------------------------------------------

def test_existing_search_still_returns_case_records(client):
    r = client.get("/search?q=microsoft")
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    # CaseRecord fields present; no data_layer key (not a CaseSearchHit)
    assert "product_markets_considered" in results[0]
    assert "source_passages" in results[0]
    assert "data_layer" not in results[0]


def test_existing_cases_endpoint_unchanged(client):
    r = client.get("/cases")
    assert r.status_code == 200
    cases = r.json()
    assert all("product_markets_considered" in c for c in cases)
    assert all("data_layer" not in c for c in cases)
