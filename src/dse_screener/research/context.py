"""StockEYE's own data, packed for the AI analyst: market, today's shortlist, facts per mentioned stock."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import engine, indicators, quality, report, rules
from ..config import Settings, list_profiles, load_profile
from ..db import Database
from . import ledger


def _r(v, digits: int = 1):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v) else round(float(v), digits)


def latest_screen(db: Database, as_of: str) -> tuple[dict, dict[str, list[str]]]:
    """Shortlist per profile on as_of (with reasons) and every active signal per code."""
    runs = db.load_runs()
    runs = runs[runs["as_of"] == as_of]
    if runs.empty:
        return {}, {}
    ids = runs["run_id"].astype(int).tolist()
    picks, sigs = db.load_run_picks(ids), db.load_run_signals(ids)
    profile_of = dict(zip(runs["run_id"], runs["profile"]))
    screen = {}
    for run_id, g in picks.groupby("run_id"):
        screen[profile_of[run_id]] = [
            {"rank": int(p.rank), "code": p.code, "score": _r(p.final_score, 0), "strategies": p.strategies,
             "reasons": [r for r in p.reasons if not r.startswith("Tech:")][:4]}
            for p in g.itertuples()]
    active: dict[str, list[str]] = {}
    for s in sigs.itertuples():
        active.setdefault(s.code, []).append(f"{profile_of[s.run_id]}: {s.strategy} (score {s.score:.0f})")
    return screen, active


def stock_facts(db: Database, settings: Settings, codes: list[str], as_of: str,
                active: dict[str, list[str]] | None = None) -> list[dict]:
    if not codes:
        return []
    day = pd.Timestamp(as_of)
    prices = engine.load_adjusted_prices(db, settings, codes)
    prices = prices[prices["date"] <= day]
    companies = db.load_companies(codes).set_index("code")
    metrics = quality.compute_quality_metrics(db, codes)
    passes = {}
    for name in list_profiles(settings):
        qf = load_profile(name).filters.get("quality")
        res = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
        passes[name] = res
    actions = db.load_corporate_actions(codes)
    upcoming = actions[(pd.to_datetime(actions["record_date"]) >= day - timedelta(days=5))
                       & (pd.to_datetime(actions["record_date"]) <= day + timedelta(days=45))]

    out = []
    by_code = {c: g.sort_values("date").reset_index(drop=True) for c, g in prices.groupby("code")}
    for code in codes:
        c = companies.loc[code] if code in companies.index else pd.Series(dtype=object)
        m = metrics.loc[code] if code in metrics.index else pd.Series(dtype=object)
        row = {
            "code": code, "name": c.get("name"), "sector": c.get("sector"), "category": c.get("category"),
            "quality": {name: ("pass" if res.loc[code, "passed"] else "fail: " + "; ".join(res.loc[code, "failures"]))
                        for name, res in passes.items() if code in res.index},
            "pe": _r(m.get("pe")), "dividend_yield_pct": _r(m.get("dividend_yield")),
            "dividend_streak_years": _r(m.get("dividend_streak"), 0), "eps_growth_3y_pct": _r(m.get("eps_cagr_3y")),
            "sponsor_govt_pct": _r(m.get("strategic_pct")), "institution_change_pp": _r(m.get("institute_change_pp")),
            "market_cap_bdt_mn": _r(c.get("market_cap_mn"), 0),
        }
        g = by_code.get(code)
        if g is not None and len(g):
            close, vol = g["close"], g["volume"].fillna(0).astype(float)
            last = close.iloc[-1]
            chg = lambda n: _r((last / close.iloc[-1 - n] - 1) * 100) if len(close) > n else None  # noqa: E731
            hi, lo = close.tail(250).max(), close.tail(250).min()
            base = vol.iloc[-70:-10].mean() if len(vol) > 20 else np.nan
            row.update({
                "last_date": g["date"].iloc[-1].strftime("%Y-%m-%d"), "close": _r(last, 2),
                "change_pct": {"1d": chg(1), "5d": chg(5), "20d": chg(20), "60d": chg(60)},
                "from_52w_high_pct": _r((last / hi - 1) * 100), "above_52w_low_pct": _r((last / lo - 1) * 100),
                "volume_10d_vs_prior_60d": _r(vol.tail(10).mean() / base, 2) if base and base > 0 else None,
                "avg_value_bdt_mn_20d": _r(g["value_mn"].tail(20).mean(), 1),
                "rsi14": _r(indicators.rsi(close).iloc[-1], 0),
            })
        row["stockeye_signals_today"] = (active or {}).get(code, [])
        rec = upcoming[upcoming["code"] == code]
        row["record_dates"] = [f"{pd.Timestamp(r.record_date):%Y-%m-%d} (cash {r.cash_pct:g}%, stock {r.stock_pct:g}%)"
                               for r in rec.itertuples()]
        out.append(row)
    return out


def build_context(db: Database, settings: Settings, doc_codes: list[str], table_codes: list[str] | None = None) -> dict:
    """Everything the analyst gets from StockEYE, as plain JSON-able data.

    doc_codes: stocks the documents write about (news, company research): always included.
    table_codes: stocks that only appear in data tables (market review lists): added largest first,
    up to research.max_context_stocks in total. Today's shortlist picks are always included."""
    as_of = db.date_range()[1]
    screen, active = latest_screen(db, as_of)
    pick_codes = [p["code"] for picks in screen.values() for p in picks]
    limit = settings.research.max_context_stocks
    mentioned = list(dict.fromkeys(doc_codes))
    rest = [c for c in dict.fromkeys(table_codes or []) if c not in set(mentioned)]
    room = max(limit - len(mentioned), 0)
    if len(rest) > room:
        comp = db.load_companies(rest).set_index("code")["market_cap_mn"]
        rest = sorted(rest, key=lambda c: -(comp.get(c) or 0))[:room]
    all_mentioned = set(doc_codes) | set(table_codes or [])
    mentioned = mentioned + rest
    codes = list(dict.fromkeys(mentioned + pick_codes))
    return {
        "as_of": as_of,
        "note": "StockEYE data up to as_of (latest stored trading day). Prices adjusted for dividends and bonus shares.",
        "market": {k: _r(v, 1) for k, v in report.market_summary(db, date.fromisoformat(as_of)).items()},
        "screen": screen,
        "stocks": stock_facts(db, settings, codes, as_of, active),
        "stocks_omitted": len(all_mentioned - set(mentioned)),
        "track_record": ledger.track_record(db),
    }


def code_directory(db: Database) -> str:
    """'CODE: Company name (sector, category)' for every listed equity: lets the analyst map names to codes."""
    c = db.load_companies()
    c = c[c["instrument_type"] == "Equity"].sort_values("code")
    return "\n".join(f"{r.code}: {r.name} ({r.sector or '?'}, {r.category or '?'})" for r in c.itertuples())
