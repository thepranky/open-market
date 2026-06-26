"""
Tests for calibrate_dual_extraction.py (dual extraction calibration gate, ROADMAP 5.9).

Drive the pure scoring functions directly (no model calls). Cover the cases that
distinguish the two metrics:
  - Both drafts agree and are correct → counts toward precision numerator, no error.
  - Both drafts wrong the SAME way → agreed-but-wrong (precision miss) AND a blind
    spot (error not raised) — the load-bearing failure the gate exists to catch.
  - One draft wrong, they disagree → error raised → conflict recall credit.
  - One draft missing the gold market entirely → raised (b_only-style), recall credit.
  - Gold's `expected_definition_status` is read as the draft's `definition_status`.
  - Partial golds score only `reviewed` markets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract.calibrate_dual_extraction import score_case


def _draft_market(name, status="defined"):
    return {"name": name, "definition_status": status, "market_importance": "core_assessed"}


def _draft(product_markets):
    return {
        "case_id": "eu_test_2023",
        "product_markets_considered": product_markets,
        "geographic_markets_considered": [],
        "theories_of_harm": [],
    }


def _gold_market(name, expected_status="defined", reviewed=True):
    return {"name": name, "expected_definition_status": expected_status, "reviewed": reviewed}


def _gold(product_markets, partial=False):
    return {
        "_gold_metadata": {"partial": partial},
        "product_markets_considered": product_markets,
        "geographic_markets_considered": [],
        "theories_of_harm": [],
    }


def test_agree_and_correct_is_clean():
    a = _draft([_draft_market("Cement", "defined")])
    b = _draft([_draft_market("Cement", "defined")])
    gold = _gold([_gold_market("Cement", "defined")])

    s = score_case(a, b, gold)

    assert s["agreed"] == s["agreed_correct"]  # everything agreed matches gold
    assert s["agreed"] >= 2  # name + definition_status
    assert s["error"] == 0
    assert s["bad_agreements"] == []
    assert s["blind_spots"] == []


def test_both_wrong_same_way_is_blind_spot():
    # Gold says discussed; both drafts say defined → they agree on the wrong value.
    a = _draft([_draft_market("Cement", "defined")])
    b = _draft([_draft_market("Cement", "defined")])
    gold = _gold([_gold_market("Cement", "discussed")])

    s = score_case(a, b, gold)

    # definition_status: agreed but wrong → precision miss + blind spot (not raised).
    assert any(bad["field"].endswith("/definition_status") for bad in s["bad_agreements"])
    assert any(bs["field"].endswith("/definition_status") for bs in s["blind_spots"])
    assert s["error_raised"] == 0  # nothing was raised — the dangerous case


def test_disagreement_is_raised():
    a = _draft([_draft_market("Cement", "defined")])
    b = _draft([_draft_market("Cement", "discussed")])
    gold = _gold([_gold_market("Cement", "defined")])

    s = score_case(a, b, gold)

    # A correct, B wrong, they disagree → error raised, recall credit, no blind spot.
    assert s["error"] == 1
    assert s["error_raised"] == 1
    assert s["blind_spots"] == []


def test_missing_market_is_raised():
    a = _draft([_draft_market("Cement", "defined")])
    b = _draft([])  # B never found the gold market
    gold = _gold([_gold_market("Cement", "defined")])

    s = score_case(a, b, gold)

    # B missing the market → each gold field for it is an error, all raised.
    assert s["error"] >= 2
    assert s["error_raised"] == s["error"]
    assert s["blind_spots"] == []


def test_both_missing_market_is_blind_spot():
    a = _draft([])
    b = _draft([])
    gold = _gold([_gold_market("Cement", "defined")])

    s = score_case(a, b, gold)

    # Neither draft found it → wrong but never surfaced as a conflict.
    assert s["error"] >= 2
    assert s["error_raised"] == 0
    assert len(s["blind_spots"]) == s["error"]


def test_partial_gold_scores_only_reviewed():
    a = _draft([_draft_market("Cement", "defined")])
    b = _draft([_draft_market("Cement", "defined")])
    gold = _gold(
        [
            _gold_market("Cement", "defined", reviewed=True),
            _gold_market("Unreviewed widget", "defined", reviewed=False),
        ],
        partial=True,
    )

    s = score_case(a, b, gold, is_partial=True)

    # The unreviewed gold market contributes no fields → no error for the missing one.
    assert s["error"] == 0
    assert s["agreed_correct"] == s["agreed"]
