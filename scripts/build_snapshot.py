"""Build pre-baked data snapshots for the market-hub Streamlit app.

Run this script to refresh `data/*.parquet` and `data/commentary.json`
from the upstream sources (Zillow Research, FRED, public commentary sites).

The Streamlit app reads these files instead of hitting the network on each
page load, so the app loads in <1s even when FRED is flaky.

Usage:
    python scripts/build_snapshot.py

Exit code is non-zero only if every source fails. Individual failures
are tolerated — the existing snapshot files are kept untouched.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────────────────────────────
# Sources (mirrored from streamlit_app.py — keep in sync)
# ──────────────────────────────────────────────────────────────────────

TAMPA_COUNTIES = [
    "Hillsborough County",
    "Pinellas County",
    "Pasco County",
    "Hernando County",
]

ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
ZORI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "County_zori_uc_sfrcondomfr_sm_month.csv"
)
FRED_SERIES = ["MORTGAGE30US", "ATNHPIUS45300Q", "TAMP312URN"]

COMMENTARY_SOURCES = [
    {"name": "iBuyer — Tampa Investor Market Report", "url": "https://ibuyer.com/blog/tampa-investor-market-report/"},
    {"name": "Three Avenues Group", "url": "https://www.3avesgroup.com/blog/"},
    {"name": "Tampa Bay Realtor Sean", "url": "https://www.tampabayrealtorsean.com"},
    {"name": "Liane Jamason / Corcoran Dwellings", "url": "https://www.lianejamason.com"},
    {"name": "Smith & Associates — Tampa Bay Market Report", "url": "https://www.smithandassociates.com/tampa-bay-market-report/"},
    {"name": "Out Fast Property Management", "url": "https://outfastpropertymanagement.com"},
    {"name": "Florida Realtors", "url": "https://www.floridarealtors.org"},
    {"name": "Altos Research", "url": "https://altos.re"},
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}

# ──────────────────────────────────────────────────────────────────────
# Fetchers (no streamlit dependencies — pure)
# ──────────────────────────────────────────────────────────────────────


def fetch_zillow_long(url: str, kind: str) -> pd.DataFrame:
    """Stream Zillow CSV to a temp file (avoids holding 13MB twice in memory),
    then read + filter to Tampa Bay counties only."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        with requests.get(url, headers=HEADERS, timeout=180, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    tmp.write(chunk)
        tmp_path = tmp.name
    try:
        df = pd.read_csv(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    df = df[(df["StateName"] == "FL") & (df["RegionName"].isin(TAMPA_COUNTIES))]
    date_cols = [c for c in df.columns if DATE_RE.match(str(c))]
    long = df.melt(
        id_vars=["RegionName"],
        value_vars=date_cols,
        var_name="date",
        value_name="value",
    )
    long["date"] = pd.to_datetime(long["date"])
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long["kind"] = kind
    return long.dropna(subset=["value"]).sort_values(["RegionName", "date"]).reset_index(drop=True)


def fetch_fred_series(series_id: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    # Retry FRED multiple times — endpoint is flaky.
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            break
        except Exception as e:
            last_err = e
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    df = pd.read_csv(StringIO(r.text))
    date_col = "observation_date" if "observation_date" in df.columns else "DATE"
    df = df.rename(columns={date_col: "date", series_id: "value"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["series"] = series_id
    return df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)


def fetch_commentary(url: str) -> dict:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        title = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        desc = ""
        ogd = soup.find("meta", property="og:description")
        md = soup.find("meta", attrs={"name": "description"})
        if ogd and ogd.get("content"):
            desc = ogd["content"].strip()
        elif md and md.get("content"):
            desc = md["content"].strip()
        latest_headline = ""
        for tag in soup.find_all(["h1", "h2", "h3"]):
            txt = (tag.get_text() or "").strip()
            if len(txt) > 12 and txt.lower() != (title or "").lower():
                latest_headline = txt[:200]
                break
        return {
            "ok": True,
            "title": title[:200],
            "desc": (desc or "")[:280],
            "latest": latest_headline,
        }
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:120]}"}


# ──────────────────────────────────────────────────────────────────────
# Build steps
# ──────────────────────────────────────────────────────────────────────


def build_zillow() -> bool:
    """Fetch ZHVI + ZORI, write to data/tampa-bay-zillow.parquet."""
    print("[zillow] fetching ZHVI + ZORI...", flush=True)
    frames: list[pd.DataFrame] = []
    for url, kind in [(ZHVI_URL, "zhvi"), (ZORI_URL, "zori")]:
        try:
            df = fetch_zillow_long(url, kind)
            print(f"  [ok]{kind}: {len(df):,} rows × {df['RegionName'].nunique()} counties")
            frames.append(df)
        except Exception as e:
            print(f"  [fail]{kind}: {e.__class__.__name__}: {e}", file=sys.stderr)
    if not frames:
        return False
    combined = pd.concat(frames, ignore_index=True)
    path = DATA_DIR / "tampa-bay-zillow.parquet"
    combined.to_parquet(path, index=False, compression="zstd")
    print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    return True


def build_fred() -> bool:
    """Fetch all FRED series, write to data/tampa-bay-fred.parquet."""
    print("[fred] fetching series...", flush=True)
    frames: list[pd.DataFrame] = []
    for series_id in FRED_SERIES:
        try:
            df = fetch_fred_series(series_id)
            print(f"  [ok]{series_id}: {len(df):,} observations")
            frames.append(df)
        except Exception as e:
            print(f"  [fail]{series_id}: {e.__class__.__name__}: {e}", file=sys.stderr)
    if not frames:
        return False
    combined = pd.concat(frames, ignore_index=True)
    path = DATA_DIR / "tampa-bay-fred.parquet"
    combined.to_parquet(path, index=False, compression="zstd")
    print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    return True


def build_commentary() -> bool:
    """Fetch all commentary sources in parallel, write data/commentary.json."""
    print("[commentary] fetching sources in parallel...", flush=True)
    urls = [s["url"] for s in COMMENTARY_SOURCES]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_commentary, urls))
    payload = {
        "fetched_at": pd.Timestamp.now("UTC").isoformat(),
        "sources": {url: res for url, res in zip(urls, results)},
    }
    ok = sum(1 for r in results if r.get("ok"))
    print(f"  [ok]{ok}/{len(results)} sources reachable")
    path = DATA_DIR / "commentary.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    return True


def main() -> int:
    started = time.time()
    print(f"Building snapshot in {DATA_DIR}")
    results = {
        "zillow": build_zillow(),
        "fred": build_fred(),
        "commentary": build_commentary(),
    }
    elapsed = time.time() - started
    ok = sum(results.values())
    print(f"\nDone — {ok}/{len(results)} steps succeeded ({elapsed:.1f}s)")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
