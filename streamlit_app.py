"""Tampa Bay Market Hub — Streamlit dashboard.

Pulls free public data (Zillow Research, FRED) and renders metro/county
snapshots and time-series charts. No API keys.
"""

from __future__ import annotations

import re
from io import StringIO

import pandas as pd
import requests
import streamlit as st

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
HEADERS = {"User-Agent": "market-hub/0.1"}

WEEK = 60 * 60 * 24 * 7
DAY = 60 * 60 * 24


@st.cache_data(ttl=WEEK, show_spinner="Fetching Zillow data...")
def fetch_zillow(url: str) -> pd.DataFrame:
    """Fetch a Zillow county CSV and return long-form for Tampa Bay only."""
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


@st.cache_data(ttl=DAY, show_spinner="Fetching FRED series...")
def fetch_fred(series_id: str) -> pd.DataFrame:
    """Fetch a FRED CSV series, normalize to date + value columns."""
    r = requests.get(FRED_TMPL.format(series_id=series_id), headers=HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    date_col = "observation_date" if "observation_date" in df.columns else "DATE"
    df = df.rename(columns={date_col: "date", series_id: "value"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)


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
    st.header("Refresh")
    st.caption(
        "Data is cached locally for ~1 week (Zillow) / 1 day (FRED). "
        "Click below to force a re-fetch."
    )
    if st.button("Refresh data now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("**Sources:** Zillow Research (ZHVI, ZORI), FRED (Federal Reserve Bank of St. Louis).")

zhvi = fetch_zillow(ZHVI_URL)
zori = fetch_zillow(ZORI_URL)
mortgage = fetch_fred("MORTGAGE30US")
hpi = fetch_fred("ATNHPIUS45300Q")
unemp = fetch_fred("TAMP312URN")

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
st.line_chart(hpi.tail(40).set_index("date")[["value"]], height=240, color="#0ea5e9")

left, right = st.columns(2)
with left:
    st.subheader("Tampa MSA — Unemployment")
    last_u = unemp["value"].iloc[-1] if not unemp.empty else None
    st.caption(
        f"FRED · TAMP312URN · monthly"
        + (f" · {last_u:.1f}% latest" if last_u is not None else "")
    )
    st.line_chart(
        unemp.tail(60).set_index("date")[["value"]],
        height=240,
        color="#f59e0b",
    )
with right:
    st.subheader("30-yr fixed mortgage (US)")
    st.caption("FRED · MORTGAGE30US · weekly")
    st.line_chart(
        mortgage.tail(260).set_index("date")[["value"]],
        height=240,
        color="#a855f7",
    )

st.divider()
st.caption(
    "Data: Zillow Research (ZHVI home values, ZORI rents) · "
    "FRED (Federal Reserve Bank of St. Louis). "
    "All sources are free and public — no API keys required."
)
