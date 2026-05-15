"""Unit tests for lib/deal_math.py — pure math, no IO."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.deal_math import (
    brrrr_refinance,
    cap_rate,
    mao_70,
    piti,
    price_to_rent,
)


def test_cap_rate_basic():
    cr = cap_rate(price=300_000, monthly_rent=2_000)
    assert cr is not None
    assert round(cr.gross, 2) == 8.0  # 24000 / 300000 = 8%
    assert round(cr.net, 2) == 4.8  # 24000 * 0.6 / 300000


def test_cap_rate_invalid():
    assert cap_rate(0, 1000) is None
    assert cap_rate(300_000, -1) is None


def test_piti_30yr_7pct():
    # 100k loan @ 7% / 30yr → ~$665.30 P&I + taxes + insurance
    payment = piti(
        price=125_000, down_pct=0.2, rate_pct=7.0,
        taxes_pct=0.012, insurance_annual=2400,
    )
    assert payment is not None
    # loan = 100k. P&I ≈ 665.30. Taxes = 125000 * 0.012 / 12 = 125. Insurance = 200. Total ≈ 990.30.
    assert 980 < payment < 1000


def test_piti_invalid():
    assert piti(0, 0.2, 7) is None
    assert piti(300_000, 1.0, 7) is None  # 100% down
    assert piti(300_000, 0.2, 0) is None


def test_price_to_rent():
    assert round(price_to_rent(300_000, 2_000), 2) == 12.5
    assert price_to_rent(0, 1000) is None


def test_mao_70():
    # ARV 400k, repair 20k → MAO = 400k * 0.7 - 20k = 260k
    assert mao_70(arv=400_000, repair_cost=20_000) == 260_000


def test_mao_invalid():
    assert mao_70(0, 10_000) is None
    assert mao_70(400_000, -5) is None


def test_brrrr_basic():
    # purchase 200k + repair 50k = 250k all-in. ARV 350k * 0.75 = 262.5k refi.
    # left_in = 250k - 262.5k = -12.5k (cash-out!)
    result = brrrr_refinance(purchase=200_000, repair_cost=50_000, arv=350_000)
    assert result is not None
    assert result.all_in == 250_000
    assert result.refi_loan == 262_500
    assert result.left_in == -12_500


def test_brrrr_partial_recovery():
    # purchase 250k + repair 50k = 300k all-in. ARV 350k * 0.75 = 262.5k refi.
    # left_in = 37.5k still in the deal
    result = brrrr_refinance(purchase=250_000, repair_cost=50_000, arv=350_000)
    assert result is not None
    assert result.left_in == 37_500
