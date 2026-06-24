"""Tests for gold deal regression suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.screening.services.jurisdiction_regression import (
    _extract_from_passages,
    diff_reextract,
    load_gold_deals,
    run_gold_deal,
)
from app.screening.services.threshold_engine import load_jurisdiction

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
GOLD_PATH = DATA_DIR / "_gold_deals.yaml"


@pytest.mark.parametrize("deal_id", [d.deal_id for d in load_gold_deals(GOLD_PATH)])
def test_gold_deal_regression(deal_id: str):
    deals = {d.deal_id: d for d in load_gold_deals(GOLD_PATH)}
    deal = deals[deal_id]
    mismatches = run_gold_deal(deal, DATA_DIR)
    assert not mismatches, f"{deal_id}: {mismatches}"


def test_gold_deal_count():
    deals = load_gold_deals(GOLD_PATH)
    assert len(deals) >= 15


def test_diff_reextract_passes_for_grounded_jurisdiction():
    # UK turnover (£70 million) is stated verbatim in its passage, so the
    # passage re-extraction must agree with the YAML threshold value.
    rule = load_jurisdiction("uk", str(DATA_DIR))
    report = diff_reextract(rule)
    assert report.passed, [m.message for m in report.mismatches]


def test_extract_from_passages_picks_closest_value():
    # A passage that mentions several figures must resolve to the one matching
    # the condition value, not merely the first number encountered.
    rule = load_jurisdiction("de", str(DATA_DIR))
    extracted = _extract_from_passages(rule)
    assert extracted["de_combined_worldwide"] == 500_000_000.0
