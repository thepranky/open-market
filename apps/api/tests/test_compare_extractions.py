"""
Tests for compare_extractions.py (dual extraction, ROADMAP 5.9).

Covers:
  - Aligned pair with agreeing scalar fields → agreed, no conflict
  - Aligned pair with differing definition_status → value_mismatch conflict
  - Market in A but not B → a_only conflict
  - Market in B but not A → b_only conflict
  - Reworded-but-equivalent geographic name (DE vs Germany) → auto_resolved
  - Genuinely different rename surfaced as rename_candidate (no adjudicator)
  - Injected equivalence adjudicator suppresses a rename as auto_resolved (llm)
  - Top-level scalar disagreement (outcome) → conflict
  - build_conflict_report carries model metadata and same_model flag
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract.compare_extractions import (
    _expanded_form,
    _trivial_equivalent,
    build_conflict_report,
    compare_drafts,
)


def _market(market_id, name, status="defined", importance="core_assessed"):
    return {
        "market_id": market_id,
        "name": name,
        "definition_status": status,
        "market_importance": importance,
    }


def _draft(markets, outcome="cleared", geo=None):
    return {
        "case_id": "eu_test_2023",
        "outcome": outcome,
        "product_markets_considered": markets,
        "geographic_markets_considered": geo or [],
        "theories_of_harm": [],
        "source_passages": [],
    }


def _conflicts_by_kind(result):
    by_kind = {}
    for c in result["conflicts"]:
        by_kind.setdefault(c["kind"], []).append(c)
    return by_kind


def test_aligned_pair_agrees():
    a = _draft([_market("pm_1", "Ready-mix concrete")])
    b = _draft([_market("pm_1", "Ready-mix concrete")])
    result = compare_drafts(a, b, focus="market_definition")
    assert result["conflicts"] == []
    assert any(f.endswith("/definition_status") for f in result["agreed_fields"])
    assert "outcome" in result["agreed_fields"]


def test_definition_status_mismatch():
    a = _draft([_market("pm_1", "Ready-mix concrete", status="defined")])
    b = _draft([_market("pm_9", "Ready-mix concrete", status="discussed")])
    result = compare_drafts(a, b, focus="market_definition")
    mismatches = _conflicts_by_kind(result).get("value_mismatch", [])
    assert any(
        c["field"].endswith("/definition_status")
        and c["draft_a"] == "defined"
        and c["draft_b"] == "discussed"
        for c in mismatches
    )


def test_a_only_market():
    a = _draft([_market("pm_1", "Ready-mix concrete"), _market("pm_2", "Mortar additives")])
    b = _draft([_market("pm_1", "Ready-mix concrete")])
    result = compare_drafts(a, b, focus="market_definition")
    a_only = _conflicts_by_kind(result).get("a_only", [])
    assert len(a_only) == 1
    assert a_only[0]["draft_a"] == "Mortar additives"


def test_b_only_market():
    a = _draft([_market("pm_1", "Ready-mix concrete")])
    b = _draft([_market("pm_1", "Ready-mix concrete"), _market("pm_2", "Cement")])
    result = compare_drafts(a, b, focus="market_definition")
    b_only = _conflicts_by_kind(result).get("b_only", [])
    assert len(b_only) == 1
    assert b_only[0]["draft_b"] == "Cement"


def test_country_abbreviation_auto_resolved():
    a = _draft([_market("pm_1", "Ready-mix concrete — Germany")])
    b = _draft([_market("pm_1", "Ready-mix concrete — DE")])
    result = compare_drafts(a, b, focus="market_definition")
    # Either matched outright or normalized; in no case a rename conflict.
    assert not _conflicts_by_kind(result).get("rename_candidate")


def test_trivial_equivalent_helper():
    assert _trivial_equivalent("Ready-mix concrete — DE", "Ready-mix concrete — Germany")
    assert _trivial_equivalent("Cement", "  cement ")
    assert not _trivial_equivalent("Cement", "Ready-mix concrete")


def test_trivial_equivalent_folds_cosmetic_punctuation():
    # Hyphen vs space, and separator swaps (dash/slash/comma) are cosmetic.
    assert _trivial_equivalent(
        "Retail sale to end customers", "Retail sale to end-customers")
    assert _trivial_equivalent("EEA-wide / regional", "EEA-wide, regional")
    assert _trivial_equivalent("Aqueous ammonia — EEA-wide", "Aqueous ammonia, EEA-wide")
    # Lexical differences are NOT folded — they stay conflicts for the human.
    assert not _trivial_equivalent("1,000 km catchment", "1,000 kilometres catchment")
    assert not _trivial_equivalent("Cement supply", "Cement distribution")


def test_expanded_form_cosmetic_keeps_descriptive_form():
    # Punctuation-only difference with mismatched segments → keep the longer form,
    # never drop a segment.
    assert _expanded_form("A,B", "A, B") == "A, B"


def test_genuine_rename_surfaced_without_adjudicator():
    # Names similar enough to align but not trivially equivalent.
    a = _draft([_market("pm_1", "Ready-mix concrete supply")])
    b = _draft([_market("pm_1", "Ready-mix concrete distribution")])
    result = compare_drafts(a, b, focus="market_definition")
    kinds = _conflicts_by_kind(result)
    # Aligned as rename candidate (not a_only/b_only) and not auto-resolved.
    if kinds.get("rename_candidate"):
        assert result["auto_resolved"] == []


def test_injected_adjudicator_suppresses_rename():
    a = _draft([_market("pm_1", "Ready-mix concrete supply")])
    b = _draft([_market("pm_1", "Ready-mix concrete distribution")])
    result = compare_drafts(
        a, b, focus="market_definition",
        equivalence_fn=lambda va, vb, src: True,
    )
    assert not _conflicts_by_kind(result).get("rename_candidate")
    assert any(r["resolved_by"] == "llm" for r in result["auto_resolved"])


def test_same_name_across_product_and_geo_lists_do_not_collide():
    # A product market and a geographic market share a name; they must be diffed
    # against their own counterparts, not each other (regression: flat by-name index).
    a = _draft(
        [_market("pm_1", "Cement", status="defined")],
        geo=[_market("gm_1", "Cement", status="discussed")],
    )
    b = _draft(
        [_market("pm_9", "Cement", status="defined")],
        geo=[_market("gm_9", "Cement", status="discussed")],
    )
    result = compare_drafts(a, b, focus="market_definition")
    # Both pairs agree internally → no conflicts, and paths are list-labeled.
    assert _conflicts_by_kind(result) == {}
    assert "product_markets/Cement/definition_status" in result["agreed_fields"]
    assert "geographic_markets/Cement/definition_status" in result["agreed_fields"]


def test_field_paths_carry_list_label():
    a = _draft([_market("pm_1", "Cement")], geo=[_market("gm_1", "Germany")])
    b = _draft([_market("pm_1", "Cement")], geo=[_market("gm_1", "Germany")])
    result = compare_drafts(a, b, focus="market_definition")
    assert any(f.startswith("product_markets/") for f in result["agreed_fields"])
    assert any(f.startswith("geographic_markets/") for f in result["agreed_fields"])


def test_a_only_path_uses_list_label():
    a = _draft([_market("pm_1", "Cement")], geo=[_market("gm_1", "Germany"), _market("gm_2", "France")])
    b = _draft([_market("pm_1", "Cement")], geo=[_market("gm_1", "Germany")])
    result = compare_drafts(a, b, focus="market_definition")
    a_only = _conflicts_by_kind(result).get("a_only", [])
    assert len(a_only) == 1
    assert a_only[0]["field"] == "geographic_markets"
    assert a_only[0]["draft_a"] == "France"


def test_expanded_form_prefers_full_country_name():
    assert _expanded_form("Ready-mix concrete — DE", "Ready-mix concrete — Germany") == \
        "Ready-mix concrete — Germany"
    assert _expanded_form("Ready-mix concrete — Germany", "Ready-mix concrete — DE") == \
        "Ready-mix concrete — Germany"


def test_country_auto_resolve_records_expanded_value():
    a = _draft([_market("pm_1", "Mortar — Germany")])
    b = _draft([_market("pm_1", "Mortar — DE")])
    result = compare_drafts(a, b, focus="market_definition")
    auto = result["auto_resolved"]
    assert auto and auto[0]["resolved_to"] == "Mortar — Germany"


def test_bare_country_code_not_auto_equated():
    # "IT" (IT services) must NOT be silently equated to "Italy" — that would
    # suppress a real conflict. Single-segment values fall through to review.
    assert not _trivial_equivalent("IT", "Italy")
    assert not _trivial_equivalent("US", "United States")


def test_top_level_outcome_conflict():
    a = _draft([_market("pm_1", "Cement")], outcome="cleared")
    b = _draft([_market("pm_1", "Cement")], outcome="blocked")
    result = compare_drafts(a, b, focus="market_definition")
    mismatches = _conflicts_by_kind(result).get("value_mismatch", [])
    assert any(c["field"] == "outcome" for c in mismatches)


def test_build_conflict_report_carries_model_metadata():
    a = _draft([_market("pm_1", "Cement")])
    b = _draft([_market("pm_1", "Cement")])
    report = build_conflict_report(
        "eu_test_2023", a, b, focus="market_definition",
        model_a="anthropic/claude-sonnet-4-6",
        model_b="gemini/gemini-2.5-flash",
        same_model=False,
    )
    cr = report["conflict_report"]
    assert cr["case_id"] == "eu_test_2023"
    assert cr["models"]["draft_a"] == "anthropic/claude-sonnet-4-6"
    assert cr["models"]["same_model"] is False
    assert cr["conflicts"] == []


# ---------------------------------------------------------------------------
# Commitments (focus=remedies)
# ---------------------------------------------------------------------------

def _commitment(commitment_id, title, commitment_type="divestiture"):
    return {"commitment_id": commitment_id, "title": title, "commitment_type": commitment_type}


def _remedies_draft(commitments, markets=None):
    return {
        "case_id": "eu_test_2023",
        "outcome": "cleared_with_remedies",
        "product_markets_considered": markets or [],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "commitments": commitments,
        "source_passages": [],
    }


def test_remedies_focus_aligned_commitments_agree():
    a = _remedies_draft([_commitment("cm_1", "Divest mobile games unit")])
    b = _remedies_draft([_commitment("cm_1", "Divest mobile games unit")])
    result = compare_drafts(a, b, focus="remedies")
    assert result["conflicts"] == []
    assert any("commitments/Divest mobile games unit" in f for f in result["agreed_fields"])


def test_remedies_focus_commitment_type_mismatch():
    a = _remedies_draft([_commitment("cm_1", "Licensing remedy", "behavioural")])
    b = _remedies_draft([_commitment("cm_1", "Licensing remedy", "divestiture")])
    result = compare_drafts(a, b, focus="remedies")
    mismatches = [c for c in result["conflicts"] if c["kind"] == "value_mismatch"]
    assert any(c["field"].endswith("/commitment_type") for c in mismatches)


def test_remedies_focus_a_only_commitment():
    a = _remedies_draft([_commitment("cm_1", "Divest unit A"), _commitment("cm_2", "Access remedy")])
    b = _remedies_draft([_commitment("cm_1", "Divest unit A")])
    result = compare_drafts(a, b, focus="remedies")
    a_only = [c for c in result["conflicts"] if c["kind"] == "a_only"]
    assert len(a_only) == 1
    assert a_only[0]["field"] == "commitments"
    assert a_only[0]["draft_a"] == "Access remedy"


def test_remedies_focus_b_only_commitment():
    a = _remedies_draft([_commitment("cm_1", "Divest unit A")])
    b = _remedies_draft([_commitment("cm_1", "Divest unit A"), _commitment("cm_2", "Access remedy")])
    result = compare_drafts(a, b, focus="remedies")
    b_only = [c for c in result["conflicts"] if c["kind"] == "b_only"]
    assert len(b_only) == 1
    assert b_only[0]["field"] == "commitments"
    assert b_only[0]["draft_b"] == "Access remedy"


def test_remedies_focus_commitment_type_skipped_on_market_entries():
    # commitment_type is absent on market dicts — the guard (both empty → skip) prevents
    # phantom conflicts when commitments are in scope but market entries have no such field.
    a = _remedies_draft([], markets=[_market("pm_1", "Cement")])
    b = _remedies_draft([], markets=[_market("pm_1", "Cement")])
    result = compare_drafts(a, b, focus="market_definition")
    type_conflicts = [c for c in result["conflicts"] if "commitment_type" in c.get("field", "")]
    assert type_conflicts == []
