"""Bureau of Labor Statistics public API client.

Uses the keyless v1 API (https://api.bls.gov/publicAPI/v1/). v1 allows
up to 10 years of history and 25 requests/day with no registration —
ample for 5 markets.

Two series families used:
- LAUS (Local Area Unemployment Statistics) — MSA unemployment rate
- CES (Current Employment Statistics) — MSA total nonfarm employment
"""

from __future__ import annotations

import pandas as pd
import requests

API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
HEADERS = {"User-Agent": "market-hub/0.1", "Content-Type": "application/json"}

_MONTH_NUM = {f"M{m:02d}": m for m in range(1, 13)}


def laus_series_id(msa_code: str, state_fips: str = "12") -> str:
    """Build a LAUS unemployment-rate series ID for an MSA.

    Format: LAU + MT + <state> + <5-digit MSA> + 000000 + 03
    (measure 03 = unemployment rate). Verified for FL metros.
    """
    return f"LAUMT{state_fips}{msa_code}00000003"


def ces_employment_series_id(msa_code: str, state_fips: str = "12") -> str:
    """Build a CES total-nonfarm all-employees series ID for an MSA.

    Format: SMU + <state> + <5-digit MSA> + 00 (supersector total) +
    000000 (industry total) + 01 (all employees, thousands).
    """
    return f"SMU{state_fips}{msa_code}0000000001"


def _parse_series(payload: dict, series_id: str) -> pd.DataFrame:
    """Turn a BLS API JSON payload into a sorted date/value DataFrame."""
    series_list = payload.get("Results", {}).get("series", [])
    if not series_list:
        return pd.DataFrame({"date": [], "value": []})
    rows: list[dict] = []
    for obs in series_list[0].get("data", []):
        month = _MONTH_NUM.get(obs.get("period", ""))
        if month is None:  # skip annual averages (M13) etc.
            continue
        try:
            value = float(obs["value"])
            year = int(obs["year"])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append({"date": pd.Timestamp(year=year, month=month, day=1), "value": value})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame({"date": [], "value": []})
    return df.sort_values("date").reset_index(drop=True)


def fetch_series(series_id: str, start_year: int, end_year: int, timeout: int = 30) -> pd.DataFrame:
    """Fetch one BLS series over a year range. Raises on network/HTTP error."""
    body = {
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    r = requests.post(API_URL, json=body, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {payload.get('message')}")
    return _parse_series(payload, series_id)


def fetch_unemployment(msa_code: str, start_year: int, end_year: int) -> pd.DataFrame:
    """MSA unemployment rate (%), monthly."""
    return fetch_series(laus_series_id(msa_code), start_year, end_year)


def fetch_employment(msa_code: str, start_year: int, end_year: int) -> pd.DataFrame:
    """MSA total nonfarm employment (thousands of jobs), monthly."""
    return fetch_series(ces_employment_series_id(msa_code), start_year, end_year)
