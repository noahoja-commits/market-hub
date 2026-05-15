"""Census Building Permits Survey — annual county-level housing permits.

Source: https://www2.census.gov/econ/bps/County/co<YYYY>a.txt

Each annual file has one row per US county. The layout is two header
rows + a blank line, then positional comma-separated data:

  0 Date(year)  1 State FIPS  2 County FIPS  3 Region  4 Division
  5 County Name  6-8 1-unit (Bldgs,Units,Value)  9-11 2-units
  12-14 3-4 units  15-17 5+ units  18+ "reported" duplicates

Total permitted housing units = sum of the Units columns (7,10,13,16).
"""

from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

HEADERS = {"User-Agent": "market-hub/0.1"}
COUNTY_URL = "https://www2.census.gov/econ/bps/County/co{year}a.txt"

# Positional indices of the four "Units" columns
_UNIT_COLS = [7, 10, 13, 16]


def fetch_county_permits(year: int, timeout: int = 60) -> pd.DataFrame:
    """Fetch one annual county BPS file → DataFrame[year, state_fips,
    county_fips, county, total_units]. Raises on network/HTTP error."""
    r = requests.get(COUNTY_URL.format(year=year), headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    # Skip the 2 header rows + 1 blank line, parse positionally.
    raw = pd.read_csv(StringIO(r.text), skiprows=3, header=None, dtype=str)
    out = pd.DataFrame({
        "year": pd.to_numeric(raw[0], errors="coerce").astype("Int64"),
        "state_fips": raw[1].str.strip().str.zfill(2),
        "county_fips": raw[2].str.strip().str.zfill(3),
        "county": raw[5].str.strip(),
    })
    units = raw[_UNIT_COLS].apply(lambda c: pd.to_numeric(c, errors="coerce"))
    out["total_units"] = units.sum(axis=1)
    return out.dropna(subset=["year"]).reset_index(drop=True)


def permits_timeseries(
    state_fips: str,
    county_fips: list[str],
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """Build a multi-year permits series for a set of counties.

    Returns DataFrame[date, county, total_units] with one row per
    county per year. Years that fail to fetch are skipped.
    """
    frames: list[pd.DataFrame] = []
    wanted = {c.zfill(3) for c in county_fips}
    for year in range(start_year, end_year + 1):
        try:
            df = fetch_county_permits(year)
        except Exception:
            continue
        df = df[(df["state_fips"] == state_fips) & (df["county_fips"].isin(wanted))]
        if df.empty:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["year"].astype(int).astype(str) + "-12-31")
        frames.append(df[["date", "county", "total_units"]])
    if not frames:
        return pd.DataFrame({"date": [], "county": [], "total_units": []})
    return pd.concat(frames, ignore_index=True).sort_values(["county", "date"]).reset_index(drop=True)
