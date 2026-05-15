"""Market definitions for the dashboard.

A Market bundles its counties (Zillow RegionName + Census county FIPS)
and the BLS metro code for labor-market data. The mortgage rate
(Freddie Mac PMMS) is national, so it's not stored per-market.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class County:
    name: str          # Zillow RegionName, e.g. "Hillsborough County"
    fips: str           # 3-digit county FIPS, e.g. "057"


@dataclass(frozen=True)
class Market:
    slug: str
    label: str
    counties_data: list[County]
    state: str = "FL"
    state_fips: str = "12"
    bls_msa_code: str = ""  # 5-digit MSA code for BLS LAUS/CES

    @property
    def counties(self) -> list[str]:
        """Zillow RegionName list (back-compat with existing app code)."""
        return [c.name for c in self.counties_data]

    @property
    def county_fips(self) -> list[str]:
        return [c.fips for c in self.counties_data]


TAMPA_BAY = Market(
    slug="tampa-bay",
    label="Tampa Bay",
    bls_msa_code="45300",  # Tampa-St. Petersburg-Clearwater
    counties_data=[
        County("Hillsborough County", "057"),
        County("Pinellas County", "103"),
        County("Pasco County", "101"),
        County("Hernando County", "053"),
    ],
)

ORLANDO = Market(
    slug="orlando",
    label="Orlando",
    bls_msa_code="36740",  # Orlando-Kissimmee-Sanford
    counties_data=[
        County("Orange County", "095"),
        County("Osceola County", "097"),
        County("Seminole County", "117"),
        County("Lake County", "069"),
    ],
)

SWFL = Market(
    slug="swfl",
    label="SW Florida",
    bls_msa_code="15980",  # Cape Coral-Fort Myers
    counties_data=[
        County("Lee County", "071"),
        County("Collier County", "021"),
        County("Charlotte County", "015"),
    ],
)

JACKSONVILLE = Market(
    slug="jacksonville",
    label="Jacksonville",
    bls_msa_code="27260",  # Jacksonville
    counties_data=[
        County("Duval County", "031"),
        County("Clay County", "019"),
        County("St. Johns County", "109"),
        County("Nassau County", "089"),
    ],
)

SPACE_COAST = Market(
    slug="space-coast",
    label="Space Coast",
    bls_msa_code="37340",  # Palm Bay-Melbourne-Titusville
    counties_data=[
        County("Brevard County", "009"),
        County("Volusia County", "127"),
    ],
)

MARKETS: list[Market] = [TAMPA_BAY, ORLANDO, SWFL, JACKSONVILLE, SPACE_COAST]
MARKETS_BY_SLUG: dict[str, Market] = {m.slug: m for m in MARKETS}


def get_market(slug: str) -> Market:
    if slug not in MARKETS_BY_SLUG:
        raise KeyError(f"Unknown market: {slug}")
    return MARKETS_BY_SLUG[slug]
