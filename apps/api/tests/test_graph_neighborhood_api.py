"""Tests for GET /graph/neighborhood/{case_id} — response shape and trust-layer invariants."""

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
# Response shape
# ---------------------------------------------------------------------------

def test_neighborhood_shape_top_level_keys(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    data = r.json()
    assert "center_case_id" in data
    assert "nodes" in data
    assert "edges" in data
    assert "source" in data


def test_neighborhood_center_case_id_matches(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    data = r.json()
    assert data["center_case_id"] == "eu_sika_dry_mix_2019"


def test_neighborhood_node_required_fields(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    for node in r.json()["nodes"]:
        assert "id" in node
        assert "label" in node
        assert "type" in node


def test_neighborhood_edge_required_fields(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    for edge in r.json()["edges"]:
        assert "id" in edge
        assert "source" in edge
        assert "target" in edge
        assert "type" in edge


# ---------------------------------------------------------------------------
# Canonical case — trust labels
# ---------------------------------------------------------------------------

def test_canonical_center_node_data_layer(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    center = next(n for n in nodes if n["id"] == "case:eu_sika_dry_mix_2019")
    assert center["data_layer"] == "canonical"
    assert center["record_status"] == "canonical_reviewed"


def test_canonical_center_node_href(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    center = next(n for n in nodes if n["id"] == "case:eu_sika_dry_mix_2019")
    assert center["href"] == "/cases/eu_sika_dry_mix_2019"


def test_canonical_has_authority_node(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "authority" in node_types


def test_canonical_has_sector_and_outcome_nodes(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "sector" in node_types
    assert "outcome" in node_types


def test_canonical_product_markets_present(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "product_market" in node_types


def test_canonical_geographic_markets_present(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "geographic_market" in node_types


def test_canonical_edge_quality_level(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    edges = r.json()["edges"]
    decided_by = next((e for e in edges if e["type"] == "DECIDED_BY"), None)
    assert decided_by is not None
    assert decided_by["quality_level"] == "canonical_reviewed"


# ---------------------------------------------------------------------------
# Indexed case — trust labels and no canonical-only subgraph
# ---------------------------------------------------------------------------

def test_indexed_center_node_data_layer(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    center = next(n for n in nodes if n["id"] == "case:eu_illumina_grail_2022")
    assert center["data_layer"] == "indexed"
    assert center["record_status"] == "indexed_metadata"


def test_indexed_center_node_href(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    center = next(n for n in nodes if n["id"] == "case:eu_illumina_grail_2022")
    assert center["href"] == "/indexed-cases/eu_illumina_grail_2022"


def test_indexed_no_product_market_nodes(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "product_market" not in node_types


def test_indexed_no_geographic_market_nodes(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "geographic_market" not in node_types


def test_indexed_no_theory_of_harm_nodes(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    node_types = {n["type"] for n in r.json()["nodes"]}
    assert "theory_of_harm" not in node_types


def test_indexed_edge_quality_level(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    edges = r.json()["edges"]
    assert all(e["quality_level"] in ("indexed_metadata", "indexed", "canonical", None) for e in edges)
    decided_by = next((e for e in edges if e["type"] == "DECIDED_BY"), None)
    assert decided_by is not None
    assert decided_by["quality_level"] == "indexed_metadata"


def test_indexed_concept_ref_edges_carry_quality_provenance(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022")
    assert r.status_code == 200
    edges = r.json()["edges"]
    concept_edges = [e for e in edges if e["type"] == "REFERENCES_CONCEPT"]
    if concept_edges:
        for e in concept_edges:
            assert e["quality_level"] is not None
            assert e["provenance"] is not None


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

def test_neighborhood_not_found(client):
    r = client.get("/graph/neighborhood/nonexistent_xyz_2099")
    assert r.status_code == 404


def test_neighborhood_indexed_excluded_when_flag_false(client):
    r = client.get("/graph/neighborhood/eu_illumina_grail_2022?include_indexed=false")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Source field
# ---------------------------------------------------------------------------

def test_neighborhood_source_is_yaml(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    assert r.json()["source"] == "yaml"


# ---------------------------------------------------------------------------
# Node IDs are unique within a response
# ---------------------------------------------------------------------------

def test_neighborhood_node_ids_unique(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    ids = [n["id"] for n in r.json()["nodes"]]
    assert len(ids) == len(set(ids))


def test_neighborhood_edge_ids_unique(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()["edges"]]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Edge source/target reference existing nodes
# ---------------------------------------------------------------------------

def test_neighborhood_edges_reference_known_nodes(client):
    r = client.get("/graph/neighborhood/eu_sika_dry_mix_2019")
    assert r.status_code == 200
    data = r.json()
    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert edge["source"] in node_ids, f"edge source '{edge['source']}' not in nodes"
        assert edge["target"] in node_ids, f"edge target '{edge['target']}' not in nodes"
