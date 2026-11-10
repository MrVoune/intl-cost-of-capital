# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD and in the currency of a selected country**.

## Features
- Live data (with **Refresh data** button; sources and dates shown in the app):
  - Industry unlevered betas and Baa2/BBB spread: Aswath Damodaran (NYU Stern)
  - Corporate tax rates: OECD statutory CIT table (read via the OECD SDMX API, because the web page blocks scrapers)
  - U.S. and country 10-year government yields: Trading Economics (scraped)
  - If a live fetch fails, the app falls back to `data_snapshot.json` and says so.
- Select industry and target country; adjust equity risk premium and debt share; toggle U.S. vs. country tax rate.
- Manual overrides for unlevered beta, tax rates, USD BBB spread, both government yields and the foreign BBB spread (if off, the foreign spread is computed automatically).
- Side-by-side USD vs. foreign results, assumptions, all-industry comparison, CSV downloads.
- Defaults: Software (System & Application), United States, U.S. tax, 6.5% ERP, 30% debt.

## Method
- Levered beta: `βL = βU × (1 + (1 − t) × D/E)`
- USD: `Ke = y_US + βL × ERP`, `Kd = y_US + BBB spread`, `WACC = E/V·Ke + D/V·Kd·(1 − t)`
- Foreign currency: `(1 + k_for) = (1 + k_USD) × (1 + y_for) / (1 + y_US)` for both Ke and Kd; foreign spread = Kd_for − y_for (or manual override). Same tax rate, debt share and ERP in both currencies.

## Verification
`python verify.py` checks a hand-computed example plus: equal yields → equal results; zero debt → WACC = Ke; foreign spread override leaves USD unchanged.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Deploy: push to GitHub and create the app on https://share.streamlit.io with `app.py` as the main file.
