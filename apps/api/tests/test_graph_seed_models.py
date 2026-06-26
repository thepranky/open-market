"""Tests for CaseIndexEntry, ConceptNode, and graph seed functions (no Neo4j required)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(REPO_ROOT))

from app.cases.models.case_index import CaseIndexEntry
from app.cases.models.concept import ConceptNode, ConceptRef
from app.cases.models import Outcome


# ---------------------------------------------------------------------------
# CaseIndexEntry validation
# ---------------------------------------------------------------------------

MINIMAL_INDEX = {
    "case_id": "eu_test_merger_2022",
    "case_name": "Test Corp / Target Corp",
    "jurisdiction": "EU",
    "authority": "European Commission",
    "decision_date": "2022-05-15",
    "sector": "industrials",
    "outcome": "cleared",
}


def test_case_index_entry_minimal_valid():
    entry = CaseIndexEntry.model_validate(MINIMAL_INDEX)
    assert entry.case_id == "eu_test_merger_2022"
    assert entry.jurisdiction == "EU"
    assert entry.outcome == Outcome.cleared
    assert entry.parties == []
    assert entry.concept_refs == []
    assert entry.source_url is None
    assert entry.ai_summary is None


def test_case_index_entry_with_parties_and_concepts():
    data = {
        **MINIMAL_INDEX,
        "parties": [{"name": "Test Corp", "role": "acquirer"}, {"name": "Target Corp", "role": "target"}],
        "concept_refs": [{"concept_id": "toh_hhi", "quality_level": "indexed", "provenance": "ai_extracted"}],
        "source_url": "https://example.com/case",
        "ai_summary": "A test merger.",
    }
    entry = CaseIndexEntry.model_validate(data)
    assert len(entry.parties) == 2
    assert len(entry.concept_refs) == 1
    assert entry.concept_refs[0].concept_id == "toh_hhi"
    assert entry.concept_refs[0].quality_level == "indexed"
    assert entry.concept_refs[0].provenance == "ai_extracted"


def test_case_index_entry_invalid_jurisdiction():
    data = {**MINIMAL_INDEX, "jurisdiction": "FR"}
    with pytest.raises(Exception, match="jurisdiction"):
        CaseIndexEntry.model_validate(data)


def test_case_index_entry_missing_required_field():
    data = {k: v for k, v in MINIMAL_INDEX.items() if k != "case_id"}
    with pytest.raises(Exception):
        CaseIndexEntry.model_validate(data)


def test_case_index_entry_forbids_canonical_fields():
    # extra="forbid" means canonical-only fields raise ValidationError rather than silently vanishing
    data = {
        **MINIMAL_INDEX,
        "product_markets_considered": [{"market_id": "pm_1", "name": "Widget market", "definition_status": "defined"}],
    }
    with pytest.raises(Exception, match="product_markets_considered"):
        CaseIndexEntry.model_validate(data)


# ---------------------------------------------------------------------------
# ConceptNode validation
# ---------------------------------------------------------------------------

def test_concept_node_minimal_valid():
    data = {"concept_id": "toh_hhi", "name": "HHI Threshold", "category": "theory_of_harm"}
    concept = ConceptNode.model_validate(data)
    assert concept.concept_id == "toh_hhi"
    assert concept.description is None
    assert concept.aliases == []


def test_concept_node_full():
    data = {
        "concept_id": "market_national",
        "name": "National Geographic Market",
        "category": "market_type",
        "description": "A market defined at national level.",
        "aliases": ["national market", "country-level market"],
    }
    concept = ConceptNode.model_validate(data)
    assert concept.aliases == ["national market", "country-level market"]


def test_concept_node_missing_required_fields():
    with pytest.raises(Exception):
        ConceptNode.model_validate({"concept_id": "x"})  # missing name + category


# ---------------------------------------------------------------------------
# ConceptRef validation
# ---------------------------------------------------------------------------

def test_concept_ref_valid():
    ref = ConceptRef(concept_id="toh_hhi", quality_level="canonical", provenance="manually_tagged")
    assert ref.quality_level == "canonical"


# ---------------------------------------------------------------------------
# seed_index_case — mock session, check node properties and absence of canonical subgraph
# ---------------------------------------------------------------------------

def _make_session():
    return MagicMock()


def test_seed_index_case_sets_data_layer():
    from graph.seed_graph import seed_index_case

    session = _make_session()
    entry = CaseIndexEntry.model_validate(MINIMAL_INDEX)
    seed_index_case(session, entry)

    # Collect all Cypher strings passed to session.run
    cypher_calls = [str(c.args[0]) for c in session.run.call_args_list]
    merged_case_cypher = next(c for c in cypher_calls if "MERGE (c:Case" in c)
    assert "data_layer" in merged_case_cypher
    assert "record_status" in merged_case_cypher

    # Verify property values passed
    props_call = next(c for c in session.run.call_args_list if "data_layer" in str(c.args[0]))
    # data_layer is a literal in the Cypher string ('indexed'), not a parameter
    assert "'indexed'" in props_call.args[0] or "indexed" in props_call.args[0]


def test_seed_index_case_no_canonical_subgraph():
    from graph.seed_graph import seed_index_case

    session = _make_session()
    entry = CaseIndexEntry.model_validate(MINIMAL_INDEX)
    seed_index_case(session, entry)

    cypher_calls = [str(c.args[0]) for c in session.run.call_args_list]
    # Must not create canonical-only subgraph nodes
    assert not any("ProductMarket" in c for c in cypher_calls)
    assert not any("GeographicMarket" in c for c in cypher_calls)
    assert not any("TheoryOfHarm" in c for c in cypher_calls)
    assert not any("SourcePassage" in c for c in cypher_calls)
    assert not any("SourceDocument" in c for c in cypher_calls)


def test_seed_index_case_wires_jurisdiction_authority_sector_outcome():
    from graph.seed_graph import seed_index_case

    session = _make_session()
    entry = CaseIndexEntry.model_validate(MINIMAL_INDEX)
    seed_index_case(session, entry)

    cypher_calls = [str(c.args[0]) for c in session.run.call_args_list]
    assert any("Jurisdiction" in c for c in cypher_calls)
    assert any("Authority" in c for c in cypher_calls)
    assert any("Sector" in c for c in cypher_calls)
    assert any("Outcome" in c for c in cypher_calls)


# ---------------------------------------------------------------------------
# seed_case — canonical case must carry data_layer='canonical'
# ---------------------------------------------------------------------------

def test_seed_case_sets_canonical_data_layer():
    from graph.seed_graph import seed_case

    # Build a minimal CaseRecord via the actual YAML loader for realism
    yaml_path = REPO_ROOT / "data" / "cases" / "eu" / "eu_sika_dry_mix_2019.yaml"
    if not yaml_path.exists():
        pytest.skip("eu_sika_dry_mix_2019.yaml not present")

    from app.cases.loader.yaml_loader import load_yaml_file
    case = load_yaml_file(yaml_path)

    session = _make_session()
    seed_case(session, case)

    cypher_calls = [str(c.args[0]) for c in session.run.call_args_list]
    merged_case_cypher = next(c for c in cypher_calls if "MERGE (c:Case" in c)
    assert "'canonical'" in merged_case_cypher
    assert "'canonical_reviewed'" in merged_case_cypher


# ---------------------------------------------------------------------------
# seed_concept — creates Concept node
# ---------------------------------------------------------------------------

def test_seed_concept_creates_node():
    from graph.seed_graph import seed_concept

    session = _make_session()
    concept = ConceptNode(concept_id="toh_hhi", name="HHI Threshold", category="theory_of_harm")
    seed_concept(session, concept)

    cypher_calls = [str(c.args[0]) for c in session.run.call_args_list]
    assert any("Concept" in c and "MERGE" in c for c in cypher_calls)


# ---------------------------------------------------------------------------
# _seed_concept_refs — REFERENCES_CONCEPT relationship carries quality_level + provenance
# ---------------------------------------------------------------------------

def test_seed_concept_refs_relationship_properties():
    from graph.seed_graph import _seed_concept_refs

    session = _make_session()
    refs = [ConceptRef(concept_id="toh_hhi", quality_level="indexed", provenance="ai_extracted")]
    _seed_concept_refs(session, "eu_test_merger_2022", refs)

    assert session.run.call_count == 1
    cypher = session.run.call_args.args[0]
    assert "REFERENCES_CONCEPT" in cypher
    assert "quality_level" in cypher
    assert "provenance" in cypher
    kwargs = session.run.call_args.kwargs
    assert kwargs["quality_level"] == "indexed"
    assert kwargs["provenance"] == "ai_extracted"
    assert kwargs["concept_id"] == "toh_hhi"


def test_seed_concept_refs_empty_is_noop():
    from graph.seed_graph import _seed_concept_refs

    session = _make_session()
    _seed_concept_refs(session, "eu_test_merger_2022", [])
    session.run.assert_not_called()
