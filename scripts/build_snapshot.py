"""Build pre-baked data snapshots for the market-hub Streamlit app.

Refreshes `data/*.parquet` and `data/commentary.json` from upstream
sources. The app reads these files first so it loads in <1s.

Sources (all reliable, no API keys):
- Zillow Research  — county home values (ZHVI) + rents (ZORI)
- Freddie Mac PMMS — national 30-yr fixed mortgage rate
- BLS public API   — MSA unemployment (LAUS) + employment (CES)
- Census BPS       — county building permits

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
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.markets import MARKETS  # noqa: E402
from lib.sources import bls, census_bps, fred_api  # noqa: E402

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
ZORI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "County_zori_uc_sfrcondomfr_sm_month.csv"
)
PMMS_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"

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

# Year ranges
THIS_YEAR = pd.Timestamp.now().year
BLS_START = THIS_YEAR - 7
PERMITS_START = THIS_YEAR - 12

# ──────────────────────────────────────────────────────────────────────
# Zillow
# ──────────────────────────────────────────────────────────────────────


def download_to_tmp(url: str, timeout: int = 180) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        with requests.get(url, headers=HEADERS, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    tmp.write(chunk)
        return Path(tmp.name)


def load_zillow_csv(url: str) -> pd.DataFrame:
    tmp_path = download_to_tmp(url)
    try:
        return pd.read_csv(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def melt_zillow(df: pd.DataFrame, counties: list[str], state: str, kind: str) -> pd.DataFrame:
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


def build_zillow_all_markets() -> dict[str, bool]:
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
            frames = [melt_zillow(w, market.counties, market.state, k) for k, w in raw.items()]
            combined = pd.concat(frames, ignore_index=True)
            path = DATA_DIR / f"{market.slug}-zillow.parquet"
            combined.to_parquet(path, index=False, compression="zstd")
            print(f"  [ok] {market.slug}: {len(combined):,} rows × "
                  f"{combined['RegionName'].nunique()} counties → {path.name}")
            results[market.slug] = True
        except Exception as e:
            print(f"  [fail] {market.slug}: {e.__class__.__name__}: {e}", file=sys.stderr)
            results[market.slug] = False
    return results


# ──────────────────────────────────────────────────────────────────────
# Mortgage (Freddie Mac PMMS)
# ──────────────────────────────────────────────────────────────────────


def fetch_pmms_mortgage() -> pd.DataFrame:
    """Freddie Mac PMMS 30-yr fixed rate, weekly. Returns date/value."""
    r = requests.get(PMMS_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce"),
        "value": pd.to_numeric(df["pmms30"], errors="coerce"),
    })
    return out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────
# Indicators — mortgage + unemployment + employment + permits per market
# ──────────────────────────────────────────────────────────────────────


def build_indicators_all_markets() -> dict[str, bool]:
    """Write data/<slug>-indicators.parquet — long format:
    columns [date, value, series, county]. county is set only for permits."""
    print("[indicators] mortgage + BLS labor + Census permits...", flush=True)

    # Mortgage is national — fetch once.
    mortgage: pd.DataFrame | None = None
    try:
        mortgage = fetch_pmms_mortgage()
        print(f"  [ok] PMMS mortgage: {len(mortgage):,} weekly obs")
    except Exception as e:
        print(f"  [fail] PMMS mortgage: {e.__class__.__name__}: {e}", file=sys.stderr)

    # Macro-rate context via the FRED API (national, optional — needs a key).
    macro: dict[str, pd.DataFrame] = {}
    fred_key = fred_api.get_api_key()
    if fred_key:
        for name, series_id in [("treasury_10yr", fred_api.TREASURY_10Y),
                                ("fed_funds", fred_api.FED_FUNDS)]:
            try:
                df = fred_api.fetch_observations(series_id, fred_key)
                if not df.empty:
                    macro[name] = df
                    print(f"  [ok] FRED {series_id} ({name}): {len(df):,} obs")
            except Exception as e:
                print(f"  [fail] FRED {series_id}: {e.__class__.__name__}", file=sys.stderr)
    else:
        print("  [skip] FRED macro — no API key (set FRED_API_KEY)")

    results: dict[str, bool] = {}
    for market in MARKETS:
        frames: list[pd.DataFrame] = []

        if mortgage is not None:
            m = mortgage.copy()
            m["series"] = "mortgage_30yr"
            m["county"] = pd.NA
            frames.append(m)

        # National macro-rate series — same for every market.
        for name, df in macro.items():
            mac = df.copy()
            mac["series"] = name
            mac["county"] = pd.NA
            frames.append(mac)

        # BLS unemployment
        try:
            u = bls.fetch_unemployment(market.bls_msa_code, BLS_START, THIS_YEAR)
            if not u.empty:
                u = u.copy()
                u["series"] = "unemployment"
                u["county"] = pd.NA
                frames.append(u)
                print(f"  [ok] {market.slug}/unemployment: {len(u)} obs")
        except Exception as e:
            print(f"  [fail] {market.slug}/unemployment: {e.__class__.__name__}", file=sys.stderr)

        # BLS employment
        try:
            e_df = bls.fetch_employment(market.bls_msa_code, BLS_START, THIS_YEAR)
            if not e_df.empty:
                e_df = e_df.copy()
                e_df["series"] = "employment"
                e_df["county"] = pd.NA
                frames.append(e_df)
                print(f"  [ok] {market.slug}/employment: {len(e_df)} obs")
        except Exception as e:
            print(f"  [fail] {market.slug}/employment: {e.__class__.__name__}", file=sys.stderr)

        # Census permits (per county)
        try:
            p = census_bps.permits_timeseries(
                market.state_fips, market.county_fips, PERMITS_START, THIS_YEAR
            )
            if not p.empty:
                p = p.rename(columns={"total_units": "value"})
                p["series"] = "permits"
                frames.append(p[["date", "value", "series", "county"]])
                print(f"  [ok] {market.slug}/permits: {len(p)} county-years")
        except Exception as e:
            print(f"  [fail] {market.slug}/permits: {e.__class__.__name__}", file=sys.stderr)

        if not frames:
            results[market.slug] = False
            continue
        combined = pd.concat(frames, ignore_index=True)
        path = DATA_DIR / f"{market.slug}-indicators.parquet"
        combined.to_parquet(path, index=False, compression="zstd")
        print(f"  [ok] {market.slug}: {len(combined):,} rows → {path.name}")
        results[market.slug] = True
    return results


# ──────────────────────────────────────────────────────────────────────
# Commentary
# ──────────────────────────────────────────────────────────────────────


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


def build_commentary() -> bool:
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
    zillow = build_zillow_all_markets()
    indicators = build_indicators_all_markets()
    commentary_ok = build_commentary()
    elapsed = time.time() - started
    total_ok = sum(zillow.values()) + sum(indicators.values()) + (1 if commentary_ok else 0)
    print(f"\nDone — Zillow {sum(zillow.values())}/{len(MARKETS)}, "
          f"Indicators {sum(indicators.values())}/{len(MARKETS)}, "
          f"Commentary {'ok' if commentary_ok else 'fail'}. "
          f"Elapsed: {elapsed:.1f}s")
    return 0 if total_ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
