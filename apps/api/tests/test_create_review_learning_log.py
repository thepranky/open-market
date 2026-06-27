"""
Tests for apps/api/scripts/cases/review/create_review_learning_log.py.

Covers: definition_status change, support linkage corrections, outcome_passage_misuse,
draft-only field stripping, metadata completion, and end-to-end file writing.
No network access; no LLM calls; isolated filesystem via tmp_path.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from create_review_learning_log import (
    _is_outcome_passage,
    _norm,
    build_review_log,
    compute_review_delta,
)


# ---------------------------------------------------------------------------
# Minimal fixture builders
# ---------------------------------------------------------------------------


def _draft(
    *,
    outcome="unknown",
    product_markets=None,
    geographic_markets=None,
    passages=None,
    extra_top=None,
) -> dict:
    d: dict = {
        "case_id": "test_case_2024",
        "case_name": "Test Corp / Other Corp",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "outcome": outcome,
        "sector": "test",
        "decision_date": "2024-01-15",
        "source_documents": [{"doc_id": "test_doc"}],
        "product_markets_considered": product_markets or [],
        "geographic_markets_considered": geographic_markets or [],
        "theories_of_harm": [],
        "source_passages": passages or [],
    }
    if extra_top:
        d.update(extra_top)
    return d


def _canonical(
    *,
    outcome="cleared",
    product_markets=None,
    geographic_markets=None,
    passages=None,
) -> dict:
    return {
        "case_id": "test_case_2024",
        "case_name": "Test Corp / Other Corp",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "procedure_stage": "phase1",
        "case_type": "merger",
        "authority_reference": "M.9999",
        "outcome": outcome,
        "sector": "test",
        "decision_date": "2024-01-15",
        "source_documents": [{"doc_id": "test_doc"}],
        "product_markets_considered": product_markets or [],
        "geographic_markets_considered": geographic_markets or [],
        "theories_of_harm": [],
        "source_passages": passages or [],
        "metadata": {
            "overall_confidence": 0.7,
            "review_status": "unreviewed",
            "created_date": "2024-01-15",
        },
    }


def _market(market_id: str, definition_status: str, name: str = "Widget market", notes: str = "Some notes.") -> dict:
    return {
        "market_id": market_id,
        "name": name,
        "definition_status": definition_status,
        "notes": notes,
    }


def _draft_market(market_id: str, definition_status: str, name: str = "Widget market", notes: str = "Some notes.") -> dict:
    return {
        **_market(market_id, definition_status, name, notes),
        "verification": {"status": "source_linked"},
        "market_importance": "core_assessed",
    }


def _passage(
    passage_id: str,
    quote: str,
    supports_markets: list,
    supports_geo: list = None,
    review_status: str = "unreviewed",
    confidence: float = 0.7,
    source_role: str = None,
) -> dict:
    p: dict = {
        "passage_id": passage_id,
        "source_document_id": "test_doc",
        "page": "5",
        "quote_snippet": quote,
        "extraction_method": "pdf_extracted",
        "review_status": review_status,
        "confidence_score": confidence,
        "supports_markets": supports_markets,
        "supports_geographic_markets": supports_geo or [],
        "supports_theories": [],
    }
    if source_role is not None:
        p["source_role"] = source_role
    return p


_MARKET_DEF_QUOTE = "The Commission is of the view that widgets form a distinct product market."
_OUTCOME_QUOTE = "The Transaction does not raise serious doubts as to its compatibility with the internal market."


# ---------------------------------------------------------------------------
# _is_outcome_passage
# ---------------------------------------------------------------------------


def test_is_outcome_passage_detects_clearance():
    assert _is_outcome_passage({"quote_snippet": _OUTCOME_QUOTE})


def test_is_outcome_passage_returns_false_for_definition():
    assert not _is_outcome_passage({"quote_snippet": _MARKET_DEF_QUOTE})


def test_is_outcome_passage_case_insensitive():
    assert _is_outcome_passage({"quote_snippet": "DOES NOT RAISE SERIOUS DOUBTS about anything."})


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------


def test_norm_collapses_whitespace():
    assert _norm("  hello\n  world  ") == "hello world"


def test_norm_handles_none():
    assert _norm(None) == ""


# ---------------------------------------------------------------------------
# Metadata completion: outcome
# ---------------------------------------------------------------------------


def test_metadata_completion_outcome_unknown_to_cleared():
    draft = _draft(outcome="unknown")
    canonical = _canonical(outcome="cleared")
    corrections, summary = compute_review_delta(draft, canonical, None)
    types = [c["correction_type"] for c in corrections]
    assert "metadata_completion" in types
    outcome_corrections = [c for c in corrections if c.get("correction_type") == "metadata_completion"
                           and c.get("object_type") == "case"
                           and c.get("before", {}).get("outcome") == "unknown"]
    assert len(outcome_corrections) == 1
    assert outcome_corrections[0]["after"]["outcome"] == "cleared"
    assert outcome_corrections[0]["confidence"] == "high"
    assert outcome_corrections[0]["suggested_follow_up"] == "validator_rule"


def test_metadata_completion_promotion_fields():
    draft = _draft()
    canonical = _canonical()
    corrections, _ = compute_review_delta(draft, canonical, None)
    promo = [c for c in corrections if c.get("correction_type") == "metadata_completion"
             and c.get("object_type") == "case"
             and "procedure_stage" in (c.get("after") or {})]
    assert len(promo) == 1
    assert promo[0]["after"]["procedure_stage"] == "phase1"
    assert promo[0]["after"]["case_type"] == "merger"


def test_metadata_completion_metadata_block():
    draft = _draft()
    canonical = _canonical()
    corrections, _ = compute_review_delta(draft, canonical, None)
    meta_c = [c for c in corrections if c.get("correction_type") == "metadata_completion"
              and c.get("object_type") == "metadata"]
    assert len(meta_c) == 1
    assert meta_c[0]["before"] is None
    assert meta_c[0]["after"]["overall_confidence"] == 0.7


def test_no_outcome_correction_when_unchanged():
    draft = _draft(outcome="cleared")
    canonical = _canonical(outcome="cleared")
    corrections, _ = compute_review_delta(draft, canonical, None)
    outcome_c = [c for c in corrections
                 if isinstance(c.get("before"), dict) and c["before"].get("outcome") == "cleared"]
    assert not outcome_c


# ---------------------------------------------------------------------------
# definition_status_mapping
# ---------------------------------------------------------------------------


def test_definition_status_mapping_defined_to_considered():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined")])
    canonical = _canonical(product_markets=[_market("pm_1", "considered")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    ds_c = [c for c in corrections if c["correction_type"] == "definition_status_mapping"]
    assert len(ds_c) == 1
    assert ds_c[0]["before"] == {"definition_status": "defined"}
    assert ds_c[0]["after"] == {"definition_status": "considered"}
    assert ds_c[0]["object_id"] == "pm_1"
    assert ds_c[0]["suggested_follow_up"] == "prompt_update"
    assert "considered" in ds_c[0]["reusable_rule_candidate"].lower()


def test_definition_status_mapping_left_open():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined")])
    canonical = _canonical(product_markets=[_market("pm_1", "left_open")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    ds_c = [c for c in corrections if c["correction_type"] == "definition_status_mapping"]
    assert len(ds_c) == 1
    assert ds_c[0]["after"] == {"definition_status": "left_open"}


def test_no_definition_status_correction_when_unchanged():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined")])
    canonical = _canonical(product_markets=[_market("pm_1", "defined")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    ds_c = [c for c in corrections if c["correction_type"] == "definition_status_mapping"]
    assert not ds_c


def test_definition_status_geographic_market():
    draft = _draft(geographic_markets=[_draft_market("gm_1", "defined")])
    canonical = _canonical(geographic_markets=[_market("gm_1", "considered")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    ds_c = [c for c in corrections if c["correction_type"] == "definition_status_mapping"]
    assert len(ds_c) == 1
    assert ds_c[0]["object_type"] == "geographic_market"


# ---------------------------------------------------------------------------
# support_linkage_correction
# ---------------------------------------------------------------------------


def test_support_linkage_correction_markets_added():
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=[])])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    sl_c = [c for c in corrections if c["correction_type"] == "support_linkage_correction"]
    assert len(sl_c) == 1
    assert "pm_1" in sl_c[0]["after"]["supports_markets"]


def test_support_linkage_correction_markets_removed():
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1", "pm_2"])])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    sl_c = [c for c in corrections if c["correction_type"] == "support_linkage_correction"]
    assert len(sl_c) == 1
    assert sorted(sl_c[0]["before"]["supports_markets"]) == ["pm_1", "pm_2"]


def test_support_linkage_geographic():
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=[], supports_geo=[])])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=[], supports_geo=["gm_1"])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    sl_c = [c for c in corrections if c["correction_type"] == "support_linkage_correction"]
    assert len(sl_c) == 1
    assert "gm_1" in sl_c[0]["after"]["supports_geographic_markets"]


# ---------------------------------------------------------------------------
# outcome_passage_misuse
# ---------------------------------------------------------------------------


def test_outcome_passage_misuse_supports_markets_removed():
    draft = _draft(passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=["pm_1"])])
    canonical = _canonical(passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=[])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    opm = [c for c in corrections if c["correction_type"] == "outcome_passage_misuse"]
    assert len(opm) == 1
    assert opm[0]["suggested_follow_up"] == "validator_rule"
    assert opm[0]["confidence"] == "high"
    assert "pm_1" in opm[0]["before"]["supports_markets"]


def test_outcome_passage_misuse_not_triggered_when_added():
    """Adding market links to an outcome passage → support_linkage, not outcome_passage_misuse."""
    draft = _draft(passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=[])])
    canonical = _canonical(passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=["pm_1"])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    opm = [c for c in corrections if c["correction_type"] == "outcome_passage_misuse"]
    # Links were added (not removed) to an outcome passage — not flagged as misuse (that's unusual)
    # but classified as support_linkage_correction instead
    assert not opm


def test_non_outcome_passage_removal_is_support_linkage():
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"])])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=[])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    opm = [c for c in corrections if c["correction_type"] == "outcome_passage_misuse"]
    sl_c = [c for c in corrections if c["correction_type"] == "support_linkage_correction"]
    assert not opm
    assert len(sl_c) == 1


# ---------------------------------------------------------------------------
# Draft-only field stripping — must not produce corrections
# ---------------------------------------------------------------------------


def test_source_role_stripping_not_a_correction():
    """source_role present in draft but absent in canonical → no correction."""
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"], source_role="commission_assessment")])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"])])
    corrections, _ = compute_review_delta(draft, canonical, None)
    # Only metadata_completion corrections expected (procedure_stage etc.); no passage corrections
    passage_corrections = [c for c in corrections if c.get("object_type") == "source_passage"]
    assert not passage_corrections


def test_verification_market_importance_stripping_not_a_correction():
    """verification and market_importance in draft market but absent in canonical → no correction."""
    draft = _draft(product_markets=[_draft_market("pm_1", "defined")])
    canonical = _canonical(product_markets=[_market("pm_1", "defined")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    market_corrections = [c for c in corrections if c.get("object_type") == "product_market"]
    assert not market_corrections


def test_draft_note_stripping_not_a_correction():
    """_draft_note in top-level draft but absent in canonical → no correction."""
    draft = _draft(extra_top={"_draft_note": "DRAFT — review before promoting."})
    canonical = _canonical()
    corrections, _ = compute_review_delta(draft, canonical, None)
    draft_note_corrections = [c for c in corrections
                               if str(c.get("before", "")).find("DRAFT") >= 0]
    assert not draft_note_corrections


# ---------------------------------------------------------------------------
# missing_market_added / market_removed
# ---------------------------------------------------------------------------


def test_missing_market_added():
    draft = _draft(product_markets=[])
    canonical = _canonical(product_markets=[_market("pm_1", "defined", "Widgets")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    added = [c for c in corrections if c["correction_type"] == "missing_market_added"]
    assert len(added) == 1
    assert added[0]["after"]["market_id"] == "pm_1"
    assert added[0]["suggested_follow_up"] == "eval_fixture"


def test_market_removed():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined")])
    canonical = _canonical(product_markets=[])
    corrections, _ = compute_review_delta(draft, canonical, None)
    removed = [c for c in corrections if c["correction_type"] == "market_removed"]
    assert len(removed) == 1
    assert removed[0]["before"]["market_id"] == "pm_1"


# ---------------------------------------------------------------------------
# note_cleanup
# ---------------------------------------------------------------------------


def test_note_cleanup_detects_editorial_change():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined", notes="Analysis in this draft.")])
    canonical = _canonical(product_markets=[_market("pm_1", "defined", notes="Analysis in this record.")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    nc = [c for c in corrections if c["correction_type"] == "note_cleanup"]
    assert len(nc) == 1
    assert nc[0]["object_id"] == "pm_1"


def test_note_cleanup_ignores_whitespace_only_differences():
    draft = _draft(product_markets=[_draft_market("pm_1", "defined", notes="  Same note.  ")])
    canonical = _canonical(product_markets=[_market("pm_1", "defined", notes="Same note.")])
    corrections, _ = compute_review_delta(draft, canonical, None)
    nc = [c for c in corrections if c["correction_type"] == "note_cleanup"]
    assert not nc


# ---------------------------------------------------------------------------
# review_status / confidence_score — must NOT produce corrections (operational metadata)
# ---------------------------------------------------------------------------


def test_review_status_downgrade_not_a_correction():
    """spot_checked/0.9 → unreviewed/0.8 is an expected promotion-workflow reset, not a human correction."""
    draft = _draft(passages=[
        _passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="spot_checked", confidence=0.9)
    ])
    canonical = _canonical(passages=[
        _passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="unreviewed", confidence=0.8)
    ])
    corrections, _ = compute_review_delta(draft, canonical, None)
    passage_corrections = [c for c in corrections if c.get("object_type") == "source_passage"]
    assert not passage_corrections, (
        f"review_status/confidence diff should not produce passage corrections; got {passage_corrections}"
    )


def test_review_status_upgrade_not_a_correction():
    """unreviewed → lawyer_reviewed is also not compared in v1 (operational metadata)."""
    draft = _draft(passages=[
        _passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="unreviewed", confidence=0.6)
    ])
    canonical = _canonical(passages=[
        _passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="lawyer_reviewed", confidence=0.95)
    ])
    corrections, _ = compute_review_delta(draft, canonical, None)
    passage_corrections = [c for c in corrections if c.get("object_type") == "source_passage"]
    assert not passage_corrections


def test_sp18_to_sp23_pattern_no_false_positives():
    """Regression: sp_18–sp_23 pattern (spot_checked/0.9 → unreviewed/0.8) across multiple passages must not emit corrections."""
    passages_draft = [
        _passage(f"sp_{i}", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="spot_checked", confidence=0.9)
        for i in range(18, 24)
    ]
    passages_canon = [
        _passage(f"sp_{i}", _MARKET_DEF_QUOTE, supports_markets=["pm_1"],
                 review_status="unreviewed", confidence=0.8)
        for i in range(18, 24)
    ]
    draft = _draft(passages=passages_draft)
    canonical = _canonical(passages=passages_canon)
    corrections, summary = compute_review_delta(draft, canonical, None)
    passage_corrections = [c for c in corrections if c.get("object_type") == "source_passage"]
    assert not passage_corrections, (
        f"Expected no passage corrections for sp_18–sp_23 review_status/confidence pattern; got {passage_corrections}"
    )
    assert summary["by_type"].get("other", 0) == 0


# ---------------------------------------------------------------------------
# LLM review integration
# ---------------------------------------------------------------------------


def test_llm_review_enriches_inferred_reason():
    llm_review = {
        "triage_status": "needs_legal_review",
        "triage_rationale": "Working assumption formula used throughout.",
        "passage_reviews": [
            {
                "passage_id": "sp_1",
                "support_verdict": "partial",
                "role_verdict": "correct",
                "linked_to": ["pm_1"],
                "note": "Mixed passage — contains outcome language.",
            }
        ],
    }
    draft = _draft(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1", "pm_2"])])
    canonical = _canonical(passages=[_passage("sp_1", _MARKET_DEF_QUOTE, supports_markets=["pm_1"])])
    corrections, summary = compute_review_delta(draft, canonical, llm_review)
    sl_c = [c for c in corrections if c["correction_type"] == "support_linkage_correction"]
    assert len(sl_c) == 1
    assert "Mixed passage" in sl_c[0]["inferred_reason"]
    assert summary["llm_triage_status"] == "needs_legal_review"


def test_llm_review_insights_in_summary():
    llm_review = {
        "triage_status": "auto_verified_candidate",
        "triage_rationale": "All passages cleanly categorised.",
        "passage_reviews": [],
    }
    draft = _draft(outcome="cleared")
    canonical = _canonical(outcome="cleared")
    _, summary = compute_review_delta(draft, canonical, llm_review)
    assert summary["llm_triage_status"] == "auto_verified_candidate"


# ---------------------------------------------------------------------------
# summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_by_type():
    draft = _draft(
        outcome="unknown",
        product_markets=[_draft_market("pm_1", "defined")],
        passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=["pm_1"])],
    )
    canonical = _canonical(
        outcome="cleared",
        product_markets=[_market("pm_1", "considered")],
        passages=[_passage("sp_1", _OUTCOME_QUOTE, supports_markets=[])],
    )
    corrections, summary = compute_review_delta(draft, canonical, None)
    assert summary["by_type"]["metadata_completion"] >= 1
    assert summary["by_type"]["definition_status_mapping"] == 1
    assert summary["by_type"]["outcome_passage_misuse"] == 1
    assert summary["total_corrections"] == sum(summary["by_type"].values())


# ---------------------------------------------------------------------------
# end-to-end: build_review_log writes a valid YAML file
# ---------------------------------------------------------------------------


def test_build_review_log_writes_output(tmp_path):
    # Write minimal draft and canonical YAML files
    draft_dir = tmp_path / "drafts" / "eu"
    draft_dir.mkdir(parents=True)
    canonical_dir = tmp_path / "cases" / "eu"
    canonical_dir.mkdir(parents=True)
    output_dir = tmp_path / "review_learning"

    case_id = "eu_test_case_2024"
    focus = "market_definition"

    draft_data = _draft(outcome="unknown")
    draft_data["case_id"] = case_id
    canonical_data = _canonical(outcome="cleared")
    canonical_data["case_id"] = case_id

    draft_path = draft_dir / f"{case_id}.{focus}.draft.yaml"
    canonical_path = canonical_dir / f"{case_id}.yaml"
    output_path = output_dir / f"{case_id}.{focus}.review_delta.yaml"

    draft_path.write_text(yaml.dump(draft_data))
    canonical_path.write_text(yaml.dump(canonical_data))

    result_path, log = build_review_log(
        case_id=case_id,
        focus=focus,
        draft_path=draft_path,
        canonical_path=canonical_path,
        output_path=output_path,
    )

    assert result_path == output_path
    assert output_path.exists()
    written = yaml.safe_load(output_path.read_text())
    assert written["case_id"] == case_id
    assert written["focus"] == focus
    assert written["schema_version"] == "1"
    assert "generated_at" in written
    assert isinstance(written["corrections"], list)
    assert written["summary"]["total_corrections"] > 0


def test_build_review_log_raises_on_missing_draft(tmp_path):
    canonical_path = tmp_path / "eu_test.yaml"
    canonical_path.write_text(yaml.dump({"case_id": "eu_test"}))
    with pytest.raises(FileNotFoundError, match="Draft not found"):
        build_review_log(
            case_id="eu_test",
            focus="market_definition",
            draft_path=tmp_path / "nonexistent.yaml",
            canonical_path=canonical_path,
            output_path=tmp_path / "out.yaml",
        )


def test_build_review_log_raises_on_missing_canonical(tmp_path):
    draft_path = tmp_path / "eu_test.draft.yaml"
    draft_path.write_text(yaml.dump({"case_id": "eu_test"}))
    with pytest.raises(FileNotFoundError, match="Canonical case not found"):
        build_review_log(
            case_id="eu_test",
            focus="market_definition",
            draft_path=draft_path,
            canonical_path=tmp_path / "nonexistent.yaml",
            output_path=tmp_path / "out.yaml",
        )
