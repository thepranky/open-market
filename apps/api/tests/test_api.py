"""Basic API integration tests (no Neo4j required)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CASES_DIR = str(REPO_ROOT / "data" / "cases")


@pytest.fixture
def client():
    # Point the API at the real data directory
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.data_cases_path = CASES_DIR
        mock_settings.app_title = "CompMap API"
        mock_settings.app_version = "0.1.0"
        mock_settings.neo4j_uri = "bolt://localhost:7687"
        mock_settings.neo4j_user = "neo4j"
        mock_settings.neo4j_password = "compmap_local"
        mock_settings.debug = False

        from app.services import case_service
        case_service.invalidate_cache()

        from main import app
        with TestClient(app) as c:
            yield c


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "CompMap" in r.json()["name"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_list_cases(client):
    r = client.get("/cases")
    assert r.status_code == 200
    cases = r.json()
    assert isinstance(cases, list)
    assert len(cases) >= 3


def test_filter_by_jurisdiction(client):
    r = client.get("/cases?jurisdiction=EU")
    assert r.status_code == 200
    cases = r.json()
    assert all(c["jurisdiction"] == "EU" for c in cases)


def test_case_detail(client):
    r = client.get("/cases/eu_google_fitbit_2021")
    assert r.status_code == 200
    data = r.json()
    assert data["case_id"] == "eu_google_fitbit_2021"
    assert "product_markets_considered" in data
    assert "source_passages" in data
    # New fields
    assert "case_history" in data
    assert data["case_history"] is not None
    assert "source_documents" in data
    doc = data["source_documents"][0]
    assert "retrieval_status" in doc
    assert doc["retrieval_status"] == "direct"


def test_case_not_found(client):
    r = client.get("/cases/nonexistent_case_xyz")
    assert r.status_code == 404


def test_search(client):
    r = client.get("/search?q=wearable")
    assert r.status_code == 200
    results = r.json()
    assert any("fitbit" in c["case_name"].lower() for c in results)


def test_search_empty_query(client):
    r = client.get("/search?q=")
    assert r.status_code == 422


def test_graph_case_yaml_fallback(client):
    r = client.get("/graph/case/eu_google_fitbit_2021")
    assert r.status_code == 200
    data = r.json()
    assert "case" in data
    assert "product_markets" in data
    assert "parties" in data
