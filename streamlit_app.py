"""Florida Market Hub — Streamlit dashboard.

Free public data, no API keys, every number sourced + dated:
- Zillow Research   — county home values (ZHVI) + rents (ZORI)
- Freddie Mac PMMS  — national 30-yr fixed mortgage rate
- BLS public API    — MSA unemployment + employment
- Census BPS        — county building permits
Plus an auto-generated, rule-based Market Brief.
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

from lib.brief import MarketSnapshot, generate_brief
from lib.deal_math import brrrr_refinance, cap_rate, mao_70, piti, price_to_rent
from lib.markets import MARKETS, MARKETS_BY_SLUG, Market

DATA_DIR = Path(__file__).parent / "data"

st.set_page_config(page_title="FL Market Hub", page_icon=":house:", layout="wide")

ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
ZORI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "County_zori_uc_sfrcondomfr_sm_month.csv"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}
WEEK, DAY, HOUR = 60 * 60 * 24 * 7, 60 * 60 * 24, 60 * 60

COMMENTARY_SOURCES = [
    {"name": "iBuyer — Tampa Investor Market Report", "url": "https://ibuyer.com/blog/tampa-investor-market-report/", "blurb": "Who's buying Tampa investment property"},
    {"name": "Three Avenues Group", "url": "https://www.3avesgroup.com/blog/", "blurb": "Local investor / wholesaler blog"},
    {"name": "Tampa Bay Realtor Sean", "url": "https://www.tampabayrealtorsean.com", "blurb": "Sean Tennant — realtor commentary"},
    {"name": "Liane Jamason / Corcoran Dwellings", "url": "https://www.lianejamason.com", "blurb": "Tampa-area Corcoran agent updates"},
    {"name": "Smith & Associates — Tampa Bay Market Report", "url": "https://www.smithandassociates.com/tampa-bay-market-report/", "blurb": "Luxury brokerage market report"},
    {"name": "Out Fast Property Management", "url": "https://outfastpropertymanagement.com", "blurb": "Tampa-area PM newsletter / blog"},
    {"name": "Florida Realtors", "url": "https://www.floridarealtors.org", "blurb": "Statewide MLS-backed data & news"},
    {"name": "Altos Research", "url": "https://altos.re", "blurb": "Weekly market analytics (subset free)"},
]

# Provenance — shown in the Data & methodology expander.
SOURCE_INFO = [
    ("Home values (ZHVI)", "Zillow Research", "Monthly", "https://www.zillow.com/research/data/"),
    ("Rents (ZORI)", "Zillow Research", "Monthly", "https://www.zillow.com/research/data/"),
    ("30-yr mortgage rate", "Freddie Mac PMMS", "Weekly", "https://www.freddiemac.com/pmms"),
    ("MSA unemployment", "BLS LAUS (public API)", "Monthly", "https://www.bls.gov/lau/"),
    ("MSA employment", "BLS CES (public API)", "Monthly", "https://www.bls.gov/ces/"),
    ("Building permits", "Census Building Permits Survey", "Annual", "https://www.census.gov/construction/bps/"),
]


# ──────────────────────────────────────────────────────────────────────
# Data loading — snapshot-first, live fallback
# ──────────────────────────────────────────────────────────────────────

def _empty_long() -> pd.DataFrame:
    return pd.DataFrame({"RegionName": [], "date": [], "value": []})


def _empty_series() -> pd.DataFrame:
    return pd.DataFrame({"date": [], "value": []})


def _zillow_from_snapshot(market_slug: str, kind: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{market_slug}-zillow.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df = df[df["kind"] == kind].drop(columns=["kind"]).reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=WEEK, show_spinner=False)
def fetch_zillow(url: str, market_slug: str, counties: tuple[str, ...], state: str) -> pd.DataFrame:
    """Read pre-baked snapshot if available, else live-fetch."""
    kind = "zhvi" if "zhvi" in url else "zori"
    snap = _zillow_from_snapshot(market_slug, kind)
    if snap is not None:
        return snap
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df = df[(df["StateName"] == state) & (df["RegionName"].isin(list(counties)))]
        date_cols = [c for c in df.columns if DATE_RE.match(str(c))]
        long = df.melt(id_vars=["RegionName"], value_vars=date_cols,
                       var_name="date", value_name="value")
        long["date"] = pd.to_datetime(long["date"])
        long["value"] = pd.to_numeric(long["value"], errors="coerce")
        return long.dropna(subset=["value"]).sort_values(["RegionName", "date"])
    except Exception as e:
        st.warning(f"Zillow fetch failed: {e.__class__.__name__}. Showing empty.")
        return _empty_long()


@st.cache_data(ttl=DAY, show_spinner=False)
def load_indicators(market_slug: str) -> pd.DataFrame:
    """Read the pre-baked indicators parquet (mortgage, unemployment,
    employment, permits). Columns: date, value, series, county."""
    path = DATA_DIR / f"{market_slug}-indicators.parquet"
    if not path.exists():
        return pd.DataFrame({"date": [], "value": [], "series": [], "county": []})
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame({"date": [], "value": [], "series": [], "county": []})


def indicator_series(indicators: pd.DataFrame, name: str) -> pd.DataFrame:
    """Pull one market-level series (mortgage/unemployment/employment)."""
    if indicators.empty:
        return _empty_series()
    df = indicators[indicators["series"] == name][["date", "value"]].copy()
    return df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def permits_by_year(indicators: pd.DataFrame) -> pd.DataFrame:
    """Metro total permits per year (sum across counties)."""
    if indicators.empty:
        return _empty_series()
    df = indicators[indicators["series"] == "permits"]
    if df.empty:
        return _empty_series()
    agg = df.groupby("date", as_index=False)["value"].sum()
    return agg.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_commentary(url: str) -> dict:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
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
        latest = ""
        for tag in soup.find_all(["h1", "h2", "h3"]):
            txt = (tag.get_text() or "").strip()
            if len(txt) > 12 and txt.lower() != (title or "").lower():
                latest = txt[:200]
                break
        return {"ok": True, "title": title[:200], "desc": (desc or "")[:280], "latest": latest}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}"}


def _commentary_from_snapshot() -> tuple[dict[str, dict] | None, str | None]:
    path = DATA_DIR / "commentary.json"
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("sources") or None, payload.get("fetched_at")
    except Exception:
        return None, None


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_all_commentary(urls_key: tuple[str, ...]) -> tuple[dict[str, dict], str | None]:
    snap, fetched_at = _commentary_from_snapshot()
    if snap is not None:
        return ({u: snap.get(u, {"ok": False, "error": "not in snapshot"}) for u in urls_key},
                fetched_at)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_commentary, urls_key))
    return {u: r for u, r in zip(urls_key, results)}, None


def snapshot_freshness(market_slug: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, fname in [
        ("Zillow", f"{market_slug}-zillow.parquet"),
        ("Indicators", f"{market_slug}-indicators.parquet"),
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
        cur, prior = grp["value"].iloc[-1], grp["value"].iloc[-13]
        out[region] = ((cur - prior) / prior) * 100 if prior else None
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
    return f"{'+' if sign and n > 0 else ''}{n:.1f}%"


def load_market_summary(m: Market) -> dict | None:
    zhvi_df = _zillow_from_snapshot(m.slug, "zhvi")
    zori_df = _zillow_from_snapshot(m.slug, "zori")
    if zhvi_df is None and zori_df is None:
        return None
    row: dict = {"market": m.label, "slug": m.slug}
    if zhvi_df is not None and not zhvi_df.empty:
        latest = zhvi_df.sort_values("date").groupby("RegionName").tail(1)
        row["value"] = float(latest["value"].mean())
        yoys = []
        for _, grp in zhvi_df.groupby("RegionName"):
            grp = grp.sort_values("date").reset_index(drop=True)
            if len(grp) >= 13 and grp["value"].iloc[-13]:
                yoys.append((grp["value"].iloc[-1] - grp["value"].iloc[-13])
                            / grp["value"].iloc[-13] * 100)
        row["value_yoy"] = sum(yoys) / len(yoys) if yoys else None
    else:
        row["value"], row["value_yoy"] = None, None
    if zori_df is not None and not zori_df.empty:
        latest_r = zori_df.sort_values("date").groupby("RegionName").tail(1)
        row["rent"] = float(latest_r["value"].mean())
    else:
        row["rent"] = None
    row["cap_rate"] = ((row["rent"] * 12 / row["value"]) * 100
                       if row.get("value") and row.get("rent") else None)
    return row


# ══════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════

default_slug = st.query_params.get("market", "tampa-bay")
if default_slug not in MARKETS_BY_SLUG:
    default_slug = "tampa-bay"

selected_label = st.segmented_control(
    "Market", [m.label for m in MARKETS],
    default=MARKETS_BY_SLUG[default_slug].label, label_visibility="collapsed",
)
if selected_label is None:
    selected_label = MARKETS_BY_SLUG[default_slug].label
market: Market = next(m for m in MARKETS if m.label == selected_label)
st.query_params["market"] = market.slug

title_col, fresh_col = st.columns([3, 2])
with title_col:
    st.title("FL Market Hub")
    st.caption(" · ".join(c.replace(" County", "") for c in market.counties))
with fresh_col:
    fresh = snapshot_freshness(market.slug)
    st.markdown(
        f"<div style='text-align:right;padding-top:1rem;color:#71717a;font-size:0.85rem'>"
        f"Data snapshot: <strong>{fresh.get('Zillow', 'live')}</strong></div>",
        unsafe_allow_html=True,
    )

with st.sidebar:
    st.header("Snapshot status")
    for label, ts in snapshot_freshness(market.slug).items():
        st.caption(f"**{label}:** {'live fetch (no snapshot)' if ts == 'live' else ts}")
    st.caption(
        "Data is read from pre-baked snapshots committed to the repo, "
        "refreshed weekly by a GitHub Action. Pages load in <1s."
    )
    st.divider()
    if st.button("Force live re-fetch", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    with st.expander("Share this view", expanded=False):
        qp_str = "&".join(f"{k}={v}" for k, v in st.query_params.items())
        st.caption("URL parameters encoding this exact view:")
        st.code(f"?{qp_str}", language="text")

# ── Load data ──────────────────────────────────────────────────────────
counties_t = tuple(market.counties)
zhvi = fetch_zillow(ZHVI_URL, market.slug, counties_t, market.state)
zori = fetch_zillow(ZORI_URL, market.slug, counties_t, market.state)
indicators = load_indicators(market.slug)
mortgage = indicator_series(indicators, "mortgage_30yr")
unemp = indicator_series(indicators, "unemployment")
employment = indicator_series(indicators, "employment")
permits_metro = permits_by_year(indicators)

zhvi_latest = latest_per_county(zhvi).set_index("RegionName")
zori_latest = latest_per_county(zori).set_index("RegionName")
zhvi_yoy = yoy_per_county(zhvi)
zori_yoy = yoy_per_county(zori)

metro_value = zhvi_latest["value"].mean() if not zhvi_latest.empty else None
metro_rent = zori_latest["value"].mean() if not zori_latest.empty else None
metro_value_yoy = pd.Series(zhvi_yoy).dropna().mean() if zhvi_yoy else None
metro_rent_yoy = pd.Series(zori_yoy).dropna().mean() if zori_yoy else None
rent_yield = (metro_rent * 12 / metro_value) * 100 if metro_value and metro_rent else None

last_mortgage = mortgage["value"].iloc[-1] if not mortgage.empty else None
mortgage_4w_bps = ((mortgage["value"].iloc[-1] - mortgage["value"].iloc[-5]) * 100
                   if len(mortgage) > 4 else None)
last_unemp = unemp["value"].iloc[-1] if not unemp.empty else None
unemp_yr_ago = unemp["value"].iloc[-13] if len(unemp) >= 13 else None

zhvi_as_of = zhvi["date"].max().strftime("%b %Y") if not zhvi.empty else "—"
zori_as_of = zori["date"].max().strftime("%b %Y") if not zori.empty else "—"
mortgage_as_of = mortgage["date"].max().strftime("%b %d, %Y") if not mortgage.empty else "—"
unemp_as_of = unemp["date"].max().strftime("%b %Y") if not unemp.empty else "—"
permits_as_of = (str(int(permits_metro["date"].max().year))
                 if not permits_metro.empty else "—")

# Per-county cap rates
county_caps: dict[str, float] = {}
county_values: dict[str, float] = {}
for c in market.counties:
    short = c.replace(" County", "")
    v_, r_ = zhvi_latest["value"].get(c), zori_latest["value"].get(c)
    if v_:
        county_values[short] = float(v_)
    if v_ and r_:
        cr_ = cap_rate(v_, r_)
        if cr_:
            county_caps[short] = cr_.gross
best_county = max(county_caps.items(), key=lambda kv: kv[1])[0] if county_caps else None

# ── Market Brief ───────────────────────────────────────────────────────
permits_latest = float(permits_metro["value"].iloc[-1]) if not permits_metro.empty else None
permits_prior = float(permits_metro["value"].iloc[-2]) if len(permits_metro) >= 2 else None

brief = generate_brief(MarketSnapshot(
    label=market.label,
    median_value=metro_value, value_yoy=metro_value_yoy,
    median_rent=metro_rent, rent_yoy=metro_rent_yoy,
    gross_yield=rent_yield,
    mortgage_rate=last_mortgage, mortgage_4w_bps=mortgage_4w_bps,
    unemployment=last_unemp, unemployment_yr_ago=unemp_yr_ago,
    permits_latest=permits_latest, permits_prior=permits_prior,
    permits_latest_year=int(permits_metro["date"].max().year) if not permits_metro.empty else None,
    county_caps=county_caps, county_values=county_values,
))

st.subheader("Market Brief")
st.markdown(
    f"<div style='padding:0.85rem 1rem;background:#171717;border-left:3px solid #0ea5e9;"
    f"border-radius:4px;font-size:0.95rem;margin-bottom:0.75rem'>{brief.state}</div>",
    unsafe_allow_html=True,
)
b_left, b_right = st.columns(2)
with b_left:
    st.markdown("**What's happening**")
    for line in brief.happening:
        st.markdown(f"- {line}")
with b_right:
    st.markdown("**How to take advantage**")
    for line in brief.tactics:
        st.markdown(f"- {line}")
st.caption(
    "Auto-generated from the live data below — every statement traces to a "
    "figure on this page. Not investment advice."
)

# ── Metro snapshot ─────────────────────────────────────────────────────
st.subheader("Metro snapshot")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Median home value", fmt_money(metro_value),
    f"{fmt_pct(metro_value_yoy)} YoY" if metro_value_yoy is not None else None,
    help=f"Zillow ZHVI · avg of {len(market.counties)} counties · as of {zhvi_as_of}",
)
c2.metric(
    "Median rent", fmt_money(metro_rent),
    f"{fmt_pct(metro_rent_yoy)} YoY" if metro_rent_yoy is not None else None,
    help=f"Zillow ZORI · monthly · as of {zori_as_of}",
)
c3.metric(
    "Gross rent yield", f"{rent_yield:.2f}%" if rent_yield is not None else "—",
    help="Annualized median rent ÷ median value, before expenses",
)
c4.metric(
    "30-yr mortgage", f"{last_mortgage:.2f}%" if last_mortgage is not None else "—",
    f"{mortgage_4w_bps:+.0f} bps 4w" if mortgage_4w_bps is not None else None,
    delta_color="inverse",
    help=f"Freddie Mac PMMS · weekly · week of {mortgage_as_of}",
)
st.caption(
    f"Sources — values/rents: Zillow Research ({zhvi_as_of}) · "
    f"mortgage: Freddie Mac PMMS ({mortgage_as_of})"
)

# ── Deal lens ──────────────────────────────────────────────────────────
st.subheader("Deal Lens")
st.caption("Plug in a hypothetical deal — county median rent + current mortgage "
           "rate auto-fill. All math is gross-of-fees rules of thumb.")
with st.container(border=True):
    in_col, out_col = st.columns([1, 1.4])
    with in_col:
        county_map = {c.replace(" County", ""): c for c in market.counties}
        short_names = list(county_map.keys())
        qp = st.query_params
        qp_county = qp.get("county")
        idx = short_names.index(qp_county) if qp_county in short_names else 0
        sel_short = st.selectbox("County", short_names, index=idx, key="deal_county")
        sel_county = county_map[sel_short]
        snap_val = int(zhvi_latest["value"].get(sel_county) or 350_000)
        deal_price = st.number_input("Purchase price ($)", 10_000, 5_000_000,
                                     int(qp.get("price", snap_val)), step=5_000, key="deal_price")
        deal_repair = st.number_input("Estimated repair cost ($)", 0, 1_000_000,
                                      int(qp.get("repair", 25_000)), step=5_000, key="deal_repair")
        deal_arv = st.number_input("ARV — after-repair value ($)", 10_000, 5_000_000,
                                   int(qp.get("arv", int(deal_price * 1.20))), step=5_000, key="deal_arv")
        deal_down_pct = st.slider("Down payment (%)", 0, 100, int(qp.get("down", 20)),
                                  step=5, key="deal_down")
        deal_down = deal_down_pct / 100
        deal_rate = st.slider("Mortgage rate (%)", 3.0, 12.0,
                              float(qp.get("rate", last_mortgage if last_mortgage else 6.5)),
                              step=0.05, key="deal_rate")
        st.query_params.update({
            "county": sel_short, "price": str(deal_price), "repair": str(deal_repair),
            "arv": str(deal_arv), "down": str(deal_down_pct), "rate": f"{deal_rate:.2f}",
        })
    with out_col:
        county_rent = zori_latest["value"].get(sel_county)
        cr = cap_rate(deal_price, county_rent) if county_rent else None
        pr = price_to_rent(deal_price, county_rent) if county_rent else None
        monthly_piti = piti(deal_price, deal_down, deal_rate)
        mao = mao_70(deal_arv, deal_repair)
        brrrr = brrrr_refinance(deal_price, deal_repair, deal_arv)
        st.markdown(f"**Auto-filled:** median rent in {sel_short} = "
                    f"**{fmt_money(county_rent)}/mo** (Zillow ZORI, {zori_as_of}) · "
                    f"rate **{deal_rate:.2f}%**")
        m1, m2, m3 = st.columns(3)
        m1.metric("Gross cap rate", f"{cr.gross:.2f}%" if cr else "—",
                  f"Net (40% opex): {cr.net:.2f}%" if cr else None)
        m2.metric("Price-to-rent", f"{pr:.1f}x" if pr else "—",
                  help="<15 cheap · 15–20 fair · >20 expensive")
        cashflow = (county_rent or 0) - (monthly_piti or 0)
        m3.metric("Monthly cashflow", fmt_money(cashflow),
                  f"Rent {fmt_money(county_rent)} − PITI {fmt_money(monthly_piti)}",
                  delta_color="off" if cashflow == 0 else ("normal" if cashflow > 0 else "inverse"))
        st.divider()
        m4, m5, m6 = st.columns(3)
        m4.metric("MAO (70% rule)", fmt_money(mao), f"vs ask {fmt_money(deal_price)}",
                  delta_color=("normal" if mao and deal_price <= mao else "inverse"),
                  help="ARV × 70% − repair")
        m5.metric("BRRRR refi loan", fmt_money(brrrr.refi_loan) if brrrr else "—",
                  f"75% LTV of ARV {fmt_money(deal_arv)}" if brrrr else None)
        m6.metric("Left in after refi", fmt_money(brrrr.left_in) if brrrr else "—",
                  "negative = cash-out exceeds basis" if brrrr and brrrr.left_in < 0 else None,
                  delta_color=("inverse" if brrrr and brrrr.left_in > 0 else "normal"))
        county_zhvi = zhvi[zhvi["RegionName"] == sel_county][["date", "value"]].rename(columns={"value": "value_zhvi"})
        county_zori = zori[zori["RegionName"] == sel_county][["date", "value"]].rename(columns={"value": "value_zori"})
        if not county_zhvi.empty and not county_zori.empty:
            joined = county_zhvi.merge(county_zori, on="date", how="inner")
            if not joined.empty:
                joined["cap_rate_pct"] = joined["value_zori"] * 12 / joined["value_zhvi"] * 100
                tail = joined.tail(60)[["date", "cap_rate_pct"]].rename(
                    columns={"cap_rate_pct": f"{sel_short} cap %"})
                st.caption(f"Historical gross cap rate — {sel_short} (60 months)")
                st.line_chart(tail.set_index("date"), height=160, color="#22c55e")

# ── By county ──────────────────────────────────────────────────────────
st.subheader("By county")
st.caption(f"Gross cap = ZORI rent ÷ ZHVI value, annualized. Data as of {zhvi_as_of}. "
           f"Best cap rate in this metro gets a ⭐.")
cols = st.columns(len(market.counties))
for col, county in zip(cols, market.counties):
    short = county.replace(" County", "")
    v, r = zhvi_latest["value"].get(county), zori_latest["value"].get(county)
    vy, ry = zhvi_yoy.get(county), zori_yoy.get(county)
    county_cr = cap_rate(v, r) if (v and r) else None
    with col:
        with st.container(border=True):
            st.markdown(f"**{short}**{' ⭐' if short == best_county else ''}")
            sub = st.columns(2)
            sub[0].metric("Value", fmt_money(v, compact=True),
                          f"{fmt_pct(vy)} YoY" if vy is not None else None)
            sub[1].metric("Rent", fmt_money(r),
                          f"{fmt_pct(ry)} YoY" if ry is not None else None)
            if county_cr:
                st.caption(f"**Gross cap:** {county_cr.gross:.2f}% · "
                           f"**Net:** {county_cr.net:.2f}%")
            spark = zhvi[zhvi["RegionName"] == county].tail(60)[["date", "value"]]
            if not spark.empty:
                st.line_chart(spark.set_index("date"), height=120, color="#0ea5e9")

# ── Labor + supply + rates charts ──────────────────────────────────────
st.subheader("Labor, supply & rates")
lc, rc = st.columns(2)
with lc:
    st.markdown(f"**MSA unemployment** — {market.label}")
    st.caption(f"BLS LAUS · monthly · {last_unemp:.1f}% as of {unemp_as_of}"
               if last_unemp is not None else "BLS LAUS · monthly")
    if not unemp.empty:
        st.line_chart(unemp.tail(72).set_index("date")[["value"]], height=220, color="#f59e0b")
    else:
        st.info("Unemployment data unavailable.")
    st.markdown("**Building permits** — metro total, annual")
    permits_yoy = None
    if len(permits_metro) >= 2 and permits_metro["value"].iloc[-2]:
        permits_yoy = ((permits_metro["value"].iloc[-1] - permits_metro["value"].iloc[-2])
                       / permits_metro["value"].iloc[-2] * 100)
    st.caption(f"Census Building Permits Survey · annual · {permits_as_of}"
               + (f" · {fmt_pct(permits_yoy)} YoY" if permits_yoy is not None else ""))
    if not permits_metro.empty:
        st.bar_chart(permits_metro.set_index("date")[["value"]], height=220, color="#22c55e")
    else:
        st.info("Permits data unavailable.")
with rc:
    st.markdown("**30-yr fixed mortgage rate (US)**")
    st.caption(f"Freddie Mac PMMS · weekly · {last_mortgage:.2f}% week of {mortgage_as_of}"
               if last_mortgage is not None else "Freddie Mac PMMS · weekly")
    if not mortgage.empty:
        st.line_chart(mortgage.tail(260).set_index("date")[["value"]], height=220, color="#a855f7")
    else:
        st.info("Mortgage data unavailable.")
    if not employment.empty:
        emp_yoy = None
        if len(employment) >= 13 and employment["value"].iloc[-13]:
            emp_yoy = ((employment["value"].iloc[-1] - employment["value"].iloc[-13])
                       / employment["value"].iloc[-13] * 100)
        st.markdown(f"**MSA employment** — {market.label}")
        st.caption(f"BLS CES · monthly · total nonfarm jobs (thousands)"
                   + (f" · {fmt_pct(emp_yoy)} YoY" if emp_yoy is not None else ""))
        st.line_chart(employment.tail(72).set_index("date")[["value"]], height=220, color="#0ea5e9")

# ── Compare all FL markets ─────────────────────────────────────────────
st.subheader("Compare all FL markets")
st.caption("Side-by-side ranking of every metro — sort any column.")
summary_rows = [r for r in (load_market_summary(m) for m in MARKETS) if r]
if summary_rows:
    sdf = pd.DataFrame(summary_rows)
    st.dataframe(
        pd.DataFrame({
            "Market": sdf["market"],
            "Median value": sdf["value"].apply(lambda v: fmt_money(v, compact=True) if v else "—"),
            "Median rent": sdf["rent"].apply(lambda v: fmt_money(v) if v else "—"),
            "Value YoY": sdf["value_yoy"].apply(lambda v: fmt_pct(v) if v is not None else "—"),
            "Cap rate": sdf["cap_rate"],
        }),
        width="stretch", hide_index=True,
        column_config={"Cap rate": st.column_config.ProgressColumn(
            "Gross cap rate", format="%.2f%%", min_value=0, max_value=10)},
    )
else:
    st.info("No market snapshots yet — run `python scripts/build_snapshot.py`.")

# ── Local commentary ───────────────────────────────────────────────────
st.subheader("Local commentary")
urls = tuple(s["url"] for s in COMMENTARY_SOURCES)
comm_results, comm_fetched = fetch_all_commentary(urls)
ok_count = sum(1 for r in comm_results.values() if r.get("ok"))
st.caption(f"Latest from {ok_count}/{len(COMMENTARY_SOURCES)} Tampa Bay realtors, PMs "
           f"and analysts" + (f" · captured {comm_fetched[:10]}" if comm_fetched else "")
           + ". Click a title to read on the source site.")
ccols = st.columns(2)
for i, source in enumerate(COMMENTARY_SOURCES):
    res = comm_results.get(source["url"], {})
    with ccols[i % 2]:
        with st.container(border=True):
            st.markdown(f"**[{source['name']}]({source['url']})**")
            st.caption(source["blurb"])
            if not res.get("ok"):
                st.caption(f":red[Could not reach source — {res.get('error', 'unknown')}]")
            else:
                if res.get("title"):
                    st.markdown(f"_{res['title']}_")
                if res.get("latest") and res["latest"].lower() != (res.get("title") or "").lower():
                    st.markdown(f"**Latest:** {res['latest']}")
                if res.get("desc"):
                    st.write(res["desc"])

# ── Data & methodology ─────────────────────────────────────────────────
with st.expander("Data & methodology — every number, its source and cadence"):
    st.dataframe(
        pd.DataFrame(SOURCE_INFO, columns=["Field", "Source", "Cadence", "Reference"]),
        width="stretch", hide_index=True,
        column_config={"Reference": st.column_config.LinkColumn("Reference")},
    )
    st.markdown(
        "- **Gross cap rate** = annual median rent ÷ median value × 100, before any "
        "expenses. **Net cap** assumes 40% operating expenses.\n"
        "- **YoY** compares the latest month to 12 months prior (Zillow), or latest "
        "year to prior year (permits).\n"
        "- **PITI** uses a 1.2% effective FL property-tax rate and $2,400/yr insurance "
        "baseline — override per deal.\n"
        "- All series are pre-baked weekly into the repo by a GitHub Action and read "
        "from disk, so the dashboard never blocks on a live API.\n"
        "- The Market Brief is rule-based on the figures above — no external commentary "
        "is fed into it."
    )
    fresh = snapshot_freshness(market.slug)
    st.caption("Snapshot files last refreshed — "
               + " · ".join(f"{k}: {v}" for k, v in fresh.items()))

st.divider()
st.caption(
    "Data: Zillow Research · Freddie Mac PMMS · U.S. Bureau of Labor Statistics · "
    "U.S. Census Bureau. All sources free and public, no API keys. "
    "Figures are estimates from third-party data — verify before transacting. "
    "Not investment advice."
)
