"""Tests for lib/brief.py — the rule-based Market Brief generator."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.brief import MarketSnapshot, generate_brief


def _base(**kw) -> MarketSnapshot:
    defaults = dict(
        label="Test Metro",
        median_value=350_000, value_yoy=4.0,
        median_rent=2_100, rent_yoy=3.0,
        gross_yield=7.2,
        mortgage_rate=6.5, mortgage_4w_bps=2.0,
        unemployment=4.5, unemployment_yr_ago=4.4,
        permits_latest=10_000, permits_prior=9_500,
        permits_latest_year=2025,
        county_caps={"Alpha": 8.0, "Beta": 6.5},
        county_values={"Alpha": 300_000, "Beta": 420_000},
    )
    defaults.update(kw)
    return MarketSnapshot(**defaults)


def test_state_line_has_core_figures():
    b = generate_brief(_base())
    assert "Test Metro" in b.state
    assert "$350K" in b.state
    assert "6.50%" in b.state


def test_yields_compressing_when_value_outpaces_rent():
    b = generate_brief(_base(value_yoy=8.0, rent_yoy=2.0))
    joined = " ".join(b.happening)
    assert "compressing" in joined


def test_yields_expanding_when_rent_outpaces_value():
    b = generate_brief(_base(value_yoy=1.0, rent_yoy=6.0))
    joined = " ".join(b.happening)
    assert "expanding" in joined


def test_rising_rates_flagged():
    b = generate_brief(_base(mortgage_4w_bps=25.0))
    assert any("tightening" in h for h in b.happening)


def test_best_cap_rate_county_in_tactics():
    b = generate_brief(_base())
    # Alpha has the higher cap rate (8.0 vs 6.5)
    assert any("Alpha" in t for t in b.tactics)


def test_healthy_yield_recommends_buy_and_hold():
    b = generate_brief(_base(gross_yield=7.5))
    assert any("buy-and-hold" in t for t in b.tactics)


def test_thin_yield_recommends_forced_equity():
    b = generate_brief(_base(gross_yield=4.8))
    assert any("forced-equity" in t for t in b.tactics)


def test_softening_market_when_both_negative():
    b = generate_brief(_base(value_yoy=-2.0, rent_yoy=-1.0))
    assert any("softening" in h for h in b.happening)


def test_permits_rising_flagged_as_supply_headwind():
    b = generate_brief(_base(permits_latest=12_000, permits_prior=9_000))
    assert any("supply pipeline is expanding" in h for h in b.happening)
