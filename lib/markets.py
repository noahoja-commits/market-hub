"""Market definitions for the dashboard.

A Market bundles together its counties (for Zillow filtering) and the
FRED series IDs that apply to its MSA. The mortgage rate (MORTGAGE30US)
is global, so it's not stored per-market.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Market:
    slug: str
    label: str
    counties: list[str]  # Zillow RegionName values, e.g. "Hillsborough County"
    state: str = "FL"
    # FRED series IDs keyed by purpose. Optional — markets missing a key
    # just skip that chart.
    fred_series: dict[str, str] = field(default_factory=dict)


# Tampa Bay
TAMPA_BAY = Market(
    slug="tampa-bay",
    label="Tampa Bay",
    counties=[
        "Hillsborough County",
        "Pinellas County",
        "Pasco County",
        "Hernando County",
    ],
    fred_series={
        # FHFA all-transactions HPI for Tampa-St Petersburg-Clearwater MSA (CBSA 45300)
        "hpi": "ATNHPIUS45300Q",
        # Unemployment rate, Tampa-St Petersburg-Clearwater MSA
        "unemp": "TAMP312URN",
    },
)

# Orlando metro
ORLANDO = Market(
    slug="orlando",
    label="Orlando",
    counties=[
        "Orange County",
        "Osceola County",
        "Seminole County",
        "Lake County",
    ],
    fred_series={
        # HPI for Orlando-Kissimmee-Sanford MSA (CBSA 36740)
        "hpi": "ATNHPIUS36740Q",
    },
)

# Southwest Florida (Cape Coral-Fort Myers + Naples)
SWFL = Market(
    slug="swfl",
    label="SW Florida",
    counties=[
        "Lee County",
        "Collier County",
        "Charlotte County",
    ],
    fred_series={
        # HPI for Cape Coral-Fort Myers MSA (CBSA 15980)
        "hpi": "ATNHPIUS15980Q",
    },
)

# Jacksonville metro
JACKSONVILLE = Market(
    slug="jacksonville",
    label="Jacksonville",
    counties=[
        "Duval County",
        "Clay County",
        "St. Johns County",
        "Nassau County",
    ],
    fred_series={
        # HPI for Jacksonville MSA (CBSA 27260)
        "hpi": "ATNHPIUS27260Q",
    },
)

# Space Coast (Palm Bay-Melbourne-Titusville + Daytona Beach)
SPACE_COAST = Market(
    slug="space-coast",
    label="Space Coast",
    counties=[
        "Brevard County",
        "Volusia County",
    ],
    fred_series={
        # HPI for Palm Bay-Melbourne-Titusville MSA (CBSA 37340)
        "hpi": "ATNHPIUS37340Q",
    },
)

MARKETS: list[Market] = [TAMPA_BAY, ORLANDO, SWFL, JACKSONVILLE, SPACE_COAST]
MARKETS_BY_SLUG: dict[str, Market] = {m.slug: m for m in MARKETS}


def get_market(slug: str) -> Market:
    if slug not in MARKETS_BY_SLUG:
        raise KeyError(f"Unknown market: {slug}")
    return MARKETS_BY_SLUG[slug]
