"""International Cost of Capital app (Streamlit).

Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country, using bottom-up industry betas (Damodaran),
BBB spread (Damodaran), corporate tax rates (OECD) and 10-year government
yields (Trading Economics).

Run:  streamlit run app.py
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------
BETA_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
OECD_PAGE = ("https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
             "full-report/statutory-corporate-income-tax-rates_440f9286.html")
# The OECD web page sits behind a bot-wall; the same table (combined statutory
# CIT rate, Table II.1) is served by the OECD SDMX API, which is used instead.
OECD_API = ("https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,1.0/all"
            "?startPeriod=2022&dimensionAtObservation=AllDimensions")
TE_URL = "https://tradingeconomics.com/bonds"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SNAPSHOT = Path(__file__).with_name("data_snapshot.json")

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"

# Currency of each Trading Economics country label (for display only).
CURRENCY = {
    "United States": "USD", "United Kingdom": "GBP", "Japan": "JPY", "Australia": "AUD",
    "Germany": "EUR", "France": "EUR", "Italy": "EUR", "Spain": "EUR", "Netherlands": "EUR",
    "Austria": "EUR", "Belgium": "EUR", "Finland": "EUR", "Greece": "EUR", "Ireland": "EUR",
    "Portugal": "EUR", "Slovakia": "EUR", "Slovenia": "EUR", "Lithuania": "EUR",
    "Croatia": "EUR", "Brazil": "BRL", "Russia": "RUB", "India": "INR", "Canada": "CAD",
    "Mexico": "MXN", "Peru": "PEN", "Chile": "CLP", "Colombia": "COP", "Switzerland": "CHF",
    "Turkey": "TRY", "China": "CNY", "Hong Kong": "HKD", "Taiwan": "TWD", "South Korea": "KRW",
    "Singapore": "SGD", "Indonesia": "IDR", "Malaysia": "MYR", "Thailand": "THB",
    "Philippines": "PHP", "Vietnam": "VND", "Pakistan": "PKR", "Israel": "ILS",
    "Sweden": "SEK", "Norway": "NOK", "Denmark": "DKK", "Poland": "PLN", "Hungary": "HUF",
    "Czech Republic": "CZK", "Romania": "RON", "Iceland": "ISK", "New Zealand": "NZD",
    "South Africa": "ZAR", "Nigeria": "NGN", "Kenya": "KES", "Zambia": "ZMW",
}
# Trading Economics label -> ISO3 when the label is not a standard country name.
ISO_ALIAS = {"South Korea": "KOR", "Russia": "RUS", "Taiwan": "TWN", "Vietnam": "VNM",
             "Turkey": "TUR", "Czech Republic": "CZE", "Hong Kong": "HKG"}


# ----------------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fetch_betas() -> dict:
    r = requests.get(BETA_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Industry Averages", header=None)
    hdr = int(raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Industry Name"][0])
    df = raw.iloc[hdr + 1:, :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr, :]]
    df = df.dropna(subset=["Industry Name"])
    df = df[pd.to_numeric(df["Unlevered beta"], errors="coerce").notna()]
    df = df[~df["Industry Name"].astype(str).str.startswith("Total Market")]
    betas = {str(n).strip(): float(b) for n, b in zip(df["Industry Name"], df["Unlevered beta"])}
    stamp = raw.iloc[0, 1]
    date = pd.Timestamp(stamp).strftime("%Y-%m-%d") if pd.notna(stamp) else "n/a"
    return {"values": betas, "as_of": f"data updated {date}", "retrieved": _now(), "url": BETA_URL}


def fetch_bbb_spread() -> dict:
    r = requests.get(RATINGS_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    tbl = pd.read_html(io.StringIO(r.text))[0]
    # First block of columns = "large non-financial service firms".
    row = tbl[tbl.iloc[:, 2].astype(str).str.contains("Baa2/BBB", regex=False)].iloc[0]
    spread = float(str(row.iloc[3]).replace("%", "")) / 100
    m = re.search(r"(Last[- ]updated|Updated)[^<]{0,40}(\d{4})", r.text, re.I)
    as_of = f"page shows {m.group(0)}" if m else "page has no date stamp"
    lm = r.headers.get("Last-Modified")
    if lm:
        as_of = f"page last modified {lm}"
    return {"value": spread, "as_of": as_of, "retrieved": _now(), "url": RATINGS_URL}


def fetch_oecd_tax() -> dict:
    import pycountry
    r = requests.get(OECD_API, headers={**HEADERS, "Accept": "application/vnd.sdmx.data+csv; charset=utf-8"},
                     timeout=90)
    r.raise_for_status()
    d = pd.read_csv(io.StringIO(r.text))
    # Combined (central + sub-central) statutory CIT rate, whole-economy basis.
    d = d[(d["MEASURE"] == "CIT_C") & (d["TARGETING"] == "ST") & (d["SECTOR"] == "S13")]
    d = d.sort_values("TIME_PERIOD").groupby("REF_AREA").tail(1)
    by_iso = {a: (float(v) / 100, int(y)) for a, v, y in zip(d.REF_AREA, d.OBS_VALUE, d.TIME_PERIOD)}
    return {"by_iso": by_iso, "as_of": f"statutory rates, year {max(y for _, y in by_iso.values())}",
            "retrieved": _now(), "url": OECD_PAGE, "api": OECD_API}


def _iso3(name: str) -> str | None:
    if name in ISO_ALIAS:
        return ISO_ALIAS[name]
    try:
        import pycountry
        return pycountry.countries.lookup(name).alpha_3
    except LookupError:
        return None


def fetch_yields() -> dict:
    r = requests.get(TE_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for t in pd.read_html(io.StringIO(r.text)):
        if t.shape[1] < 4:
            continue
        cols = [str(c) for c in t.columns]
        if "Yield" not in cols or "Date" not in cols:
            continue
        for _, row in t.iterrows():
            name = str(row.iloc[1]).strip()
            y = pd.to_numeric(row["Yield"], errors="coerce")
            if name and name != "nan" and pd.notna(y) and name not in out:
                out[name] = {"yield": float(y) / 100, "date": str(row["Date"])}
    if "United States" not in out:
        raise ValueError("U.S. yield not found on Trading Economics page")
    return {"values": out, "retrieved": _now(), "url": TE_URL}


def fetch_all() -> dict:
    """Fetch every source independently; fall back to the repo snapshot per source."""
    snap = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    data, status = {}, {}
    for key, fn in [("betas", fetch_betas), ("spread", fetch_bbb_spread),
                    ("tax", fetch_oecd_tax), ("yields", fetch_yields)]:
        try:
            data[key] = fn()
            status[key] = "live"
        except Exception as e:  # noqa: BLE001 - show the reason, use snapshot
            if key in snap:
                data[key] = snap[key]
                status[key] = f"snapshot (live fetch failed: {type(e).__name__}: {str(e)[:80]})"
            else:
                raise RuntimeError(f"Could not fetch {key} and no snapshot available: {e}") from e
    if all(s == "live" for s in status.values()):
        try:
            SNAPSHOT.write_text(json.dumps(data, indent=1))
        except OSError:
            pass
    data["status"] = status
    return data


def country_table(data: dict) -> pd.DataFrame:
    """One row per country with a yield: yield, date, currency, tax rate (if known)."""
    by_iso = {k: tuple(v) for k, v in data["tax"]["by_iso"].items()}
    rows = []
    for name, v in data["yields"]["values"].items():
        if name == "Euro area":
            continue
        iso = _iso3(name)
        tax = by_iso.get(iso, (None, None))[0] if iso else None
        rows.append({"Country": name, "Currency": CURRENCY.get(name, "local"), "Yield": v["yield"],
                     "Yield date": v["date"], "Tax": tax})
    return pd.DataFrame(rows).sort_values("Country").reset_index(drop=True)


# ----------------------------------------------------------------------------
# Calculations (pure functions - used by the UI and by verify.py)
# ----------------------------------------------------------------------------
def relever_beta(beta_u: float, tax: float, debt_share: float) -> float:
    """Hamada: beta_L = beta_U * (1 + (1 - t) * D/E), with D/E = d / (1 - d)."""
    de = debt_share / (1 - debt_share) if debt_share < 1 else float("inf")
    return beta_u * (1 + (1 - tax) * de)


def convert_rate(usd_rate: float, y_us: float, y_for: float) -> float:
    """Convert a USD nominal rate to a foreign-currency rate via the 10-year
    government-yield differential (interest-rate-parity / expected inflation):
        (1 + k_for) = (1 + k_usd) * (1 + y_for) / (1 + y_us)"""
    return (1 + usd_rate) * (1 + y_for) / (1 + y_us) - 1


def cost_of_capital(beta_u, tax, spread_usd, y_us, y_for, erp, debt_share,
                    spread_for_override=None) -> dict:
    d, e = debt_share, 1 - debt_share
    beta_l = relever_beta(beta_u, tax, d)
    # ---- USD
    ke_usd = y_us + beta_l * erp
    kd_usd = y_us + spread_usd
    wacc_usd = e * ke_usd + d * kd_usd * (1 - tax)
    # ---- foreign currency
    ke_for = convert_rate(ke_usd, y_us, y_for)
    kd_for_auto = convert_rate(kd_usd, y_us, y_for)
    spread_for_auto = kd_for_auto - y_for
    if spread_for_override is None:
        kd_for, spread_for = kd_for_auto, spread_for_auto
    else:
        kd_for, spread_for = y_for + spread_for_override, spread_for_override
    wacc_for = e * ke_for + d * kd_for * (1 - tax)
    return {
        "beta_levered": beta_l, "de_ratio": d / e if e else float("inf"),
        "usd": {"rf": y_us, "ke": ke_usd, "spread": spread_usd, "kd": kd_usd,
                "kd_after_tax": kd_usd * (1 - tax), "wacc": wacc_usd},
        "for": {"rf": y_for, "ke": ke_for, "spread": spread_for, "kd": kd_for,
                "kd_after_tax": kd_for * (1 - tax), "wacc": wacc_for,
                "spread_auto": spread_for_auto},
    }


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="International Cost of Capital", page_icon="🌍", layout="wide")

    @st.cache_data(show_spinner="Fetching latest data from the sources…", ttl=6 * 3600)
    def load():
        return fetch_all()

    st.title("🌍 International Cost of Capital: USD vs. Foreign Currency")
    st.caption("Compare a project's cost of equity, cost of debt and WACC in USD and in the currency "
               "of another country.")

    with st.sidebar:
        st.header("Data")
        if st.button("🔄 Refresh data", width="stretch"):
            load.clear()
            st.rerun()

    try:
        data = load()
    except Exception as e:  # noqa: BLE001
        st.error(f"Data fetch failed and no snapshot is available: {e}")
        st.stop()

    betas = data["betas"]["values"]
    countries = country_table(data)
    crow = countries.set_index("Country")
    us_tax_fetched = data["tax"]["by_iso"].get("USA", [None])[0]

    # ---------------- Sidebar inputs ----------------
    with st.sidebar:
        st.header("Project")
        industries = sorted(betas)
        industry = st.selectbox("Industry", industries,
                                index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
        names = countries["Country"].tolist()
        country = st.selectbox("Target country", names,
                               index=names.index(DEFAULT_COUNTRY) if DEFAULT_COUNTRY in names else 0)
        erp = st.number_input("Equity risk premium (%)", 0.0, 20.0, 6.5, 0.25, format="%.2f") / 100
        debt_share = st.slider("Target debt share D/(D+E) (%)", 0, 100, 30, 1) / 100

        cur = crow.loc[country, "Currency"]
        is_us = country == "United States"

        st.header("Manual overrides")
        st.caption("Tick a box to replace the fetched value.")

        def ovr(label, fetched, key, step, lo, hi, fmt, pct=True, force=False, note=""):
            on = st.checkbox(f"Override {label}", value=force, key=f"{key}_on", disabled=force)
            shown = (fetched * 100 if pct else fetched) if fetched is not None else (25.0 if pct else 1.0)
            if on or force:
                v = st.number_input(f"{label}{note}", lo, hi, float(round(shown, 4)), step, format=fmt, key=f"{key}_v")
                return v / 100 if pct else v
            st.caption(f"{label}: **{shown:.2f}{'%' if pct else ''}** (fetched)")
            return fetched

        beta_u = ovr("unlevered beta", betas[industry], "beta", 0.01, 0.0, 5.0, "%.3f", pct=False)
        spread_usd = ovr("USD BBB spread (%)", data["spread"]["value"], "spr", 0.05, 0.0, 20.0, "%.2f")
        y_us = ovr("U.S. 10Y yield (%)", crow.loc["United States", "Yield"], "yus", 0.05, -2.0, 60.0, "%.3f")
        y_for_f = crow.loc[country, "Yield"]
        y_for = ovr(f"{country} 10Y yield (%)", y_for_f, "yfor", 0.05, -2.0, 60.0, "%.3f")
        tax_us = ovr("U.S. corporate tax (%)", us_tax_fetched, "tus", 0.5, 0.0, 70.0, "%.2f",
                     force=us_tax_fetched is None)
        tax_for_fetched = None if pd.isna(crow.loc[country, "Tax"]) else float(crow.loc[country, "Tax"])
        tax_for = ovr(f"{country} corporate tax (%)", tax_for_fetched, "tfor", 0.5, 0.0, 70.0, "%.2f",
                      force=tax_for_fetched is None,
                      note=" - not in OECD data, enter manually" if tax_for_fetched is None else "")

        spr_on = st.checkbox(f"Override {cur} BBB spread (%)", key="sprf_on",
                             help="If off, the foreign spread is calculated from the yield differential.")
        spr_for_ovr = None
        if spr_on:
            spr_for_ovr = st.number_input(f"{cur} BBB spread (%)", 0.0, 50.0, 2.0, 0.05, format="%.2f",
                                          key="sprf_v") / 100

    # Project tax toggle (main area, prominent)
    left, right = st.columns([1, 2])
    with left:
        tax_choice = st.radio("Project tax rate", ["U.S.", country if not is_us else "U.S. (selected country)"],
                              horizontal=True)
    tax = tax_us if tax_choice == "U.S." else tax_for
    with right:
        st.info(f"Using **{tax_choice}** corporate tax rate of **{tax:.2%}** for both currencies "
                f"(beta re-levering and interest tax shield).")

    res = cost_of_capital(beta_u, tax, spread_usd, y_us, y_for, erp, debt_share, spr_for_ovr)
    u, f = res["usd"], res["for"]

    # ---------------- Results side by side ----------------
    st.subheader(f"Results — {industry}")
    c1, c2 = st.columns(2)
    for col, title, r in [(c1, "USD", u), (c2, f"{country} ({cur})", f)]:
        with col:
            st.markdown(f"### {title}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Cost of equity", f"{r['ke']:.2%}")
            m2.metric("Pre-tax cost of debt", f"{r['kd']:.2%}")
            m3.metric("WACC", f"{r['wacc']:.2%}")
    side = pd.DataFrame({
        "Item": ["Risk-free (10Y gov. yield)", "Unlevered beta", "Levered beta", "Equity risk premium",
                 "Cost of equity", "BBB spread", "Pre-tax cost of debt", "Tax rate", "After-tax cost of debt",
                 "Equity weight", "Debt weight", "WACC"],
        "USD": [u["rf"], beta_u, res["beta_levered"], erp, u["ke"], u["spread"], u["kd"], tax,
                u["kd_after_tax"], 1 - debt_share, debt_share, u["wacc"]],
        f"{country} ({cur})": [f["rf"], beta_u, res["beta_levered"], erp, f["ke"], f["spread"], f["kd"], tax,
                               f["kd_after_tax"], 1 - debt_share, debt_share, f["wacc"]],
    })
    side["Difference"] = side.iloc[:, 2] - side.iloc[:, 1]
    is_beta = side["Item"].str.contains("beta")

    def fmt(df):
        out = df.copy().astype(object)
        for i in df.index:
            for c in df.columns[1:]:
                out.loc[i, c] = f"{df.loc[i, c]:.3f}" if is_beta[i] else f"{df.loc[i, c]:.2%}"
        return out
    st.dataframe(fmt(side), hide_index=True, width="stretch")
    if spr_for_ovr is None:
        st.caption(f"{cur} BBB spread is the automatic result: (1+Kd_USD)·(1+y_{cur})/(1+y_USD) − 1 − y_{cur} "
                   f"= {f['spread_auto']:.2%}.")
    else:
        st.caption(f"{cur} BBB spread overridden to {spr_for_ovr:.2%} (automatic value would be "
                   f"{f['spread_auto']:.2%}). USD results are unaffected.")

    st.bar_chart(pd.DataFrame({"USD": [u["ke"], u["kd"], u["wacc"]],
                               cur: [f["ke"], f["kd"], f["wacc"]]},
                              index=["Cost of equity", "Pre-tax cost of debt", "WACC"]))

    # ---------------- Assumptions ----------------
    with st.expander("Main assumptions and formulas", expanded=False):
        st.markdown(f"""
* **Unlevered beta** = industry average from Damodaran (global/US dataset), re-levered at the target
  capital structure: β_L = β_U × [1 + (1 − t) × D/E], with D/E = d/(1 − d). The same β_L is used in both currencies
  (business risk does not depend on the currency).
* **Cost of equity (USD)** = U.S. 10Y yield + β_L × equity risk premium.
* **Cost of debt (USD)** = U.S. 10Y yield + Damodaran Baa2/BBB spread (large non-financial firms).
* **Foreign currency**: USD rates are translated using the government-bond yield differential
  (expected-inflation / interest-rate parity):
  `(1 + k_foreign) = (1 + k_USD) × (1 + y_foreign) / (1 + y_US)`.
  Equal 10Y yields therefore give identical results; the foreign BBB spread is the converted cost of debt minus the
  foreign government yield unless overridden.
* **WACC** = E/V × K_e + D/V × K_d × (1 − t), using the *same* tax rate, debt share and equity risk premium in both currencies.
* Government yields are used as the risk-free rate for both countries (no sovereign default-spread adjustment).
* Corporate tax: OECD combined (central + sub-national) statutory rate; choose U.S. or selected-country rate above.
* Debt share is a *target* weight and is not iterated with beta or spread.
        """)

    # ---------------- Sources ----------------
    with st.expander("Data sources, dates and values used", expanded=True):
        stt = data["status"]
        src = pd.DataFrame([
            ["Industry unlevered beta", f"{betas[industry]:.3f}", data["betas"]["as_of"], data["betas"]["retrieved"], stt["betas"], BETA_URL],
            ["USD BBB spread (Baa2/BBB)", f"{data['spread']['value']:.2%}", data["spread"]["as_of"], data["spread"]["retrieved"], stt["spread"], RATINGS_URL],
            ["U.S. corporate tax", "n/a" if us_tax_fetched is None else f"{us_tax_fetched:.2%}", data["tax"]["as_of"], data["tax"]["retrieved"], stt["tax"], OECD_PAGE],
            [f"{country} corporate tax", "n/a" if tax_for_fetched is None else f"{tax_for_fetched:.2%}", data["tax"]["as_of"], data["tax"]["retrieved"], stt["tax"], OECD_PAGE],
            ["U.S. 10Y yield", f"{crow.loc['United States', 'Yield']:.3%}", f"quote date {crow.loc['United States', 'Yield date']}", data["yields"]["retrieved"], stt["yields"], TE_URL],
            [f"{country} 10Y yield", f"{y_for_f:.3%}", f"quote date {crow.loc[country, 'Yield date']}", data["yields"]["retrieved"], stt["yields"], TE_URL],
        ], columns=["Item", "Fetched value", "Data date", "Retrieved", "Status", "Source"])
        st.dataframe(src, hide_index=True, width="stretch",
                     column_config={"Source": st.column_config.LinkColumn()})
        st.caption("OECD figures are read from the OECD SDMX API behind the same Statutory CIT table as the linked page "
                   f"(the web page itself blocks automated access). Fetched values shown here ignore manual overrides. "
                   f"Currently used: beta {beta_u:.3f}, BBB spread {spread_usd:.2%}, U.S. yield {y_us:.3%}, "
                   f"{country} yield {y_for:.3%}.")

    # ---------------- All-industry comparison ----------------
    st.subheader("All-industry comparison")
    rows = []
    for ind, b in betas.items():
        bu = beta_u if ind == industry else b
        r = cost_of_capital(bu, tax, spread_usd, y_us, y_for, erp, debt_share, spr_for_ovr)
        rows.append({"Industry": ind, "Unlevered beta": bu, "Levered beta": r["beta_levered"],
                     "Ke USD": r["usd"]["ke"], "WACC USD": r["usd"]["wacc"],
                     f"Ke {cur}": r["for"]["ke"], f"WACC {cur}": r["for"]["wacc"]})
    allind = pd.DataFrame(rows).sort_values("WACC USD", ascending=False).reset_index(drop=True)
    pct_cols = [c for c in allind.columns if c.startswith(("Ke", "WACC"))]
    st.dataframe(allind.style.format({**{c: "{:.2%}" for c in pct_cols}, "Unlevered beta": "{:.3f}",
                                      "Levered beta": "{:.3f}"}),
                 hide_index=True, width="stretch", height=420)
    st.caption("Same ERP, debt share, tax rate, yields and spread settings for every industry; "
               "a manual beta override only affects the selected industry.")
    st.bar_chart(allind.set_index("Industry")[["WACC USD", f"WACC {cur}"]], height=400)

    # ---------------- Downloads ----------------
    st.subheader("Download")
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Selected-industry results (CSV)", side.to_csv(index=False).encode(),
                       "cost_of_capital_results.csv", "text/csv", width="stretch")
    d2.download_button("⬇️ All-industry comparison (CSV)", allind.to_csv(index=False).encode(),
                       "cost_of_capital_all_industries.csv", "text/csv", width="stretch")
    st.caption("Educational tool. Verify inputs before relying on results.")


if __name__ == "__main__":
    main()
