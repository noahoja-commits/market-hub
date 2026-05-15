"""Market Brief generator — rule-based, deterministic, data-derived.

Every sentence traces to a number in `MarketSnapshot`. No invented
macro claims. `generate_brief()` returns three blocks: the state of
the market, what's driving it, and how to take advantage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.deal_math import piti


@dataclass
class MarketSnapshot:
    label: str
    median_value: float | None = None
    value_yoy: float | None = None          # %
    median_rent: float | None = None
    rent_yoy: float | None = None           # %
    gross_yield: float | None = None        # % metro avg (rent*12/value)
    mortgage_rate: float | None = None      # %
    mortgage_4w_bps: float | None = None    # change over ~4 weeks, bps
    unemployment: float | None = None       # %
    unemployment_yr_ago: float | None = None  # %
    permits_latest: float | None = None     # total metro units, latest yr
    permits_prior: float | None = None      # total metro units, prior yr
    permits_latest_year: int | None = None
    county_caps: dict[str, float] = field(default_factory=dict)   # short name -> gross cap %
    county_values: dict[str, float] = field(default_factory=dict)  # short name -> median value


@dataclass
class Brief:
    state: str
    happening: list[str]
    tactics: list[str]


def _money(n: float | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:,.0f}"


def _pct(n: float | None, digits: int = 1) -> str:
    if n is None:
        return "—"
    return f"{'+' if n > 0 else ''}{n:.{digits}f}%"


def _breakeven_down_pct(value: float, rent: float, rate: float) -> int | None:
    """Smallest down-payment % (0..100, step 5) where rent >= monthly PITI."""
    for down in range(0, 101, 5):
        p = piti(value, down / 100, rate)
        if p is not None and rent >= p:
            return down
    return None


def generate_brief(snap: MarketSnapshot) -> Brief:
    # ── State ──────────────────────────────────────────────────────────
    state = (
        f"{snap.label}: median home {_money(snap.median_value)} "
        f"({_pct(snap.value_yoy)} YoY), median rent {_money(snap.median_rent)}/mo "
        f"({_pct(snap.rent_yoy)} YoY), gross yield "
        f"{snap.gross_yield:.2f}% " if snap.gross_yield is not None else
        f"{snap.label}: median home {_money(snap.median_value)} "
        f"({_pct(snap.value_yoy)} YoY), median rent {_money(snap.median_rent)}/mo. "
    )
    extras = []
    if snap.mortgage_rate is not None:
        extras.append(f"30-yr mortgage {snap.mortgage_rate:.2f}%")
    if snap.unemployment is not None:
        extras.append(f"MSA unemployment {snap.unemployment:.1f}%")
    if extras:
        state = state.rstrip() + " · " + " · ".join(extras) + "."

    happening: list[str] = []

    # ── Rule 1: yield direction (value vs rent growth) ─────────────────
    if snap.value_yoy is not None and snap.rent_yoy is not None:
        gap = snap.value_yoy - snap.rent_yoy
        if snap.value_yoy < 0 and snap.rent_yoy < 0:
            happening.append(
                f"Both values ({_pct(snap.value_yoy)}) and rents ({_pct(snap.rent_yoy)}) "
                f"are down year-over-year — a softening market; patient buyers gain leverage."
            )
        elif gap > 1.5:
            happening.append(
                f"Home values are outpacing rents ({_pct(snap.value_yoy)} vs "
                f"{_pct(snap.rent_yoy)} YoY) — cap rates are compressing; this is an "
                f"appreciation-led market, not a cash-flow one."
            )
        elif gap < -1.5:
            happening.append(
                f"Rents are outpacing values ({_pct(snap.rent_yoy)} vs "
                f"{_pct(snap.value_yoy)} YoY) — yields are expanding, the cash-flow "
                f"math is improving for buyers."
            )
        else:
            happening.append(
                f"Values ({_pct(snap.value_yoy)}) and rents ({_pct(snap.rent_yoy)}) "
                f"are moving roughly together — yields are stable."
            )

    # ── Rule 2: mortgage rate level + trend ────────────────────────────
    if snap.mortgage_rate is not None:
        if snap.mortgage_4w_bps is not None and snap.mortgage_4w_bps <= -10:
            happening.append(
                f"30-yr financing at {snap.mortgage_rate:.2f}%, down "
                f"{abs(snap.mortgage_4w_bps):.0f} bps over the last month — affordability "
                f"is easing at the margin."
            )
        elif snap.mortgage_4w_bps is not None and snap.mortgage_4w_bps >= 10:
            happening.append(
                f"30-yr financing at {snap.mortgage_rate:.2f}%, up "
                f"{snap.mortgage_4w_bps:.0f} bps over the last month — affordability "
                f"is tightening; expect more motivated sellers."
            )
        else:
            happening.append(
                f"30-yr financing is holding near {snap.mortgage_rate:.2f}% — "
                f"a stable rate backdrop for underwriting."
            )

    # ── Rule 3: building permits (supply) ──────────────────────────────
    if snap.permits_latest is not None and snap.permits_prior:
        permits_chg = (snap.permits_latest - snap.permits_prior) / snap.permits_prior * 100
        yr = snap.permits_latest_year or "the latest year"
        if permits_chg > 5:
            happening.append(
                f"New-construction permits rose {_pct(permits_chg)} in {yr} "
                f"({snap.permits_latest:,.0f} units) — the supply pipeline is expanding, "
                f"a medium-term headwind for price growth and rents."
            )
        elif permits_chg < -5:
            happening.append(
                f"New-construction permits fell {_pct(permits_chg)} in {yr} "
                f"({snap.permits_latest:,.0f} units) — supply is tightening, "
                f"supportive of both prices and rents."
            )
        else:
            happening.append(
                f"New-construction permits were roughly flat in {yr} "
                f"({snap.permits_latest:,.0f} units) — no major supply shock either way."
            )

    # ── Rule 4: labor market ───────────────────────────────────────────
    if snap.unemployment is not None and snap.unemployment_yr_ago is not None:
        delta = snap.unemployment - snap.unemployment_yr_ago
        if delta >= 0.4:
            happening.append(
                f"MSA unemployment is {snap.unemployment:.1f}%, up from "
                f"{snap.unemployment_yr_ago:.1f}% a year ago — a softening labor "
                f"market, a demand risk to watch."
            )
        elif delta <= -0.4:
            happening.append(
                f"MSA unemployment is {snap.unemployment:.1f}%, down from "
                f"{snap.unemployment_yr_ago:.1f}% a year ago — a tightening labor "
                f"market, supportive of housing demand."
            )
        else:
            happening.append(
                f"MSA unemployment is steady near {snap.unemployment:.1f}% — "
                f"a stable demand backdrop."
            )

    # ── Rule 5: intra-metro county spread ──────────────────────────────
    if len(snap.county_values) >= 2:
        cheap = min(snap.county_values.items(), key=lambda kv: kv[1])
        rich = max(snap.county_values.items(), key=lambda kv: kv[1])
        if rich[1]:
            spread = (rich[1] - cheap[1]) / rich[1] * 100
            happening.append(
                f"Within the metro, {cheap[0]} ({_money(cheap[1])}) trades "
                f"{spread:.0f}% below {rich[0]} ({_money(rich[1])}) — the value "
                f"end of this market."
            )

    # ── Tactics ────────────────────────────────────────────────────────
    tactics: list[str] = []

    if snap.county_caps:
        best = max(snap.county_caps.items(), key=lambda kv: kv[1])
        tactics.append(
            f"Best cash-flow county: **{best[0]}** at a {best[1]:.2f}% gross cap "
            f"rate — the strongest rent-to-price ratio in this metro."
        )

    if snap.gross_yield is not None:
        if snap.gross_yield < 5.5:
            tactics.append(
                f"At a {snap.gross_yield:.2f}% metro gross yield, straight buy-and-hold "
                f"will struggle to cash-flow — favor forced-equity plays (BRRRR, "
                f"value-add rehab, flips) over turnkey rentals here."
            )
        elif snap.gross_yield >= 7:
            tactics.append(
                f"A {snap.gross_yield:.2f}% metro gross yield is healthy — straight "
                f"buy-and-hold rentals can pencil; prioritize turnkey cash-flow deals."
            )
        else:
            tactics.append(
                f"A {snap.gross_yield:.2f}% metro gross yield is workable but thin — "
                f"buy below median price or add value to clear a real return."
            )

    if snap.median_value and snap.median_rent and snap.mortgage_rate:
        down = _breakeven_down_pct(snap.median_value, snap.median_rent, snap.mortgage_rate)
        if down is None:
            tactics.append(
                f"At today's {snap.mortgage_rate:.2f}% rate, a median-priced "
                f"({_money(snap.median_value)}) deal does **not** cash-flow even at "
                f"100% down on the metro-median rent — buy under median or push rents."
            )
        elif down == 0:
            tactics.append(
                f"A median-priced deal cash-flows even fully financed at today's "
                f"{snap.mortgage_rate:.2f}% rate — rare; act decisively on clean ones."
            )
        else:
            tactics.append(
                f"At {snap.mortgage_rate:.2f}%, a median-priced deal needs roughly "
                f"**{down}% down** to break even on cash flow against the median rent."
            )

    if snap.value_yoy is not None and snap.value_yoy > 3:
        tactics.append(
            f"Appreciation is running {_pct(snap.value_yoy)} — forced-equity exits "
            f"(BRRRR cash-out, flips) remain viable, but verify ARV against recent "
            f"comps, not the trend."
        )

    if (
        snap.mortgage_4w_bps is not None and snap.mortgage_4w_bps >= 10
        and snap.gross_yield is not None and snap.gross_yield < 6
    ):
        tactics.append(
            f"Rising rates plus a thin {snap.gross_yield:.2f}% yield: underwrite "
            f"conservatively and stress-test every deal at +50 bps."
        )

    return Brief(state=state, happening=happening, tactics=tactics)
