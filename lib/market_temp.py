"""Buyer's-vs-seller's-market temperature gauge.

Pure, deterministic. Scores three pace signals against their own
trailing history and combines them into a single −100…+100 score:
  negative = buyer's market   ·   positive = seller's market

Signals (each contributes up to ±100, then averaged):
- days-to-pending  — rising vs 12mo ago → buyers gain leverage (negative)
- for-sale inventory — rising vs 12mo ago → more selection (negative)
- sale-to-list ratio — falling vs 12mo ago → room to negotiate (negative)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Temperature:
    score: float                       # −100 (buyer's) … +100 (seller's)
    label: str
    reasons: list[str] = field(default_factory=list)


def _pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / prior * 100


def _clamp(x: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _label(score: float) -> str:
    if score <= -50:
        return "Strong buyer's market"
    if score <= -15:
        return "Buyer's market"
    if score < 15:
        return "Balanced market"
    if score < 50:
        return "Seller's market"
    return "Strong seller's market"


def market_temperature(
    days_pending_now: float | None,
    days_pending_yr_ago: float | None,
    inventory_now: float | None,
    inventory_yr_ago: float | None,
    sale_to_list_now: float | None,
    sale_to_list_yr_ago: float | None,
) -> Temperature:
    """Combine the three pace signals into a temperature score.

    Each signal's YoY % change is scaled (×4, clamped to ±100) into a
    sub-score; the final score is the mean of whatever signals exist.
    """
    sub_scores: list[float] = []
    reasons: list[str] = []

    # Days-to-pending: longer = cooler (buyer-friendly) → negative.
    dp = _pct_change(days_pending_now, days_pending_yr_ago)
    if dp is not None:
        sub_scores.append(_clamp(-dp * 4))
        if dp > 5:
            reasons.append(f"Homes take {dp:.0f}% longer to go pending than a year ago")
        elif dp < -5:
            reasons.append(f"Homes go pending {abs(dp):.0f}% faster than a year ago")
        else:
            reasons.append("Time-to-pending is roughly flat YoY")

    # Inventory: more for-sale supply = cooler → negative.
    inv = _pct_change(inventory_now, inventory_yr_ago)
    if inv is not None:
        sub_scores.append(_clamp(-inv * 3))
        if inv > 5:
            reasons.append(f"For-sale inventory is up {inv:.0f}% YoY — more selection")
        elif inv < -5:
            reasons.append(f"For-sale inventory is down {abs(inv):.0f}% YoY — tighter supply")
        else:
            reasons.append("For-sale inventory is roughly flat YoY")

    # Sale-to-list: falling ratio = sellers conceding → negative.
    stl = _pct_change(sale_to_list_now, sale_to_list_yr_ago)
    if stl is not None:
        sub_scores.append(_clamp(stl * 30))
        if sale_to_list_now is not None:
            if sale_to_list_now < 0.985:
                reasons.append(
                    f"Homes close at {sale_to_list_now * 100:.1f}% of list — "
                    f"clear room to negotiate"
                )
            elif sale_to_list_now > 1.0:
                reasons.append(
                    f"Homes close above list ({sale_to_list_now * 100:.1f}%) — "
                    f"competitive bidding"
                )
            else:
                reasons.append(
                    f"Homes close near list ({sale_to_list_now * 100:.1f}%)"
                )

    if not sub_scores:
        return Temperature(score=0.0, label="Unknown — no pace data", reasons=[])

    score = sum(sub_scores) / len(sub_scores)
    return Temperature(score=round(score, 1), label=_label(score), reasons=reasons)
