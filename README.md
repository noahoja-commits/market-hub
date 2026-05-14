# Market Hub

Streamlit dashboard tracking the Tampa Bay real estate market
(Hillsborough, Pinellas, Pasco, Hernando counties).

## Data sources

All free, public, no API keys:

- **Zillow Research** — ZHVI (county home values), ZORI (county rents), monthly
- **FRED** (Federal Reserve Bank of St. Louis):
  - `MORTGAGE30US` — 30-year fixed mortgage rate, weekly
  - `ATNHPIUS45300Q` — Tampa MSA home price index, quarterly
  - `TAMP312URN` — Tampa MSA unemployment, monthly

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open http://localhost:8501.

## Caching

Data is cached via `@st.cache_data`:
- Zillow: 7 days
- FRED: 1 day

Hit "Refresh data now" in the sidebar to force re-fetch.

## Deploy

Free options:
- [Streamlit Community Cloud](https://streamlit.io/cloud) — connect this GitHub repo, deploys on push
- Self-host: any Python host (Fly.io, Railway, Render)
