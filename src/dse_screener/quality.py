"""Quality metrics per company: the 'good reputation, good business' check."""

from __future__ import annotations

import pandas as pd

from .db import Database

# Metrics the quality filter can use (names referenced in config/profiles/*.yaml)
METRICS = {
    "category": "DSE market category (A/B/G/N/Z)",
    "market_cap_mn": "Market cap, BDT million",
    "dividend_streak": "Consecutive years with any dividend, up to the latest year",
    "cash_dividend_years_5": "Years with a cash dividend in the last 5",
    "eps_positive_years_5": "Years with positive EPS in the last 5",
    "eps_cagr_3y": "EPS growth per year over 3 years, % (restated EPS)",
    "pe": "Trailing P/E",
    "p_nav": "Price / NAV per share",
    "dividend_yield": "Latest dividend yield, %",
    "sponsor_pct": "Sponsor/director holding, %",
    "strategic_pct": "Sponsor/director + government holding, %",
    "institute_change_pp": "Change in institutional holding over stored snapshots, % points",
    "avg_value_mn_60": "Liquidity: average daily traded value over the last 60 trading days, BDT million",
    "traded_days_pct_60": "Share of the last 60 trading days with any trade, %",
}

LIQUIDITY_DAYS = 60


def compute_quality_metrics(db: Database, codes: list[str]) -> pd.DataFrame:
    companies = db.load_companies(codes).set_index("code")
    divs = db.load_table("dividend_history", codes)
    annual = db.load_table("annual_financials", codes)
    holding = db.load_table("shareholding", codes)
    prices = db.load_prices(codes)
    last_close = prices.sort_values("date").groupby("code")["close"].last()
    recent_days = sorted(prices["date"].unique())[-LIQUIDITY_DAYS:]
    recent = prices[prices["date"].isin(recent_days)]
    avg_value = recent.groupby("code")["value_mn"].sum() / len(recent_days)    # no-trade days count as 0
    traded_pct = recent.assign(t=recent["volume"].fillna(0) > 0).groupby("code")["t"].sum() / len(recent_days) * 100

    rows = []
    for code in codes:
        c = companies.loc[code] if code in companies.index else pd.Series(dtype=object)
        d = divs[divs["code"] == code].sort_values("year")
        a = annual[annual["code"] == code].sort_values("year")
        h = holding[holding["code"] == code].sort_values("as_of")

        # The page lists only years with a dividend, so a missing year = no dividend.
        # Count back from the latest reported financial year.
        paid_years = set(d.loc[(d["cash_pct"] + d["stock_pct"]) > 0, "year"].astype(int))
        cash_years = set(d.loc[d["cash_pct"] > 0, "year"].astype(int))
        known = list(d["year"].astype(int)) + list(a["year"].astype(int))
        latest_fy = max(known) if known else None
        streak = 0
        if latest_fy is not None:
            while latest_fy - streak in paid_years:
                streak += 1

        last5 = a.tail(5)
        eps = a["eps"].dropna()
        cagr = None
        if len(eps) >= 4 and eps.iloc[-4] > 0 and eps.iloc[-1] > 0:
            cagr = ((eps.iloc[-1] / eps.iloc[-4]) ** (1 / 3) - 1) * 100
        nav = a["nav"].dropna()
        price = last_close.get(code)

        rows.append(
            {
                "code": code,
                "sector": c.get("sector"),
                "category": c.get("category"),
                "market_cap_mn": c.get("market_cap_mn"),
                "dividend_streak": streak if latest_fy is not None else None,
                "cash_dividend_years_5": (
                    sum(latest_fy - k in cash_years for k in range(5)) if latest_fy is not None else None
                ),
                "eps_positive_years_5": int((last5["eps"] > 0).sum()) if len(last5) else None,
                "eps_cagr_3y": cagr,
                "pe": c.get("trailing_pe"),
                "p_nav": price / nav.iloc[-1] if price and len(nav) and nav.iloc[-1] > 0 else None,
                "dividend_yield": a["dividend_yield"].dropna().iloc[-1] if a["dividend_yield"].notna().any() else None,
                "sponsor_pct": h["sponsor"].iloc[-1] if len(h) else None,
                # State-owned companies (BSC, oil companies) show 0% sponsor but ~50%+ govt
                "strategic_pct": h["sponsor"].iloc[-1] + h["govt"].iloc[-1] if len(h) else None,
                "institute_change_pp": h["institute"].iloc[-1] - h["institute"].iloc[0] if len(h) > 1 else None,
                "avg_value_mn_60": avg_value.get(code),
                "traded_days_pct_60": traded_pct.get(code),
            }
        )
    columns = ["code", "sector", "category", *METRICS]
    # An empty universe (e.g. fresh install before `discover`) must give an empty table, not crash
    return pd.DataFrame(rows, columns=list(dict.fromkeys(columns))).set_index("code")
