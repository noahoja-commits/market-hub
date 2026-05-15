# FL Market Hub

Streamlit dashboard for Florida real estate market data across 5 metros
(Tampa Bay, Orlando, SW Florida, Jacksonville, Space Coast) — home
values, rents, mortgage rates, MSA-level indicators, plus a built-in
deal-math calculator and a feed of local realtor/PM commentary.

## Sources (all free, public, no API keys)

- **Zillow Research** — ZHVI (county home values), ZORI (county rents), monthly
- **FRED** — MORTGAGE30US (national 30-yr rate) + per-MSA HPI and unemployment
- **Commentary feeds** — iBuyer Tampa report, Three Avenues Group, Tampa Bay
  Realtor Sean, Liane Jamason / Corcoran, Smith & Associates, Out Fast Property
  Management, Florida Realtors, Altos Research

## Features

- **Multi-market selector** — switch between Tampa Bay / Orlando / SWFL / Jax /
  Space Coast. Choice persists via `?market=<slug>` query param.
- **Deal Lens** — plug in a price + repair + ARV, auto-fills the county median
  rent and current mortgage rate, returns cap rate, P/R ratio, monthly cashflow,
  MAO from the 70% rule, and BRRRR refi cash-out.
- **Pre-baked snapshots** — `data/*.parquet` is refreshed weekly via a GitHub
  Action so page loads are <1 second instead of 30 seconds.
- **Graceful fallback** — every source returns empty if it fails, page still
  renders, broken section shows a clear notice.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open http://localhost:8501.

## Refresh data manually

```bash
python scripts/build_snapshot.py
git add data/ && git commit -m "data refresh" && git push
```

Or trigger the GitHub Action:
```bash
gh workflow run "Refresh data snapshot"
```

## Deploy to Streamlit Community Cloud (free)

1. Push this repo to GitHub (already at `noahoja-commits/market-hub`)
2. Go to https://share.streamlit.io
3. Sign in with GitHub, click "Create app"
4. Select repo `noahoja-commits/market-hub`, branch `main`, main file `streamlit_app.py`
5. Click Deploy. URL will be `https://<chosen-subdomain>.streamlit.app`.

Future pushes auto-deploy. The weekly GitHub Action refreshes data
without any action on Streamlit Cloud's side.

## Tests

```bash
python -m pytest tests/
```

Currently covers `lib/deal_math.py` (cap rate, PITI, MAO, BRRRR).
