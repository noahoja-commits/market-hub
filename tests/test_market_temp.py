"""Tests for lib/market_temp.py — the buyer/seller temperature gauge."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.market_temp import market_temperature


def test_buyers_market():
    # Slower sales + more inventory + sellers conceding → buyer's market.
    t = market_temperature(
        days_pending_now=45, days_pending_yr_ago=30,   # +50% slower
        inventory_now=8000, inventory_yr_ago=6000,     # +33% more
        sale_to_list_now=0.97, sale_to_list_yr_ago=1.01,
    )
    assert t.score < -15
    assert "buyer" in t.label.lower()


def test_sellers_market():
    # Faster sales + less inventory + bidding above list → seller's market.
    t = market_temperature(
        days_pending_now=18, days_pending_yr_ago=28,
        inventory_now=4000, inventory_yr_ago=6000,
        sale_to_list_now=1.02, sale_to_list_yr_ago=0.99,
    )
    assert t.score > 15
    assert "seller" in t.label.lower()


def test_balanced_market():
    t = market_temperature(
        days_pending_now=30, days_pending_yr_ago=30,
        inventory_now=6000, inventory_yr_ago=6000,
        sale_to_list_now=0.99, sale_to_list_yr_ago=0.99,
    )
    assert -15 < t.score < 15
    assert t.label == "Balanced market"


def test_no_data():
    t = market_temperature(None, None, None, None, None, None)
    assert t.score == 0.0
    assert "Unknown" in t.label


def test_partial_data_still_scores():
    # Only days-to-pending available — still produces a score.
    t = market_temperature(40, 30, None, None, None, None)
    assert t.score < 0
    assert len(t.reasons) == 1


def test_score_clamped():
    # Extreme inputs must not blow past the bounds.
    t = market_temperature(200, 10, 50000, 1000, 0.5, 1.2)
    assert -100 <= t.score <= 100
