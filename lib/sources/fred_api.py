"""FRED official API client (api.stlouisfed.org).

Uses the JSON API — *not* the fredgraph.csv scraping endpoint, which
is unreliable. Requires a free API key, read from (in order):
  1. the FRED_API_KEY environment variable
  2. .streamlit/secrets.toml  (key: FRED_API_KEY)

If no key is found, callers get None and should skip FRED gracefully.
Used only for macro-rate context (Treasury yield, Fed funds) — the
core housing data comes from Zillow / BLS / Census / PMMS.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"
HEADERS = {"User-Agent": "market-hub/0.1"}

_SECRETS = Path(__file__).resolve().parent.parent.parent / ".streamlit" / "secrets.toml"


def get_api_key() -> str | None:
    """FRED API key from env var, then .streamlit/secrets.toml."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key.strip()
    if _SECRETS.exists():
        try:
            text = _SECRETS.read_text(encoding="utf-8")
            m = re.search(r'FRED_API_KEY\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
    return None


def fetch_observations(
    series_id: str,
    api_key: str,
    start_date: str = "2015-01-01",
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch a FRED series via the JSON API → DataFrame[date, value].
    Raises on network/HTTP error."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
    }
    r = requests.get(API_URL, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    rows: list[dict] = []
    for o in obs:
        raw = o.get("value")
        if raw in (None, ".", ""):
            continue
        try:
            rows.append({"date": pd.Timestamp(o["date"]), "value": float(raw)})
        except (ValueError, KeyError, TypeError):
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame({"date": [], "value": []})
    return df.sort_values("date").reset_index(drop=True)


# Series used for the macro backdrop
TREASURY_10Y = "DGS10"      # 10-year Treasury constant-maturity yield, daily
FED_FUNDS = "FEDFUNDS"      # Effective federal funds rate, monthly
