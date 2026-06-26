"""
Tests for merge_drafts.py.

Covers:
  - Mismatched case IDs fail with clear error
  - Metadata precedence: outcome_metadata draft wins for priority fields
  - Unknown metadata does not overwrite known metadata
  - Global ID rewriting (pm_, gm_, toh_, com_, sp_)
  - supports_theories / supports_commitments rewrite correctly
  - Theory dedupe unions passage links, keeps richer description
  - Commitment dedupe unions passage lists and asset lists
  - Passage dedupe by (normalized quote, page, source_document_id)
  - Dry-run does not write output
  - --case-id validation fails on mismatch
"""

import copy
from pathlib import Path

import pytest
import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract.merge_drafts import (
    _IdMap,
    _finding_key,
    _focus_of,
    _is_empty,
    _merge_source_documents,
    _merge_unit_assessments,
    _norm,
    _normalize_definition_statuses,
    _pick_metadata,
    _unit_key,
    _validate_merged,
    main,
    merge_drafts,
)

# ---------------------------------------------------------------------------
# Helpers — minimal draft builders
# ---------------------------------------------------------------------------

TODAY = "2026-06-02"


def _base_draft(case_id: str = "eu_test_2020", **overrides) -> dict:
    d = {
        "_draft_note": "DRAFT",
        "case_id": case_id,
        "case_name": "Test Corp / Target Corp",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "sector": "technology",
        "outcome": "cleared",
        "decision_date": "2020-01-15",
        "procedure_stage": "phase1",
        "parties": [
            {"name": "Test Corp", "role": "acquirer"},
            {"name": "Target Corp", "role": "target"},
        ],
        "source_documents": [
            {
                "doc_id": "doc_1",
                "title": "Decision",
                "doc_type": "decision",
                "retrieval_status": "direct",
                "published_date": "2020-01-15",
            }
        ],
        "product_markets_considered": [],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "commitments": [],
        "source_passages": [],
    }
    d.update(overrides)
    return d


def _passage(pid: str, quote: str, page: str = "1", doc_id: str = "doc_1",
             theories: list = None, markets: list = None,
             commitments: list = None) -> dict:
    return {
        "passage_id": pid,
        "source_document_id": doc_id,
        "page": page,
        "quote_snippet": quote,
        "extraction_method": "pdf_extracted",
        "review_status": "unreviewed",
        "confidence_score": 0.7,
        "last_checked_date": TODAY,
        "supports_markets": markets or [],
        "supports_geographic_markets": [],
        "supports_theories": theories or [],
        "supports_commitments": commitments or [],
    }


def _theory(tid: str, name: str, ttype: str = "horizontal",
            description: str = "desc") -> dict:
    return {
        "theory_id": tid,
        "name": name,
        "theory_type": ttype,
        "theory_outcome": "upheld",
        "description": description,
    }


def _commitment(cid: str, title: str, ctype: str = "structural",
                description: str = "desc", passages: list = None,
                markets: list = None, assets: list = None) -> dict:
    return {
        "commitment_id": cid,
        "commitment_type": ctype,
        "title": title,
        "description": description,
        "divested_assets": assets or [],
        "purchaser_requirements": None,
        "markets_addressed": markets or [],
        "related_source_passages": passages or [],
        "review_status": "unreviewed",
    }


def _market(mid: str, name: str, status: str = "defined") -> dict:
    return {
        "market_id": mid,
        "name": name,
        "definition_status": status,
    }

# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestNorm:
    def test_collapses_whitespace(self):
        assert _norm("  hello   world  ") == "hello world"

    def test_lowercases(self):
        assert _norm("HELLO") == "hello"

    def test_empty_string(self):
        assert _norm("") == ""

    def test_none_safe(self):
        assert _norm(None) == ""


class TestIsEmpty:
    def test_none(self):
        assert _is_empty(None)

    def test_empty_string(self):
        assert _is_empty("")

    def test_unknown_string(self):
        assert _is_empty("unknown")

    def test_Unknown_case_insensitive(self):
        assert _is_empty("Unknown")

    def test_empty_list(self):
        assert _is_empty([])

    def test_nonempty_string(self):
        assert not _is_empty("cleared")

    def test_nonempty_list(self):
        assert not _is_empty(["item"])


class TestFocusOf:
    def test_outcome_metadata(self):
        p = Path("data/drafts/eu/eu_bayer_2018.outcome_metadata.pp1_30.draft.yaml")
        assert _focus_of(p) == "outcome_metadata"

    def test_theories(self):
        p = Path("data/drafts/eu/eu_bayer_2018.theories.innovation.draft.yaml")
        assert _focus_of(p) == "theories"

    def test_remedies(self):
        p = Path("data/drafts/eu/eu_bayer_2018.remedies.divestment.draft.yaml")
        assert _focus_of(p) == "remedies"


# ---------------------------------------------------------------------------
# Case ID validation
# ---------------------------------------------------------------------------

class TestCaseIdValidation:
    def test_mismatched_case_ids_raises(self, tmp_path):
        a = _base_draft("eu_case_a_2020")
        b = _base_draft("eu_case_b_2021")
        pa = tmp_path / "a.draft.yaml"
        pb = tmp_path / "b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        with pytest.raises(ValueError, match="mismatched case_ids"):
            merge_drafts([pa, pb])

    def test_case_id_override_mismatch_raises(self, tmp_path):
        a = _base_draft("eu_case_a_2020")
        pa = tmp_path / "a.draft.yaml"
        pa.write_text(yaml.dump(a))
        with pytest.raises(ValueError, match="case_id mismatch"):
            merge_drafts([pa], case_id_override="eu_case_b_2021")

    def test_case_id_override_match_ok(self, tmp_path):
        a = _base_draft("eu_case_a_2020")
        pa = tmp_path / "a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa], case_id_override="eu_case_a_2020")
        assert merged["case_id"] == "eu_case_a_2020"

    def test_single_draft_succeeds(self, tmp_path):
        a = _base_draft("eu_case_a_2020")
        pa = tmp_path / "a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])
        assert merged["case_id"] == "eu_case_a_2020"


# ---------------------------------------------------------------------------
# Metadata precedence
# ---------------------------------------------------------------------------

class TestMetadataPrecedence:
    def _make_paths(self, tmp_path, drafts_and_names):
        paths = []
        for d, name in drafts_and_names:
            p = tmp_path / name
            p.write_text(yaml.dump(d))
            paths.append(p)
        return paths

    def test_outcome_metadata_draft_wins_for_outcome(self, tmp_path):
        # market_definition draft has outcome=unknown, outcome_metadata has cleared_with_conditions
        mkt = _base_draft(outcome="unknown")
        meta = _base_draft(outcome="cleared_with_conditions")
        paths = self._make_paths(tmp_path, [
            (mkt, "eu_test.market_definition.draft.yaml"),
            (meta, "eu_test.outcome_metadata.foo.draft.yaml"),
        ])
        result = _pick_metadata([mkt, meta], paths)
        assert result["outcome"] == "cleared_with_conditions"

    def test_outcome_metadata_draft_wins_for_procedure_stage(self, tmp_path):
        mkt = _base_draft(procedure_stage="phase1")
        meta = _base_draft(procedure_stage="phase2")
        paths = self._make_paths(tmp_path, [
            (mkt, "eu_test.market_definition.draft.yaml"),
            (meta, "eu_test.outcome_metadata.foo.draft.yaml"),
        ])
        result = _pick_metadata([mkt, meta], paths)
        assert result["procedure_stage"] == "phase2"

    def test_unknown_does_not_overwrite_known(self, tmp_path):
        # First draft has outcome=cleared, second has outcome=unknown — keep cleared
        a = _base_draft(outcome="cleared")
        b = _base_draft(outcome="unknown")
        paths = self._make_paths(tmp_path, [
            (a, "eu_test.theories.foo.draft.yaml"),
            (b, "eu_test.theories.bar.draft.yaml"),
        ])
        result = _pick_metadata([a, b], paths)
        assert result["outcome"] == "cleared"

    def test_empty_outcome_does_not_overwrite_known(self, tmp_path):
        a = _base_draft(outcome="cleared")
        b = _base_draft()
        b["outcome"] = ""
        paths = self._make_paths(tmp_path, [
            (a, "eu_test.theories.a.draft.yaml"),
            (b, "eu_test.theories.b.draft.yaml"),
        ])
        result = _pick_metadata([a, b], paths)
        assert result["outcome"] == "cleared"

    def test_first_nonempty_used_when_no_outcome_metadata_draft(self, tmp_path):
        a = _base_draft(outcome="unknown")
        b = _base_draft(outcome="cleared_with_conditions")
        paths = self._make_paths(tmp_path, [
            (a, "eu_test.theories.a.draft.yaml"),
            (b, "eu_test.theories.b.draft.yaml"),
        ])
        result = _pick_metadata([a, b], paths)
        # 'a' has outcome=unknown (empty), falls back to 'b'
        assert result["outcome"] == "cleared_with_conditions"


# ---------------------------------------------------------------------------
# Source document merge
# ---------------------------------------------------------------------------

class TestSourceDocumentMerge:
    def test_deduplicates_by_doc_id(self):
        doc1 = {"doc_id": "d1", "title": "Decision", "doc_type": "decision", "retrieval_status": "direct"}
        doc2 = {"doc_id": "d1", "title": "Decision", "doc_type": "decision", "retrieval_status": "direct"}
        drafts = [
            {"source_documents": [doc1]},
            {"source_documents": [doc2]},
        ]
        result = _merge_source_documents(drafts)
        assert len(result) == 1

    def test_merges_distinct_documents(self):
        doc1 = {"doc_id": "d1", "title": "Decision", "doc_type": "decision"}
        doc2 = {"doc_id": "d2", "title": "Annex", "doc_type": "annex"}
        drafts = [{"source_documents": [doc1]}, {"source_documents": [doc2]}]
        result = _merge_source_documents(drafts)
        assert len(result) == 2

    def test_fills_missing_fields_from_duplicate(self):
        doc1 = {"doc_id": "d1", "title": "Decision", "doc_type": "decision", "pdf_url": None}
        doc2 = {"doc_id": "d1", "title": "Decision", "doc_type": "decision", "pdf_url": "https://example.com/d.pdf"}
        drafts = [{"source_documents": [doc1]}, {"source_documents": [doc2]}]
        result = _merge_source_documents(drafts)
        assert result[0]["pdf_url"] == "https://example.com/d.pdf"


# ---------------------------------------------------------------------------
# Global ID rewriting
# ---------------------------------------------------------------------------

class TestGlobalIdRewriting:
    def test_product_market_ids_start_at_pm_1(self, tmp_path):
        a = _base_draft(product_markets_considered=[
            _market("pm_1", "Widget market"),
        ])
        b = _base_draft(product_markets_considered=[
            _market("pm_1", "Gadget market"),
        ])
        pa = tmp_path / "eu_test.market_definition.a.draft.yaml"
        pb = tmp_path / "eu_test.market_definition.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        pm_ids = [m["market_id"] for m in merged["product_markets_considered"]]
        assert pm_ids == ["pm_1", "pm_2"]

    def test_theory_ids_start_at_toh_1(self, tmp_path):
        a = _base_draft(theories_of_harm=[
            _theory("toh_1", "Horizontal overlap"),
        ])
        b = _base_draft(theories_of_harm=[
            _theory("toh_1", "Innovation harm"),
        ])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        ids = [t["theory_id"] for t in merged["theories_of_harm"]]
        assert ids == ["toh_1", "toh_2"]

    def test_commitment_ids_start_at_com_1(self, tmp_path):
        a = _base_draft(commitments=[_commitment("com_1", "Divestiture A")])
        b = _base_draft(commitments=[_commitment("com_1", "Behavioural remedy")])
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        ids = [c["commitment_id"] for c in merged["commitments"]]
        assert ids == ["com_1", "com_2"]

    def test_passage_ids_start_at_sp_1(self, tmp_path):
        a = _base_draft(source_passages=[
            _passage("sp_1", "First quote here"),
        ])
        b = _base_draft(source_passages=[
            _passage("sp_1", "Second distinct quote"),
        ])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        ids = [p["passage_id"] for p in merged["source_passages"]]
        assert ids == ["sp_1", "sp_2"]


# ---------------------------------------------------------------------------
# Cross-reference rewriting
# ---------------------------------------------------------------------------

class TestCrossRefRewriting:
    def test_supports_theories_rewritten(self, tmp_path):
        # Draft A: sp_1 supports toh_1. Draft B: sp_1 supports toh_1 (different theory).
        # After merge: sp_1 from A -> sp_1 global; sp_1 from B -> sp_2 global
        # toh_1 from A -> toh_1 global; toh_1 from B -> toh_2 global
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", "Theory Alpha")],
            source_passages=[_passage("sp_1", "Quote alpha", theories=["toh_1"])],
        )
        b = _base_draft(
            theories_of_harm=[_theory("toh_1", "Theory Beta")],
            source_passages=[_passage("sp_1", "Quote beta", theories=["toh_1"])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])

        # Build passage-by-id map
        sp_map = {p["passage_id"]: p for p in merged["source_passages"]}
        toh_map = {t["theory_id"]: t for t in merged["theories_of_harm"]}

        assert "toh_1" in toh_map and toh_map["toh_1"]["name"] == "Theory Alpha"
        assert "toh_2" in toh_map and toh_map["toh_2"]["name"] == "Theory Beta"
        # sp_1 (alpha) must reference toh_1
        assert sp_map["sp_1"]["supports_theories"] == ["toh_1"]
        # sp_2 (beta) must reference toh_2
        assert sp_map["sp_2"]["supports_theories"] == ["toh_2"]

    def test_supports_commitments_rewritten(self, tmp_path):
        a = _base_draft(
            commitments=[_commitment("com_1", "Remedy Alpha", passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Quote alpha com", commitments=["com_1"])],
        )
        b = _base_draft(
            commitments=[_commitment("com_1", "Remedy Beta", passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Quote beta com", commitments=["com_1"])],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])

        sp_map = {p["passage_id"]: p for p in merged["source_passages"]}
        com_map = {c["commitment_id"]: c for c in merged["commitments"]}

        assert "com_1" in com_map
        assert "com_2" in com_map
        assert "com_1" in sp_map["sp_1"]["supports_commitments"]
        assert "com_2" in sp_map["sp_2"]["supports_commitments"]

    def test_commitment_related_passages_rewritten(self, tmp_path):
        # Commitment in draft A references sp_1; after merge sp_1 becomes sp_1 globally.
        # Commitment in draft B references sp_1; after merge that sp_1 becomes sp_2 globally.
        a = _base_draft(
            commitments=[_commitment("com_1", "Remedy A", passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Passage for remedy A")],
        )
        b = _base_draft(
            commitments=[_commitment("com_1", "Remedy B", passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Passage for remedy B")],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])

        com_map = {c["commitment_id"]: c for c in merged["commitments"]}
        assert "sp_1" in com_map["com_1"]["related_source_passages"]
        assert "sp_2" in com_map["com_2"]["related_source_passages"]


# ---------------------------------------------------------------------------
# Theory deduplication
# ---------------------------------------------------------------------------

class TestTheoryDedupe:
    def test_identical_theories_collapsed(self, tmp_path):
        t = _theory("toh_1", "Horizontal overlap in widgets", ttype="horizontal")
        a = _base_draft(theories_of_harm=[t])
        b = _base_draft(theories_of_harm=[copy.deepcopy(t)])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, warnings = merge_drafts([pa, pb])
        assert len(merged["theories_of_harm"]) == 1
        assert any("collapsed" in w for w in warnings)

    def test_theory_dedupe_unions_passages(self, tmp_path):
        # Same theory in two drafts, each supported by a different passage.
        t_name = "Horizontal overlap in widgets"
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", t_name)],
            source_passages=[_passage("sp_1", "Quote from draft A", theories=["toh_1"])],
        )
        b = _base_draft(
            theories_of_harm=[_theory("toh_1", t_name)],
            source_passages=[_passage("sp_1", "Quote from draft B", theories=["toh_1"])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])

        # One merged theory
        assert len(merged["theories_of_harm"]) == 1
        merged_toh = merged["theories_of_harm"][0]
        assert merged_toh["theory_id"] == "toh_1"

        # Both passages should exist and both reference toh_1
        passages_supporting = [
            p for p in merged["source_passages"]
            if "toh_1" in p["supports_theories"]
        ]
        assert len(passages_supporting) == 2

    def test_distinct_theories_kept_separately(self, tmp_path):
        a = _base_draft(theories_of_harm=[_theory("toh_1", "Horizontal overlap")])
        b = _base_draft(theories_of_harm=[_theory("toh_1", "Innovation harm")])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert len(merged["theories_of_harm"]) == 2

    def test_theory_dedupe_keeps_richer_description(self, tmp_path):
        short_desc = "Short."
        long_desc = "Much longer description with more detail about the theory."
        a = _base_draft(theories_of_harm=[_theory("toh_1", "Same theory", description=short_desc)])
        b = _base_draft(theories_of_harm=[_theory("toh_1", "Same theory", description=long_desc)])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert merged["theories_of_harm"][0]["description"] == long_desc


# ---------------------------------------------------------------------------
# Commitment deduplication
# ---------------------------------------------------------------------------

class TestCommitmentDedupe:
    def test_identical_commitments_collapsed(self, tmp_path):
        c = _commitment("com_1", "Divestiture of seed business")
        a = _base_draft(commitments=[c])
        b = _base_draft(commitments=[copy.deepcopy(c)])
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, warnings = merge_drafts([pa, pb])
        assert len(merged["commitments"]) == 1

    def test_commitment_dedupe_unions_passages(self, tmp_path):
        # Same commitment in two drafts, each with a different supporting passage.
        c_title = "Divestiture of seed business"
        a = _base_draft(
            commitments=[_commitment("com_1", c_title, passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Passage A about seeds")],
        )
        b = _base_draft(
            commitments=[_commitment("com_1", c_title, passages=["sp_1"])],
            source_passages=[_passage("sp_1", "Passage B about seeds")],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert len(merged["commitments"]) == 1
        c = merged["commitments"][0]
        # Both sp_1 and sp_2 should appear in related_source_passages
        assert len(c["related_source_passages"]) == 2

    def test_commitment_dedupe_unions_assets(self, tmp_path):
        c_title = "Divestiture package"
        a = _base_draft(
            commitments=[_commitment("com_1", c_title, assets=["Asset A"])],
        )
        b = _base_draft(
            commitments=[_commitment("com_1", c_title, assets=["Asset B"])],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pb = tmp_path / "eu_test.remedies.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert set(merged["commitments"][0]["divested_assets"]) == {"Asset A", "Asset B"}


# ---------------------------------------------------------------------------
# Passage deduplication
# ---------------------------------------------------------------------------

class TestPassageDedupe:
    def test_identical_passages_collapsed(self, tmp_path):
        p = _passage("sp_1", "The Commission finds that market shares are high.")
        a = _base_draft(source_passages=[p])
        b = _base_draft(source_passages=[copy.deepcopy(p)])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, warnings = merge_drafts([pa, pb])
        assert len(merged["source_passages"]) == 1
        assert any("collapsed" in w for w in warnings)

    def test_different_quote_same_page_not_collapsed(self, tmp_path):
        a = _base_draft(source_passages=[_passage("sp_1", "Quote alpha", page="5")])
        b = _base_draft(source_passages=[_passage("sp_1", "Quote beta", page="5")])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert len(merged["source_passages"]) == 2

    def test_same_quote_different_page_not_collapsed(self, tmp_path):
        a = _base_draft(source_passages=[_passage("sp_1", "Same text here", page="5")])
        b = _base_draft(source_passages=[_passage("sp_1", "Same text here", page="6")])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert len(merged["source_passages"]) == 2

    def test_passage_dedupe_unions_theory_refs(self, tmp_path):
        # Same passage text, but draft A points it at toh_1, draft B at toh_1 (same)
        # After dedupe there should be one passage with toh_1.
        t = _theory("toh_1", "Same theory name")
        p_text = "Identical passage about the theory."
        a = _base_draft(
            theories_of_harm=[t],
            source_passages=[_passage("sp_1", p_text, theories=["toh_1"])],
        )
        b = _base_draft(
            theories_of_harm=[copy.deepcopy(t)],
            source_passages=[_passage("sp_1", p_text, theories=["toh_1"])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        # One theory, one passage, passage supports the theory
        assert len(merged["theories_of_harm"]) == 1
        assert len(merged["source_passages"]) == 1
        assert "toh_1" in merged["source_passages"][0]["supports_theories"]

    def test_passage_dedupe_by_source_document_id(self, tmp_path):
        # Same quote and page, different doc -> not collapsed
        a = _base_draft(source_passages=[_passage("sp_1", "Quote text", page="1", doc_id="doc_1")])
        b = _base_draft(source_passages=[_passage("sp_1", "Quote text", page="1", doc_id="doc_2")])
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        assert len(merged["source_passages"]) == 2


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        a = _base_draft()
        pa = tmp_path / "eu_test.market_definition.draft.yaml"
        pa.write_text(yaml.dump(a))

        out_path = tmp_path / "output.merged.draft.yaml"
        rc = main([str(pa), "--dry-run", "--output", str(out_path)])
        assert rc == 0
        assert not out_path.exists()

    def test_non_dry_run_writes_file(self, tmp_path):
        a = _base_draft()
        pa = tmp_path / "eu_test.market_definition.draft.yaml"
        pa.write_text(yaml.dump(a))

        out_path = tmp_path / "output.merged.draft.yaml"
        rc = main([str(pa), "--output", str(out_path)])
        assert rc == 0
        assert out_path.exists()

    def test_missing_draft_returns_nonzero(self, tmp_path):
        rc = main([str(tmp_path / "nonexistent.draft.yaml")])
        assert rc != 0


# ---------------------------------------------------------------------------
# Full integration — two overlapping theory drafts
# ---------------------------------------------------------------------------

class TestIntegrationTwoTheoryDrafts:
    def test_merges_two_theory_drafts(self, tmp_path):
        a = _base_draft(
            theories_of_harm=[
                _theory("toh_1", "Innovation harm in crop protection"),
                _theory("toh_2", "Horizontal overlap in OSR HT"),
            ],
            source_passages=[
                _passage("sp_1", "Passage supporting innovation", theories=["toh_1"]),
                _passage("sp_2", "Passage supporting OSR", theories=["toh_2"]),
            ],
        )
        b = _base_draft(
            theories_of_harm=[
                _theory("toh_1", "Innovation harm in crop protection"),  # same as a.toh_1
                _theory("toh_1", "Vertical integration concern", ttype="vertical"),  # distinct
            ],
            source_passages=[
                _passage("sp_1", "Another innovation passage", theories=["toh_1"]),
                _passage("sp_2", "Vertical concern passage", page="50", theories=["toh_1"]),
            ],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, warnings = merge_drafts([pa, pb])

        # Innovation harm appears in both drafts -> deduped to 1
        # OSR HT only in a -> 1
        # Vertical only in b -> 1
        # Total = 3
        assert len(merged["theories_of_harm"]) == 3

        # All IDs are sequential toh_1, toh_2, toh_3
        ids = sorted(t["theory_id"] for t in merged["theories_of_harm"])
        assert ids == ["toh_1", "toh_2", "toh_3"]

        # No passage should reference a stale per-draft ID
        all_theory_refs = set()
        for p in merged["source_passages"]:
            all_theory_refs.update(p["supports_theories"])
        valid_ids = {t["theory_id"] for t in merged["theories_of_harm"]}
        assert all_theory_refs.issubset(valid_ids), (
            f"Stale theory refs: {all_theory_refs - valid_ids}"
        )


# ---------------------------------------------------------------------------
# Back-reference synthesis
# ---------------------------------------------------------------------------

class TestSynthesizeBackRefs:
    def test_theory_back_refs_populated_from_passages(self, tmp_path):
        # Passages support toh_1; theory should get source_passage_refs populated.
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", "Innovation harm")],
            source_passages=[
                _passage("sp_1", "Passage A", theories=["toh_1"]),
                _passage("sp_2", "Passage B", page="2", theories=["toh_1"]),
            ],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, warnings = merge_drafts([pa])

        toh = merged["theories_of_harm"][0]
        assert toh["theory_id"] == "toh_1"
        assert set(toh["source_passage_refs"]) == {"sp_1", "sp_2"}
        assert any("back-ref" in w.lower() for w in warnings)

    def test_theory_back_refs_union_with_existing(self, tmp_path):
        # Theory already has an explicit source_passage_ref; synthesis should
        # add the passage-inferred ones without duplicating the existing one.
        theory = _theory("toh_1", "Horizontal overlap")
        theory["source_passage_refs"] = ["sp_1"]  # pre-existing explicit ref
        a = _base_draft(
            theories_of_harm=[theory],
            source_passages=[
                _passage("sp_1", "Quote already referenced", theories=["toh_1"]),
                _passage("sp_2", "Additional quote", page="3", theories=["toh_1"]),
            ],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])

        toh = merged["theories_of_harm"][0]
        refs = toh["source_passage_refs"]
        # Both sp_1 and sp_2 must appear, but sp_1 must not be duplicated
        assert set(refs) == {"sp_1", "sp_2"}
        assert refs.count("sp_1") == 1

    def test_theory_with_no_passage_support_gets_empty_list(self, tmp_path):
        # Theory not referenced by any passage keeps an empty list.
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", "Orphan theory")],
            source_passages=[_passage("sp_1", "Unrelated passage", theories=[])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])

        toh = merged["theories_of_harm"][0]
        assert toh["source_passage_refs"] == []

    def test_commitment_back_refs_populated_from_passages(self, tmp_path):
        # Passages with supports_commitments -> commitment.related_source_passages.
        a = _base_draft(
            commitments=[_commitment("com_1", "Divestiture A")],
            source_passages=[
                _passage("sp_1", "Remedy passage A", commitments=["com_1"]),
                _passage("sp_2", "Remedy passage B", page="5", commitments=["com_1"]),
            ],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, warnings = merge_drafts([pa])

        com = merged["commitments"][0]
        assert set(com["related_source_passages"]) == {"sp_1", "sp_2"}
        assert any("back-ref" in w.lower() for w in warnings)

    def test_commitment_back_refs_union_with_existing(self, tmp_path):
        # Commitment already has related_source_passages; union, no duplicates.
        com = _commitment("com_1", "Remedy B", passages=["sp_1"])
        a = _base_draft(
            commitments=[com],
            source_passages=[
                _passage("sp_1", "Existing passage", commitments=["com_1"]),
                _passage("sp_2", "New passage", page="6", commitments=["com_1"]),
            ],
        )
        pa = tmp_path / "eu_test.remedies.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])

        com_out = merged["commitments"][0]
        refs = com_out["related_source_passages"]
        assert set(refs) == {"sp_1", "sp_2"}
        assert refs.count("sp_1") == 1

    def test_back_refs_correct_after_id_rewrite(self, tmp_path):
        # Two drafts each with distinct passages; after ID rewrite the back-refs
        # in theories and commitments must use the new global IDs.
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", "Theory Alpha")],
            source_passages=[_passage("sp_1", "Alpha passage", theories=["toh_1"])],
        )
        b = _base_draft(
            theories_of_harm=[_theory("toh_1", "Theory Beta")],
            source_passages=[_passage("sp_1", "Beta passage", theories=["toh_1"])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pb = tmp_path / "eu_test.theories.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])

        # Theories are distinct -> toh_1 and toh_2
        toh_map = {t["theory_id"]: t for t in merged["theories_of_harm"]}
        sp_map = {p["passage_id"]: p for p in merged["source_passages"]}
        assert "toh_1" in toh_map and "toh_2" in toh_map
        # toh_1's back-refs must only contain the passage that references it
        toh1_refs = set(toh_map["toh_1"]["source_passage_refs"])
        toh2_refs = set(toh_map["toh_2"]["source_passage_refs"])
        # Each theory supported by exactly one passage; refs must be global IDs
        assert len(toh1_refs) == 1
        assert len(toh2_refs) == 1
        # The passage IDs in back-refs must exist in merged passages
        all_sp_ids = set(sp_map.keys())
        assert toh1_refs.issubset(all_sp_ids)
        assert toh2_refs.issubset(all_sp_ids)
        # They must reference different passages
        assert toh1_refs != toh2_refs


# ---------------------------------------------------------------------------
# definition_status normalisation
# ---------------------------------------------------------------------------

class TestDefinitionStatusNormalization:
    def _run_normalize(self, pm_statuses, gm_statuses=None):
        """Helper: build minimal market lists, run normalisation, return (pms, gms, warnings)."""
        pms = [{"market_id": f"pm_{i+1}", "name": f"Market {i+1}", "definition_status": s}
               for i, s in enumerate(pm_statuses)]
        gms = [{"market_id": f"gm_{i+1}", "name": f"Geo {i+1}", "definition_status": s}
               for i, s in enumerate(gm_statuses or [])]
        warnings: list = []
        _normalize_definition_statuses(pms, gms, warnings)
        return pms, gms, warnings

    def test_valid_statuses_unchanged(self):
        for status in ("defined", "discussed", "segmented", "left_open", "considered"):
            pms, _, warnings = self._run_normalize([status])
            assert pms[0]["definition_status"] == status
            assert not warnings

    def test_not_conclusive_normalized_to_left_open(self):
        pms, _, warnings = self._run_normalize(["not_conclusive"])
        assert pms[0]["definition_status"] == "left_open"
        assert any("not_conclusive" in w and "left_open" in w for w in warnings)

    def test_precedent_only_normalized_to_discussed(self):
        pms, _, warnings = self._run_normalize(["precedent_only"])
        assert pms[0]["definition_status"] == "discussed"
        assert any("precedent_only" in w and "discussed" in w for w in warnings)

    def test_possible_segmentation_normalized_to_discussed(self):
        pms, _, warnings = self._run_normalize(["possible_segmentation"])
        assert pms[0]["definition_status"] == "discussed"
        assert any("possible_segmentation" in w for w in warnings)

    def test_unknown_warned_but_not_changed(self):
        pms, _, warnings = self._run_normalize(["unknown"])
        # 'unknown' has no safe automatic mapping — value preserved
        assert pms[0]["definition_status"] == "unknown"
        assert any("WARN" in w and "unknown" in w for w in warnings)

    def test_unrecognised_value_warned_but_not_changed(self):
        pms, _, warnings = self._run_normalize(["provisional"])
        assert pms[0]["definition_status"] == "provisional"
        assert any("WARN" in w and "provisional" in w for w in warnings)

    def test_normalisation_applied_to_geographic_markets(self):
        _, gms, warnings = self._run_normalize([], ["not_conclusive"])
        assert gms[0]["definition_status"] == "left_open"

    def test_warning_deduplicated_across_multiple_occurrences(self):
        # Three markets with 'not_conclusive' -> only one INFO warning, not three.
        pms, _, warnings = self._run_normalize(
            ["not_conclusive", "not_conclusive", "not_conclusive"]
        )
        info_warnings = [w for w in warnings if "not_conclusive" in w]
        assert len(info_warnings) == 1

    def test_normalisation_reduces_schema_warnings_in_merge(self, tmp_path):
        # End-to-end: drafts with non_conclusive status; after merge validation
        # should not flag that field.
        a = _base_draft(
            product_markets_considered=[
                _market("pm_1", "Widget market", status="not_conclusive"),
            ],
        )
        pa = tmp_path / "eu_test.market_definition.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, warnings = merge_drafts([pa])

        # Merged market should have the normalised value
        assert merged["product_markets_considered"][0]["definition_status"] == "left_open"
        # Validation should PASS (not_conclusive was the only schema error)
        ok, err = _validate_merged(merged)
        assert ok, f"Validation still failing after normalisation: {err}"


# ---------------------------------------------------------------------------
# unit_assessment key helpers
# ---------------------------------------------------------------------------

class TestUnitKey:
    def test_key_normalises_label(self):
        u = {"unit_type": "crop", "unit_label": "  CUCUMBER  "}
        assert _unit_key(u) == ("crop", "cucumber")

    def test_key_case_insensitive_unit_type(self):
        u = {"unit_type": "Crop", "unit_label": "Onion"}
        assert _unit_key(u)[0] == "crop"

    def test_key_differs_by_label(self):
        u1 = {"unit_type": "crop", "unit_label": "Cucumber"}
        u2 = {"unit_type": "crop", "unit_label": "Onion"}
        assert _unit_key(u1) != _unit_key(u2)

    def test_key_differs_by_type(self):
        u1 = {"unit_type": "crop", "unit_label": "Cucumber"}
        u2 = {"unit_type": "route", "unit_label": "Cucumber"}
        assert _unit_key(u1) != _unit_key(u2)


class TestFindingKey:
    def test_key_normalises_fields(self):
        f = {
            "finding_type": "horizontal_overlap",
            "segment": "  American Slicer  ",
            "geography": "Italy",
            "conclusion": "siec",
        }
        key = _finding_key(f)
        assert key == ("horizontal_overlap", "american slicer", "italy", "siec")

    def test_distinct_geography_different_key(self):
        base = {"finding_type": "h", "segment": "seg", "geography": "IT", "conclusion": "siec"}
        other = dict(base, geography="DE")
        assert _finding_key(base) != _finding_key(other)


# ---------------------------------------------------------------------------
# unit_assessment merge
# ---------------------------------------------------------------------------

def _unit(unit_type: str, unit_label: str, findings: list = None) -> dict:
    return {
        "unit_type": unit_type,
        "unit_label": unit_label,
        "findings": findings or [],
    }


def _finding(fid: str, ftype: str = "horizontal_overlap", segment: str = "Seg A",
              geography: str = "Italy", conclusion: str = "siec",
              description: str = "desc", refs: list = None,
              markets: list = None, theories: list = None) -> dict:
    return {
        "finding_id": fid,
        "finding_type": ftype,
        "segment": segment,
        "geography": geography,
        "conclusion": conclusion,
        "description": description,
        "source_passage_refs": refs or [],
        "related_markets": markets or [],
        "related_theories": theories or [],
    }


class TestMergeUnitAssessments:
    def _run(self, items, sp_map=None):
        if sp_map is None:
            sp_map = _IdMap()
        warnings: list = []
        result = _merge_unit_assessments(items, sp_map, warnings)
        return result, warnings

    def test_single_unit_preserved(self):
        u = _unit("crop", "Cucumber", [_finding("f_1")])
        result, _ = self._run([(0, u)])
        assert len(result) == 1
        assert result[0]["unit_label"] == "Cucumber"
        assert len(result[0]["findings"]) == 1

    def test_two_distinct_units_kept_separately(self):
        u1 = _unit("crop", "Cucumber", [_finding("f_1")])
        u2 = _unit("crop", "Onion", [_finding("f_1")])
        result, _ = self._run([(0, u1), (0, u2)])
        assert len(result) == 2
        labels = {r["unit_label"] for r in result}
        assert labels == {"Cucumber", "Onion"}

    def test_same_unit_different_drafts_deduped(self):
        u1 = _unit("crop", "Cucumber", [_finding("f_1", segment="Seg A")])
        u2 = _unit("crop", "Cucumber", [_finding("f_1", segment="Seg B")])
        result, warnings = self._run([(0, u1), (1, u2)])
        assert len(result) == 1
        assert len(result[0]["findings"]) == 2   # distinct findings kept
        assert any("collapsed" in w for w in warnings)

    def test_same_unit_label_case_insensitive(self):
        u1 = _unit("crop", "cucumber", [_finding("f_1")])
        u2 = _unit("crop", "CUCUMBER", [_finding("f_1", segment="Seg B")])
        result, _ = self._run([(0, u1), (1, u2)])
        assert len(result) == 1

    def test_finding_ids_reassigned_sequentially(self):
        u = _unit("crop", "Cucumber", [
            _finding("f_1", segment="A"),
            _finding("f_2", segment="B"),
        ])
        result, _ = self._run([(0, u)])
        ids = [f["finding_id"] for f in result[0]["findings"]]
        assert ids == ["f_1", "f_2"]

    def test_finding_ids_unique_after_dedupe(self):
        # Two drafts, same unit, distinct findings → IDs should be f_1, f_2
        u1 = _unit("crop", "Cucumber", [_finding("f_1", segment="Seg A")])
        u2 = _unit("crop", "Cucumber", [_finding("f_1", segment="Seg B")])
        result, _ = self._run([(0, u1), (1, u2)])
        ids = [f["finding_id"] for f in result[0]["findings"]]
        assert len(ids) == len(set(ids))   # all unique
        assert set(ids) == {"f_1", "f_2"}

    def test_duplicate_findings_collapsed(self):
        f = _finding("f_1", segment="Seg A", geography="Italy", conclusion="siec")
        u1 = _unit("crop", "Cucumber", [f])
        u2 = _unit("crop", "Cucumber", [copy.deepcopy(f)])
        result, warnings = self._run([(0, u1), (1, u2)])
        assert len(result[0]["findings"]) == 1
        assert any("collapsed" in w for w in warnings)

    def test_duplicate_finding_unions_refs(self):
        f1 = _finding("f_1", segment="Seg A", refs=["sp_1"])
        f2 = _finding("f_1", segment="Seg A", refs=["sp_2"])
        u1 = _unit("crop", "Cucumber", [f1])
        u2 = _unit("crop", "Cucumber", [f2])
        # Build a sp_map that maps (draft_idx, old_id) -> new_id
        sp_map = _IdMap()
        sp_map.register(0, "sp_1", "sp_1")
        sp_map.register(1, "sp_2", "sp_2")
        result, _ = self._run([(0, u1), (1, u2)], sp_map)
        refs = set(result[0]["findings"][0]["source_passage_refs"])
        assert refs == {"sp_1", "sp_2"}

    def test_duplicate_finding_keeps_richer_description(self):
        f1 = _finding("f_1", segment="Seg A", description="Short.")
        f2 = _finding("f_1", segment="Seg A", description="Much longer description with detail.")
        u1 = _unit("crop", "Cucumber", [f1])
        u2 = _unit("crop", "Cucumber", [f2])
        result, _ = self._run([(0, u1), (1, u2)])
        assert result[0]["findings"][0]["description"] == "Much longer description with detail."

    def test_duplicate_finding_unions_related_markets(self):
        f1 = _finding("f_1", segment="Seg A", markets=["Market A"])
        f2 = _finding("f_1", segment="Seg A", markets=["Market B"])
        u1 = _unit("crop", "Cucumber", [f1])
        u2 = _unit("crop", "Cucumber", [f2])
        result, _ = self._run([(0, u1), (1, u2)])
        markets = set(result[0]["findings"][0]["related_markets"])
        assert markets == {"Market A", "Market B"}

    def test_passage_refs_rewritten_via_sp_map(self):
        f = _finding("f_1", refs=["sp_1"])
        u = _unit("crop", "Cucumber", [f])
        sp_map = _IdMap()
        sp_map.register(0, "sp_1", "sp_3")   # sp_1 in draft 0 -> sp_3 global
        result, _ = self._run([(0, u)], sp_map)
        assert result[0]["findings"][0]["source_passage_refs"] == ["sp_3"]

    def test_empty_unit_assessments_not_added_to_merged(self, tmp_path):
        # Draft with no unit_assessments field — merged output should not have key
        a = _base_draft()
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])
        assert "unit_assessments" not in merged

    def test_unit_assessments_appear_in_merged_output(self, tmp_path):
        u = _unit("crop", "Cucumber", [_finding("f_1")])
        a = _base_draft(unit_assessments=[u])
        pa = tmp_path / "eu_test.unit_assessment.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])
        assert "unit_assessments" in merged
        assert len(merged["unit_assessments"]) == 1

    def test_two_unit_assessment_drafts_merged(self, tmp_path):
        # Two drafts with different units — both should appear in merged output
        a = _base_draft(unit_assessments=[_unit("crop", "Cucumber", [_finding("f_1")])])
        b = _base_draft(unit_assessments=[_unit("crop", "Onion", [_finding("f_1")])])
        pa = tmp_path / "eu_test.unit_assessment.a.draft.yaml"
        pb = tmp_path / "eu_test.unit_assessment.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        uas = merged.get("unit_assessments", [])
        assert len(uas) == 2
        labels = {u["unit_label"] for u in uas}
        assert labels == {"Cucumber", "Onion"}

    def test_same_unit_across_two_drafts_deduped_in_merge(self, tmp_path):
        # Same unit in two drafts with different findings — should collapse to 1 unit, 2 findings
        a = _base_draft(unit_assessments=[
            _unit("crop", "Cucumber", [_finding("f_1", segment="Seg A")])
        ])
        b = _base_draft(unit_assessments=[
            _unit("crop", "Cucumber", [_finding("f_1", segment="Seg B")])
        ])
        pa = tmp_path / "eu_test.unit_assessment.a.draft.yaml"
        pb = tmp_path / "eu_test.unit_assessment.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, warnings = merge_drafts([pa, pb])
        uas = merged.get("unit_assessments", [])
        assert len(uas) == 1
        assert len(uas[0]["findings"]) == 2
        assert any("collapsed" in w for w in warnings)

    def test_no_regression_existing_market_merge(self, tmp_path):
        # Verify that adding unit_assessment support doesn't break market merging
        a = _base_draft(product_markets_considered=[_market("pm_1", "Widget market")])
        b = _base_draft(product_markets_considered=[_market("pm_1", "Gadget market")])
        pa = tmp_path / "eu_test.market_definition.a.draft.yaml"
        pb = tmp_path / "eu_test.market_definition.b.draft.yaml"
        pa.write_text(yaml.dump(a))
        pb.write_text(yaml.dump(b))
        merged, _ = merge_drafts([pa, pb])
        pm_ids = [m["market_id"] for m in merged["product_markets_considered"]]
        assert pm_ids == ["pm_1", "pm_2"]

    def test_no_regression_theory_merge(self, tmp_path):
        # Verify that theory merging still works when unit_assessments are also present
        a = _base_draft(
            theories_of_harm=[_theory("toh_1", "Innovation harm")],
            unit_assessments=[_unit("crop", "Cucumber", [_finding("f_1")])],
        )
        pa = tmp_path / "eu_test.theories.a.draft.yaml"
        pa.write_text(yaml.dump(a))
        merged, _ = merge_drafts([pa])
        assert len(merged["theories_of_harm"]) == 1
        assert len(merged["unit_assessments"]) == 1
