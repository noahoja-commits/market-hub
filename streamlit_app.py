"""Tampa Bay Market Hub — Streamlit dashboard.

Pulls free public data (Zillow Research, FRED) plus latest commentary
from local Tampa Bay realtor/PM/research blogs. No API keys.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent / "data"

st.set_page_config(
    page_title="Tampa Bay Market Hub",
    page_icon=":house:",
    layout="wide",
)

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
FRED_TMPL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}

WEEK = 60 * 60 * 24 * 7
DAY = 60 * 60 * 24
HOUR = 60 * 60

COMMENTARY_SOURCES = [
    {
        "name": "iBuyer — Tampa Investor Market Report",
        "url": "https://ibuyer.com/blog/tampa-investor-market-report/",
        "blurb": "Long-form analysis of who's buying Tampa investment property",
    },
    {
        "name": "Three Avenues Group",
        "url": "https://www.3avesgroup.com/blog/",
        "blurb": "Local investor / wholesaler blog",
    },
    {
        "name": "Tampa Bay Realtor Sean",
        "url": "https://www.tampabayrealtorsean.com",
        "blurb": "Sean Tennant — Tampa Bay realtor commentary",
    },
    {
        "name": "Liane Jamason / Corcoran Dwellings",
        "url": "https://www.lianejamason.com",
        "blurb": "Tampa-area Corcoran agent updates",
    },
    {
        "name": "Smith & Associates — Tampa Bay Market Report",
        "url": "https://www.smithandassociates.com/tampa-bay-market-report/",
        "blurb": "Luxury brokerage's Tampa Bay market report",
    },
    {
        "name": "Out Fast Property Management",
        "url": "https://outfastpropertymanagement.com",
        "blurb": "Tampa-area PM newsletter / blog",
    },
    {
        "name": "Florida Realtors",
        "url": "https://www.floridarealtors.org",
        "blurb": "Statewide MLS-backed data & news",
    },
    {
        "name": "Altos Research",
        "url": "https://altos.re",
        "blurb": "Weekly market analytics (subset free)",
    },
]


# ──────────────────────────────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────────────────────────────

def _empty_long() -> pd.DataFrame:
    return pd.DataFrame({"RegionName": [], "date": [], "value": []})


def _empty_series() -> pd.DataFrame:
    return pd.DataFrame({"date": [], "value": []})


def _zillow_from_snapshot(kind: str) -> pd.DataFrame | None:
    """Read pre-baked Zillow snapshot for given kind ('zhvi' or 'zori')."""
    path = DATA_DIR / "tampa-bay-zillow.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df = df[df["kind"] == kind].drop(columns=["kind"]).reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


def _fred_from_snapshot(series_id: str) -> pd.DataFrame | None:
    path = DATA_DIR / "tampa-bay-fred.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df = df[df["series"] == series_id].drop(columns=["series"]).reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=WEEK, show_spinner=False)
def fetch_zillow(url: str) -> pd.DataFrame:
    """Read pre-baked snapshot if available, else live-fetch.

    Returns empty DataFrame on failure so the page still renders.
    """
    kind = "zhvi" if "zhvi" in url else "zori"
    snap = _zillow_from_snapshot(kind)
    if snap is not None:
        return snap
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
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
        return long.dropna(subset=["value"]).sort_values(["RegionName", "date"])
    except Exception as e:
        st.warning(f"Zillow fetch failed ({url.split('/')[-1]}): {e.__class__.__name__}. Showing empty.")
        return _empty_long()


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_fred(series_id: str) -> pd.DataFrame:
    """Read pre-baked snapshot if available, else live-fetch.

    Returns empty DataFrame on failure so the page still renders.
    """
    snap = _fred_from_snapshot(series_id)
    if snap is not None:
        return snap
    try:
        r = requests.get(
            FRED_TMPL.format(series_id=series_id),
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        date_col = "observation_date" if "observation_date" in df.columns else "DATE"
        df = df.rename(columns={date_col: "date", series_id: "value"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    except Exception as e:
        st.warning(f"FRED {series_id} fetch failed: {e.__class__.__name__}. Showing empty.")
        return _empty_series()


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_commentary(url: str) -> dict:
    """Fetch a page and pull title + description + first article headline.

    Defensive: catches all exceptions and returns an error string in the
    result so one broken source doesn't break the section.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # Title: prefer og:title, then <title>
        title = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        # Description: prefer og:description, then meta description
        desc = ""
        ogd = soup.find("meta", property="og:description")
        md = soup.find("meta", attrs={"name": "description"})
        if ogd and ogd.get("content"):
            desc = ogd["content"].strip()
        elif md and md.get("content"):
            desc = md["content"].strip()
        # Latest headline: first <h2> or <h3> in article/main if present
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
    except requests.RequestException as e:
        return {"ok": False, "error": f"network: {e.__class__.__name__}"}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:80]}"}


def _commentary_from_snapshot() -> dict[str, dict] | None:
    path = DATA_DIR / "commentary.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("sources") or None
    except Exception:
        return None


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_all_commentary(urls_key: tuple[str, ...]) -> dict[str, dict]:
    """Read pre-baked snapshot if available, else live-fetch in parallel."""
    snap = _commentary_from_snapshot()
    if snap is not None:
        # Only return entries whose URLs are still in our source list
        return {url: snap.get(url, {"ok": False, "error": "not in snapshot"}) for url in urls_key}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_commentary, urls_key))
    for url, res in zip(urls_key, results):
        out[url] = res
    return out


def snapshot_freshness() -> dict[str, str]:
    """Return human-readable last-modified timestamps for each snapshot file."""
    out: dict[str, str] = {}
    for label, fname in [
        ("Zillow", "tampa-bay-zillow.parquet"),
        ("FRED", "tampa-bay-fred.parquet"),
        ("Commentary", "commentary.json"),
    ]:
        path = DATA_DIR / fname
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            out[label] = mtime.strftime("%Y-%m-%d %H:%M UTC")
        else:
            out[label] = "live"
    return out


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def latest_per_county(long: pd.DataFrame) -> pd.DataFrame:
    return long.sort_values("date").groupby("RegionName").tail(1)


def yoy_per_county(long: pd.DataFrame) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for region, grp in long.groupby("RegionName"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < 13:
            out[region] = None
            continue
        current = grp["value"].iloc[-1]
        prior = grp["value"].iloc[-13]
        out[region] = ((current - prior) / prior) * 100 if prior else None
    return out


def fmt_money(n: float | None, compact: bool = False) -> str:
    if n is None or pd.isna(n):
        return "—"
    if compact:
        if n >= 1_000_000:
            return f"${n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"${n / 1_000:.0f}K"
    return f"${n:,.0f}"


def fmt_pct(n: float | None, sign: bool = True) -> str:
    if n is None or pd.isna(n):
        return "—"
    s = "+" if sign and n > 0 else ""
    return f"{s}{n:.1f}%"


# ──────────────────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────────────────

st.title("Tampa Bay Market Hub")
st.caption("Hillsborough · Pinellas · Pasco · Hernando")

with st.sidebar:
    st.header("Snapshot status")
    freshness = snapshot_freshness()
    for label, ts in freshness.items():
        if ts == "live":
            st.caption(f"**{label}:** live fetch (no snapshot)")
        else:
            st.caption(f"**{label}:** {ts}")
    st.caption(
        "Data is read from pre-baked snapshots committed to the repo. "
        "Refreshed weekly by the GitHub Action. Pages should load in <1s."
    )
    st.divider()
    if st.button("Force live re-fetch", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "**Sources:** Zillow Research (ZHVI, ZORI), FRED (Federal Reserve), "
        "plus local realtor/PM blogs (see Commentary section)."
    )

# Single visible load-progress block — shows what's happening on first run.
status = st.status("Loading market data...", expanded=True)
with status:
    st.write("Fetching Zillow home values (ZHVI)...")
    zhvi = fetch_zillow(ZHVI_URL)
    st.write(f"  ✓ {len(zhvi):,} rows")
    st.write("Fetching Zillow rents (ZORI)...")
    zori = fetch_zillow(ZORI_URL)
    st.write(f"  ✓ {len(zori):,} rows")
    st.write("Fetching FRED mortgage rate...")
    mortgage = fetch_fred("MORTGAGE30US")
    st.write(f"  ✓ {len(mortgage):,} observations")
    st.write("Fetching FRED Tampa HPI + unemployment...")
    hpi = fetch_fred("ATNHPIUS45300Q")
    unemp = fetch_fred("TAMP312URN")
    st.write(f"  ✓ HPI {len(hpi)}, unemployment {len(unemp)}")
status.update(label="Market data loaded.", state="complete", expanded=False)

zhvi_latest = latest_per_county(zhvi).set_index("RegionName")
zori_latest = latest_per_county(zori).set_index("RegionName")
zhvi_yoy = yoy_per_county(zhvi)
zori_yoy = yoy_per_county(zori)

metro_value = zhvi_latest["value"].mean() if not zhvi_latest.empty else None
metro_rent = zori_latest["value"].mean() if not zori_latest.empty else None
metro_value_yoy = pd.Series(zhvi_yoy).dropna().mean() if zhvi_yoy else None
metro_rent_yoy = pd.Series(zori_yoy).dropna().mean() if zori_yoy else None
rent_yield = (
    (metro_rent * 12 / metro_value) * 100 if metro_value and metro_rent else None
)

last_mortgage = mortgage["value"].iloc[-1] if not mortgage.empty else None
mortgage_4w_bps = None
if len(mortgage) > 4:
    mortgage_4w_bps = (mortgage["value"].iloc[-1] - mortgage["value"].iloc[-5]) * 100

last_mortgage_date = mortgage["date"].iloc[-1].strftime("%b %d") if not mortgage.empty else ""
zhvi_as_of = zhvi["date"].max().strftime("%b %Y") if not zhvi.empty else ""

st.subheader("Metro snapshot")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Median home value",
    fmt_money(metro_value),
    f"{fmt_pct(metro_value_yoy)} YoY" if metro_value_yoy is not None else None,
    help=f"Zillow ZHVI · avg of 4 counties · as of {zhvi_as_of}",
)
c2.metric(
    "Median rent",
    fmt_money(metro_rent),
    f"{fmt_pct(metro_rent_yoy)} YoY" if metro_rent_yoy is not None else None,
    help="Zillow ZORI · monthly",
)
c3.metric(
    "Gross rent yield",
    f"{rent_yield:.2f}%" if rent_yield is not None else "—",
    help="Annualized rent / value, before expenses",
)
c4.metric(
    "30-yr mortgage",
    f"{last_mortgage:.2f}%" if last_mortgage is not None else "—",
    f"{mortgage_4w_bps:+.0f} bps 4w" if mortgage_4w_bps is not None else None,
    delta_color="inverse",
    help=f"FRED MORTGAGE30US · week of {last_mortgage_date}",
)

st.subheader("By county")
cols = st.columns(len(TAMPA_COUNTIES))
for col, county in zip(cols, TAMPA_COUNTIES):
    short = county.replace(" County", "")
    v = zhvi_latest["value"].get(county)
    r = zori_latest["value"].get(county)
    vy = zhvi_yoy.get(county)
    ry = zori_yoy.get(county)
    with col:
        st.markdown(f"**{short}**")
        sub = st.columns(2)
        sub[0].metric(
            "Value",
            fmt_money(v, compact=True),
            f"{fmt_pct(vy)} YoY" if vy is not None else None,
        )
        sub[1].metric(
            "Rent",
            fmt_money(r),
            f"{fmt_pct(ry)} YoY" if ry is not None else None,
        )
        spark = zhvi[zhvi["RegionName"] == county].tail(60)[["date", "value"]]
        if not spark.empty:
            st.line_chart(
                spark.set_index("date"),
                height=120,
                color="#0ea5e9",
            )

st.subheader("Tampa MSA — Home Price Index")
hpi_yoy = None
if len(hpi) >= 5:
    hpi_yoy = (hpi["value"].iloc[-1] - hpi["value"].iloc[-5]) / hpi["value"].iloc[-5] * 100
st.caption(
    f"FRED · ATNHPIUS45300Q · quarterly"
    + (f" · {fmt_pct(hpi_yoy)} YoY" if hpi_yoy is not None else "")
)
if not hpi.empty:
    st.line_chart(hpi.tail(40).set_index("date")[["value"]], height=240, color="#0ea5e9")
else:
    st.info("HPI series unavailable.")

left, right = st.columns(2)
with left:
    st.subheader("Tampa MSA — Unemployment")
    last_u = unemp["value"].iloc[-1] if not unemp.empty else None
    st.caption(
        f"FRED · TAMP312URN · monthly"
        + (f" · {last_u:.1f}% latest" if last_u is not None else "")
    )
    if not unemp.empty:
        st.line_chart(
            unemp.tail(60).set_index("date")[["value"]],
            height=240,
            color="#f59e0b",
        )
    else:
        st.info("Unemployment series unavailable.")
with right:
    st.subheader("30-yr fixed mortgage (US)")
    st.caption("FRED · MORTGAGE30US · weekly")
    if not mortgage.empty:
        st.line_chart(
            mortgage.tail(260).set_index("date")[["value"]],
            height=240,
            color="#a855f7",
        )
    else:
        st.info("Mortgage series unavailable.")

# ──────────────────────────────────────────────────────────────────────
# Local commentary
# ──────────────────────────────────────────────────────────────────────

st.subheader("Local commentary")
st.caption(
    "Latest from Tampa Bay realtors, property managers, and market analysts. "
    "Cached for 1 hour. Click any title to read on the source site."
)

with st.status("Fetching commentary sources...", expanded=False) as cstatus:
    urls = tuple(s["url"] for s in COMMENTARY_SOURCES)
    comm_results = fetch_all_commentary(urls)
    ok_count = sum(1 for r in comm_results.values() if r.get("ok"))
    cstatus.update(
        label=f"Commentary loaded — {ok_count}/{len(COMMENTARY_SOURCES)} sources reachable.",
        state="complete",
        expanded=False,
    )

ccols = st.columns(2)
for i, source in enumerate(COMMENTARY_SOURCES):
    res = comm_results.get(source["url"], {})
    with ccols[i % 2]:
        with st.container(border=True):
            st.markdown(f"**[{source['name']}]({source['url']})**")
            st.caption(source["blurb"])
            if not res.get("ok"):
                st.caption(f":red[Could not reach source — {res.get('error', 'unknown error')}]")
            else:
                if res.get("title"):
                    st.markdown(f"_{res['title']}_")
                if res.get("latest") and res["latest"].lower() != (res.get("title") or "").lower():
                    st.markdown(f"**Latest:** {res['latest']}")
                if res.get("desc"):
                    st.write(res["desc"])

st.divider()
st.caption(
    "Data: Zillow Research (ZHVI home values, ZORI rents) · "
    "FRED (Federal Reserve Bank of St. Louis) · "
    "Plus public web content from sources listed above. "
    "All sources are free and public — no API keys required."
)
