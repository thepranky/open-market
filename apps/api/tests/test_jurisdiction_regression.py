"""Tests for gold deal regression suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.jurisdiction_regression import load_gold_deals, run_gold_deal

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
