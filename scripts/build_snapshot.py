"""Build pre-baked data snapshots for the market-hub Streamlit app.

Run this script to refresh `data/*.parquet` and `data/commentary.json`
from upstream (Zillow Research, FRED, public commentary sites). The
Streamlit app reads these files first so it loads in <1s.

Usage:
    python scripts/build_snapshot.py

Exit code is non-zero only if every step fails. Individual failures
are tolerated — existing snapshot files are kept untouched.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.markets import MARKETS, Market  # noqa: E402

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────────────────────────────
# URLs / constants
# ──────────────────────────────────────────────────────────────────────

ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
ZORI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "County_zori_uc_sfrcondomfr_sm_month.csv"
)
FRED_TMPL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# Mortgage rate is global, shared by every market
GLOBAL_FRED_SERIES = ["MORTGAGE30US"]

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
# Fetchers (pure, no streamlit)
# ──────────────────────────────────────────────────────────────────────


def download_to_tmp(url: str, timeout: int = 180) -> Path:
    """Stream a URL to a tmp file. Avoids holding huge CSVs twice in memory."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        with requests.get(url, headers=HEADERS, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    tmp.write(chunk)
        return Path(tmp.name)


def load_zillow_csv(url: str) -> pd.DataFrame:
    """Download a Zillow county CSV and return the raw wide DataFrame."""
    tmp_path = download_to_tmp(url)
    try:
        return pd.read_csv(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def melt_zillow(df: pd.DataFrame, counties: list[str], state: str, kind: str) -> pd.DataFrame:
    """Filter wide Zillow CSV to one market's counties + melt to long form."""
    df = df[(df["StateName"] == state) & (df["RegionName"].isin(counties))]
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
    """Fetch one FRED CSV series with retries (FRED is flaky)."""
    url = FRED_TMPL.format(series_id=series_id)
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
    from io import StringIO
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


def build_zillow_all_markets() -> dict[str, bool]:
    """Download Zillow ZHVI+ZORI once, filter for each market, write parquet per market."""
    print("[zillow] downloading ZHVI + ZORI CSVs (once for all markets)...", flush=True)
    raw: dict[str, pd.DataFrame] = {}
    for url, kind in [(ZHVI_URL, "zhvi"), (ZORI_URL, "zori")]:
        try:
            raw[kind] = load_zillow_csv(url)
            print(f"  [ok] {kind}: {len(raw[kind]):,} total county-rows")
        except Exception as e:
            print(f"  [fail] {kind}: {e.__class__.__name__}: {e}", file=sys.stderr)
    if not raw:
        return {m.slug: False for m in MARKETS}

    results: dict[str, bool] = {}
    for market in MARKETS:
        try:
            frames = []
            for kind, wide in raw.items():
                frames.append(melt_zillow(wide, market.counties, market.state, kind))
            combined = pd.concat(frames, ignore_index=True)
            path = DATA_DIR / f"{market.slug}-zillow.parquet"
            combined.to_parquet(path, index=False, compression="zstd")
            n_counties = combined["RegionName"].nunique()
            print(f"  [ok] {market.slug}: {len(combined):,} rows × {n_counties} counties → {path.name}")
            results[market.slug] = True
        except Exception as e:
            print(f"  [fail] {market.slug}: {e.__class__.__name__}: {e}", file=sys.stderr)
            results[market.slug] = False
    return results


def build_fred_all_markets() -> dict[str, bool]:
    """For each market, fetch its FRED series + the global ones, write parquet."""
    print("[fred] fetching series per market...", flush=True)

    # Cache global series so we only fetch them once
    global_cache: dict[str, pd.DataFrame] = {}
    for sid in GLOBAL_FRED_SERIES:
        try:
            global_cache[sid] = fetch_fred_series(sid)
            print(f"  [ok] {sid} (global): {len(global_cache[sid]):,} obs")
        except Exception as e:
            print(f"  [fail] {sid} (global): {e.__class__.__name__}: {e}", file=sys.stderr)

    results: dict[str, bool] = {}
    for market in MARKETS:
        frames: list[pd.DataFrame] = list(global_cache.values())
        for purpose, sid in market.fred_series.items():
            try:
                frames.append(fetch_fred_series(sid))
                print(f"  [ok] {market.slug}/{purpose} ({sid}): added")
            except Exception as e:
                print(f"  [fail] {market.slug}/{purpose} ({sid}): {e.__class__.__name__}", file=sys.stderr)
        if not frames:
            results[market.slug] = False
            continue
        combined = pd.concat(frames, ignore_index=True)
        path = DATA_DIR / f"{market.slug}-fred.parquet"
        combined.to_parquet(path, index=False, compression="zstd")
        print(f"  [ok] {market.slug}: {len(combined):,} rows → {path.name}")
        results[market.slug] = True
    return results


def build_commentary() -> bool:
    """Single commentary set, shared across markets."""
    print("[commentary] fetching sources in parallel...", flush=True)
    urls = [s["url"] for s in COMMENTARY_SOURCES]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_commentary, urls))
    payload = {
        "fetched_at": pd.Timestamp.now("UTC").isoformat(),
        "sources": {url: res for url, res in zip(urls, results)},
    }
    ok = sum(1 for r in results if r.get("ok"))
    print(f"  [ok] {ok}/{len(results)} sources reachable")
    path = DATA_DIR / "commentary.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    return True


def main() -> int:
    started = time.time()
    print(f"Building snapshot for {len(MARKETS)} markets in {DATA_DIR}")
    zillow_results = build_zillow_all_markets()
    fred_results = build_fred_all_markets()
    commentary_ok = build_commentary()
    elapsed = time.time() - started
    total_ok = sum(zillow_results.values()) + sum(fred_results.values()) + (1 if commentary_ok else 0)
    print(f"\nDone — Zillow {sum(zillow_results.values())}/{len(MARKETS)}, "
          f"FRED {sum(fred_results.values())}/{len(MARKETS)}, "
          f"Commentary {'ok' if commentary_ok else 'fail'}. "
          f"Elapsed: {elapsed:.1f}s")
    return 0 if total_ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
