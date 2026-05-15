"""Tests for lib/sources/census_bps.py — the BPS flat-file parser."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.sources import census_bps

# 2 header rows + blank line + 2 data rows, mirroring the real file layout.
_FIXTURE = """Survey,FIPS,FIPS,Region,Division,County,,1-unit,,,2-units,,,3-4 units,,,5+ units,,,rep,,,rep,,,rep,,,rep
Date,State,County,Code,Code,Name,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value

2025,12,057,3,5,Hillsborough County           ,8000,8000,100,0,0,0,0,0,0,200,696,50,8000,8000,100,0,0,0,0,0,0,200,696,50
2025,12,103,3,5,Pinellas County               ,3000,3000,80,10,20,5,0,0,0,400,1178,30,3000,3000,80,10,20,5,0,0,0,400,1178,30
"""


def _fake_get(url, **kwargs):
    class R:
        text = _FIXTURE
        def raise_for_status(self):
            pass
    return R()


def test_fetch_county_permits_parses_total_units():
    with patch("lib.sources.census_bps.requests.get", _fake_get):
        df = census_bps.fetch_county_permits(2025)
    assert len(df) == 2
    hills = df[df["county_fips"] == "057"].iloc[0]
    # total units = 8000 (1u) + 0 (2u) + 0 (3-4) + 696 (5+) = 8696
    assert hills["total_units"] == 8696
    assert hills["state_fips"] == "12"
    pinellas = df[df["county_fips"] == "103"].iloc[0]
    # 3000 + 20 + 0 + 1178 = 4198
    assert pinellas["total_units"] == 4198


def test_permits_timeseries_filters_and_dates():
    with patch("lib.sources.census_bps.requests.get", _fake_get):
        ts = census_bps.permits_timeseries("12", ["057"], 2025, 2025)
    assert len(ts) == 1
    row = ts.iloc[0]
    assert row["county"] == "Hillsborough County"
    assert row["total_units"] == 8696
    assert str(row["date"].date()) == "2025-12-31"
