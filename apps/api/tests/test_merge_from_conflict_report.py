"""
Tests for merge_drafts.merge_from_conflict_report (dual extraction, ROADMAP 5.9).

Covers:
  - Unresolved conflict blocks the merge (ValueError)
  - value_mismatch resolution overwrites the field on the right market
  - rename_candidate resolution renames the aligned market (located by A-name even
    though the conflict path uses B-name)
  - auto_resolved name is applied
  - top-level record scalar (outcome) resolution is applied
  - a_only: drop removes the A-only market; keep (default) retains it
  - b_only: keep adds B's market AND its supporting passages, with id-collision
    handling; drop (default) omits it
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract.merge_drafts import merge_from_conflict_report


def _market(mid, name, status="defined", importance="core_assessed"):
    return {"market_id": mid, "name": name,
            "definition_status": status, "market_importance": importance}


def _draft(products, outcome="cleared", geo=None, passages=None):
    return {
        "case_id": "eu_test_2023",
        "outcome": outcome,
        "product_markets_considered": products,
        "geographic_markets_considered": geo or [],
        "theories_of_harm": [],
        "source_passages": passages or [],
    }


def _report(conflicts, auto_resolved=None, focus="market_definition"):
    return {"conflict_report": {
        "case_id": "eu_test_2023", "focus": focus,
        "models": {"draft_a": "anthropic/x", "draft_b": "gemini/y", "same_model": False},
        "agreed_fields": [],
        "conflicts": conflicts,
        "auto_resolved": auto_resolved or [],
    }}


def test_unresolved_conflict_blocks():
    a = _draft([_market("pm_1", "Cement", status="defined")])
    b = _draft([_market("pm_9", "Cement", status="discussed")])
    report = _report([{
        "field": "product_markets/Cement/definition_status", "kind": "value_mismatch",
        "draft_a": "defined", "draft_b": "discussed", "resolution": None,
    }])
    try:
        merge_from_conflict_report(a, b, report, focus="market_definition")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unresolved" in str(exc).lower()


def test_value_mismatch_resolution_applied():
    a = _draft([_market("pm_1", "Cement", status="defined")])
    b = _draft([_market("pm_9", "Cement", status="discussed")])
    report = _report([{
        "field": "product_markets/Cement/definition_status", "kind": "value_mismatch",
        "draft_a": "defined", "draft_b": "discussed", "resolution": "discussed",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    assert merged["product_markets_considered"][0]["definition_status"] == "discussed"


def test_rename_resolution_locates_market_by_a_name():
    # Aligned-but-renamed pair: A="…supply", B="…distribution"; conflict path uses B name.
    a = _draft([_market("pm_1", "Ready-mix concrete supply")])
    b = _draft([_market("pm_9", "Ready-mix concrete distribution")])
    report = _report([{
        "field": "product_markets/Ready-mix concrete distribution/name",
        "kind": "rename_candidate",
        "draft_a": "Ready-mix concrete supply",
        "draft_b": "Ready-mix concrete distribution",
        "resolution": "Ready-mix concrete",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    assert merged["product_markets_considered"][0]["name"] == "Ready-mix concrete"


def test_auto_resolved_name_applied():
    a = _draft([_market("pm_1", "Mortar — Germany")])
    b = _draft([_market("pm_1", "Mortar — DE")])
    report = _report([], auto_resolved=[{
        "field": "product_markets/Mortar — DE/name",
        "draft_a": "Mortar — Germany", "draft_b": "Mortar — DE",
        "resolved_to": "Mortar — Germany", "resolved_by": "auto",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    assert merged["product_markets_considered"][0]["name"] == "Mortar — Germany"


def test_top_level_outcome_resolution():
    a = _draft([_market("pm_1", "Cement")], outcome="cleared")
    b = _draft([_market("pm_1", "Cement")], outcome="blocked")
    report = _report([{
        "field": "outcome", "kind": "value_mismatch",
        "draft_a": "cleared", "draft_b": "blocked", "resolution": "blocked",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    assert merged["outcome"] == "blocked"


def test_a_only_drop_removes_market():
    a = _draft([_market("pm_1", "Cement"), _market("pm_2", "Mortar additives")])
    b = _draft([_market("pm_1", "Cement")])
    report = _report([{
        "field": "product_markets", "kind": "a_only",
        "draft_a": "Mortar additives", "draft_b": None, "resolution": "drop",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    names = [m["name"] for m in merged["product_markets_considered"]]
    assert names == ["Cement"]


def test_a_only_keep_retains_market():
    a = _draft([_market("pm_1", "Cement"), _market("pm_2", "Mortar additives")])
    b = _draft([_market("pm_1", "Cement")])
    report = _report([{
        "field": "product_markets", "kind": "a_only",
        "draft_a": "Mortar additives", "draft_b": None, "resolution": "keep",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    names = {m["name"] for m in merged["product_markets_considered"]}
    assert names == {"Cement", "Mortar additives"}


def test_b_only_keep_adds_market_and_passages_with_id_collision():
    # B's extra "Slag" market reuses id "pm_1", which collides with A's "pm_1"
    # (Cement) — it must be rewritten to a fresh id and B's supporting passage ref
    # updated to match, so the kept market stays correctly grounded.
    a = _draft([_market("pm_1", "Cement")])
    b = _draft(
        [_market("pm_1", "Cement"), _market("pm_1", "Slag")],  # id collision on pm_1
        passages=[{
            "passage_id": "sp_b1", "quote_snippet": "...slag...",
            "page": 12, "source_document_id": "doc_1",
            "supports_markets": ["pm_1"],
        }],
    )
    report = _report([{
        "field": "product_markets", "kind": "b_only",
        "draft_a": None, "draft_b": "Slag", "resolution": "keep",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    names = {m["name"] for m in merged["product_markets_considered"]}
    assert names == {"Cement", "Slag"}
    slag = next(m for m in merged["product_markets_considered"] if m["name"] == "Slag")
    # Rewritten to a fresh, non-colliding id...
    assert slag["market_id"] != "pm_1"
    # ...and the copied passage points at the new id, not Cement's pm_1.
    assert merged["source_passages"][0]["supports_markets"] == [slag["market_id"]]


def test_unrecognized_keep_drop_resolution_raises():
    # A non-empty but unparseable keep/drop resolution must block, not silently
    # default (which would drop a B-only market the human meant to keep).
    a = _draft([_market("pm_1", "Cement")])
    b = _draft([_market("pm_1", "Cement"), _market("pm_2", "Slag")])
    report = _report([{
        "field": "product_markets", "kind": "b_only",
        "draft_a": None, "draft_b": "Slag", "resolution": "yes please keep it",
    }])
    try:
        merge_from_conflict_report(a, b, report, focus="market_definition")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unrecognized resolution" in str(exc).lower()


def test_unlocatable_resolved_conflict_raises():
    # A resolved value_mismatch whose market is not present in Draft A must raise,
    # not silently discard the resolution.
    a = _draft([_market("pm_1", "Cement")])
    b = _draft([_market("pm_1", "Cement")])
    report = _report([{
        "field": "product_markets/Nonexistent/definition_status",
        "kind": "value_mismatch", "draft_a": "defined", "draft_b": "discussed",
        "resolution": "discussed",
    }])
    try:
        merge_from_conflict_report(a, b, report, focus="market_definition")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "could not be located" in str(exc).lower()


def test_b_only_keep_drops_dangling_multimarket_passage_ref():
    # A copied B passage that also supports a B market we did NOT keep must not
    # carry that dangling ref into the merged record.
    a = _draft([_market("pm_1", "Cement")])
    b = _draft(
        [_market("pm_1", "Cement"), _market("pm_2", "Slag"), _market("pm_3", "Other")],
        passages=[{
            "passage_id": "sp_b1", "quote_snippet": "...slag and other...",
            "page": 12, "source_document_id": "doc_1",
            "supports_markets": ["pm_2", "pm_3"],  # pm_3 is NOT kept
        }],
    )
    report = _report([{
        "field": "product_markets", "kind": "b_only",
        "draft_a": None, "draft_b": "Slag", "resolution": "keep",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    slag = next(m for m in merged["product_markets_considered"] if m["name"] == "Slag")
    # Only the kept market's ref survives; the dangling pm_3 ref is dropped.
    assert merged["source_passages"][0]["supports_markets"] == [slag["market_id"]]


def test_b_only_keep_two_markets_sharing_one_passage():
    # A B passage grounds two B-only markets, both kept. The shared passage must
    # end up referencing BOTH merged markets, not just the first one copied.
    a = _draft([_market("pm_1", "Cement")])
    b = _draft(
        [_market("pm_1", "Cement"), _market("pm_2", "Slag"), _market("pm_3", "Other")],
        passages=[{
            "passage_id": "sp_b1", "quote_snippet": "...slag and other...",
            "page": 12, "source_document_id": "doc_1",
            "supports_markets": ["pm_2", "pm_3"],
        }],
    )
    report = _report([
        {"field": "product_markets", "kind": "b_only",
         "draft_a": None, "draft_b": "Slag", "resolution": "keep"},
        {"field": "product_markets", "kind": "b_only",
         "draft_a": None, "draft_b": "Other", "resolution": "keep"},
    ])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    slag = next(m for m in merged["product_markets_considered"] if m["name"] == "Slag")
    other = next(m for m in merged["product_markets_considered"] if m["name"] == "Other")
    # Exactly one copy of the shared passage, grounding both kept markets.
    shared = [sp for sp in merged["source_passages"] if sp["passage_id"] == "sp_b1"]
    assert len(shared) == 1
    assert set(shared[0]["supports_markets"]) == {slag["market_id"], other["market_id"]}


def test_b_only_drop_omits_market():
    a = _draft([_market("pm_1", "Cement")])
    b = _draft([_market("pm_1", "Cement"), _market("pm_2", "Slag")])
    report = _report([{
        "field": "product_markets", "kind": "b_only",
        "draft_a": None, "draft_b": "Slag", "resolution": "drop",
    }])
    merged = merge_from_conflict_report(a, b, report, focus="market_definition")
    names = {m["name"] for m in merged["product_markets_considered"]}
    assert names == {"Cement"}
    assert merged["source_passages"] == []
