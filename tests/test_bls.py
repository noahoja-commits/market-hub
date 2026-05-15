"""Tests for lib/sources/bls.py — series-ID construction + JSON parsing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.sources import bls


def test_laus_series_id():
    # Verified live: Tampa MSA 45300 → LAUMT124530000000003
    assert bls.laus_series_id("45300") == "LAUMT124530000000003"
    assert len(bls.laus_series_id("45300")) == 20


def test_ces_series_id():
    assert bls.ces_employment_series_id("45300") == "SMU12453000000000001"
    assert len(bls.ces_employment_series_id("45300")) == 20


def test_parse_series():
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "X", "data": [
            {"year": "2026", "period": "M02", "value": "4.9"},
            {"year": "2026", "period": "M01", "value": "5.1"},
            {"year": "2025", "period": "M13", "value": "5.0"},  # annual avg — skipped
        ]}]},
    }
    df = bls._parse_series(payload, "X")
    assert len(df) == 2  # M13 dropped
    # sorted ascending → Jan then Feb
    assert df["value"].tolist() == [5.1, 4.9]
    assert str(df["date"].iloc[-1].date()) == "2026-02-01"


def test_parse_series_empty():
    assert bls._parse_series({"Results": {"series": []}}, "X").empty
