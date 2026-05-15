"""Pure deal-math functions — no streamlit, no IO, easy to unit-test.

All inputs are positive numbers. Functions return None when inputs would
produce nonsense (negative, division by zero) so the UI can render "—".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapRate:
    gross: float  # % — rent / price, before expenses
    net: float    # % — after assumed opex


def cap_rate(price: float, monthly_rent: float, opex_pct: float = 0.40) -> CapRate | None:
    """Gross + net cap rate.

    opex_pct is share of gross rent eaten by taxes, insurance, vacancy,
    maintenance, mgmt — 40% is a common SFR rule of thumb. Net cap excludes
    debt service (that's PITI's job).
    """
    if price <= 0 or monthly_rent <= 0 or not 0 <= opex_pct < 1:
        return None
    annual_rent = monthly_rent * 12
    gross = (annual_rent / price) * 100
    net = (annual_rent * (1 - opex_pct) / price) * 100
    return CapRate(gross=gross, net=net)


def piti(
    price: float,
    down_pct: float,
    rate_pct: float,
    term_years: int = 30,
    taxes_pct: float = 0.012,
    insurance_annual: float = 2400.0,
) -> float | None:
    """Monthly PITI (principal+interest+taxes+insurance).

    Defaults: 1.2% effective FL property tax, $2,400/yr insurance (rough
    Tampa Bay SFR baseline — hurricane-belt rates have moved a lot, user
    can override).
    """
    if price <= 0 or not 0 <= down_pct < 1 or rate_pct <= 0 or term_years <= 0:
        return None
    loan = price * (1 - down_pct)
    monthly_rate = (rate_pct / 100) / 12
    n = term_years * 12
    if monthly_rate == 0:
        pi = loan / n
    else:
        pi = loan * monthly_rate * (1 + monthly_rate) ** n / ((1 + monthly_rate) ** n - 1)
    taxes_monthly = price * taxes_pct / 12
    ins_monthly = insurance_annual / 12
    return pi + taxes_monthly + ins_monthly


def price_to_rent(price: float, monthly_rent: float) -> float | None:
    """P/R ratio = price / annual rent. <15 cheap, >20 expensive (rule of thumb)."""
    if price <= 0 or monthly_rent <= 0:
        return None
    return price / (monthly_rent * 12)


def mao_70(arv: float, repair_cost: float, pct: float = 0.70) -> float | None:
    """70% rule max allowable offer = (ARV × pct) − repair."""
    if arv <= 0 or repair_cost < 0 or not 0 < pct <= 1:
        return None
    return arv * pct - repair_cost


@dataclass(frozen=True)
class BrrrrOutcome:
    refi_loan: float    # cash you can pull at refinance
    all_in: float       # total invested (purchase + repair, no debt)
    left_in: float      # what you don't recover at refi (can be negative = cash-out)


def brrrr_refinance(
    purchase: float,
    repair_cost: float,
    arv: float,
    refi_ltv: float = 0.75,
) -> BrrrrOutcome | None:
    """BRRRR cash-out at refi.

    all_in = purchase + repair (assumes cash purchase or bridge paid off).
    refi loan = ARV × LTV (typical 75%).
    left_in = all_in − refi_loan (negative means cash-out exceeded basis).
    """
    if purchase <= 0 or repair_cost < 0 or arv <= 0 or not 0 < refi_ltv <= 1:
        return None
    all_in = purchase + repair_cost
    refi_loan = arv * refi_ltv
    return BrrrrOutcome(refi_loan=refi_loan, all_in=all_in, left_in=all_in - refi_loan)
