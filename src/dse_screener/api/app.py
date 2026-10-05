"""FastAPI app serving the stored data, screens, charts and backtests as JSON.

Read-mostly: the writes are POST /api/screens/run, the research uploads and saving trade-lab plans.
Bound to localhost by the CLI.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import date

import pandas as pd
import yaml
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ValidationError

from .. import backtest, casestudy, engine, features, indicators, quality, report, rules, simulate
from ..config import (CONFIG_DIR, OPERATORS, TradePlan, list_plans, list_profiles, load_plan, load_profile,
                      load_settings, plan_path, plan_to_yaml_data)
from ..universes import universe_codes as resolve_universe
from ..db import Database
from ..strategies import REGISTRY

settings = load_settings()
app = FastAPI(title="StockEYE API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


def get_db() -> Iterator[Database]:
    db = Database(settings.resolve(settings.paths.db), check_same_thread=False)
    try:
        yield db
    finally:
        db.close()


# --- helpers -----------------------------------------------------------------

def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records; dates as YYYY-MM-DD, NaN as null."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records"))


_cache: dict[tuple, tuple[float, object]] = {}


def cached(key: tuple, ttl: float, fn):
    """Tiny in-process cache: adjusted prices and metrics are expensive to rebuild per request."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


def _data_version(db: Database) -> tuple:
    last_price = db.date_range()[1]
    last_run = db.conn.execute("SELECT MAX(run_id) FROM screen_runs").fetchone()[0]
    return last_price, last_run


def universe_codes(db: Database) -> list[str]:
    """Union of every profile's universe (resolved from stored company pages for query universes)."""
    return cached(("universe", _data_version(db)), 600, lambda: sorted(
        {c for n in list_profiles(settings) for c in resolve_universe(load_profile(n).universe, db)}))


def adjusted_prices(db: Database) -> pd.DataFrame:
    return cached(("prices", _data_version(db)), 600,
                  lambda: engine.load_adjusted_prices(db, settings, universe_codes(db)))


def quality_metrics(db: Database) -> pd.DataFrame:
    return cached(("metrics", _data_version(db)), 600,
                  lambda: quality.compute_quality_metrics(db, universe_codes(db)))


def _profile(name: str):
    if name not in list_profiles(settings):
        raise HTTPException(404, f"Unknown profile '{name}'")
    return load_profile(name)


# --- meta & screens ----------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta(db: Database = Depends(get_db)):
    first, last = db.date_range()
    return {
        "prices_from": first, "prices_to": last,
        "profiles": [{"name": n, "description": load_profile(n).description} for n in list_profiles(settings)],
        "strategies": {name: cls.title for name, cls in REGISTRY.items()},
        "universe": universe_codes(db),
        "disclaimer": report.DISCLAIMER,
    }


@app.get("/api/runs")
def runs(db: Database = Depends(get_db)):
    return records(db.load_runs().drop(columns=["config_json"]))


def _screen_payload(db: Database, as_of: str) -> dict:
    all_runs = db.load_runs()
    day = all_runs[all_runs["as_of"] == as_of]
    if day.empty:
        raise HTTPException(404, f"No saved screen for {as_of}")
    picks = db.load_run_picks(day["run_id"].astype(int).tolist())
    sigs = db.load_run_signals(day["run_id"].astype(int).tolist())
    watch = db.load_run_watch(day["run_id"].astype(int).tolist())
    codes = sorted(set(picks["code"]))
    news = report.recent_news(db, codes, date.fromisoformat(as_of), settings.report)
    order = {n: i for i, n in enumerate(list_profiles(settings))}
    profiles = []
    for run in sorted(day.itertuples(), key=lambda r: order.get(r.profile, 99)):
        p_picks = picks[picks["run_id"] == run.run_id]
        p_sigs = sigs[sigs["run_id"] == run.run_id].sort_values("weighted", ascending=False)
        shortlist = set(p_picks["code"])
        profiles.append({
            "profile": run.profile,
            "description": load_profile(run.profile).description if run.profile in order else "",
            "run_id": int(run.run_id), "run_at": run.run_at,
            "universe_size": int(run.universe_size), "passed_quality": int(run.passed_quality),
            "signals": int((sigs["run_id"] == run.run_id).sum()),
            "picks": [{**r, "news": news.get(r["code"], [])}
                      for r in records(p_picks.drop(columns=["run_id"]))],
            # Every strategy hit, including those below the shortlist cut
            "all_signals": [{"code": s.code, "strategy": s.strategy, "title": _title(s.strategy), "role": s.role,
                             "score": s.score, "weighted": s.weighted, "reasons": s.reasons,
                             "on_shortlist": s.code in shortlist} for s in p_sigs.itertuples()],
            # Setups still forming (not a signal yet), closest to triggering first
            "watch": [{"code": w.code, "strategy": w.strategy, "title": _title(w.strategy), "reasons": w.reasons,
                       "metrics": w.metrics} for w in watch[watch["run_id"] == run.run_id].itertuples()],
        })
    return {"as_of": as_of, "market": report.market_summary(db, date.fromisoformat(as_of)), "profiles": profiles}


def _title(strategy: str) -> str:
    return REGISTRY[strategy].title if strategy in REGISTRY else strategy


@app.get("/api/screens/latest")
def latest_screen(db: Database = Depends(get_db)):
    all_runs = db.load_runs()
    if all_runs.empty:
        raise HTTPException(404, "No saved screens yet")
    return _screen_payload(db, all_runs["as_of"].max())


@app.get("/api/screens/{as_of}")
def screen(as_of: str, db: Database = Depends(get_db)):
    return _screen_payload(db, as_of)


@app.post("/api/screens/run")
def run_screen(db: Database = Depends(get_db)):
    """Screen every profile on the latest stored day and save the results."""
    for name in list_profiles(settings):
        p = load_profile(name)
        db.save_screen(engine.run_profile(db, settings, p), p.model_dump_json(by_alias=True))
    return latest_screen(db)


@app.get("/api/history")
def history(db: Database = Depends(get_db)):
    all_runs = db.load_runs()
    picks = db.load_run_picks(all_runs["run_id"].astype(int).tolist())
    merged = picks.merge(all_runs[["run_id", "as_of", "profile"]], on="run_id")
    return records(merged[["as_of", "profile", "rank", "code", "final_score", "strategies"]]
                   .sort_values(["as_of", "profile", "rank"], ascending=[False, True, True]))


# --- stocks -------------------------------------------------------------------

@app.get("/api/stocks")
def stocks(db: Database = Depends(get_db)):
    codes = universe_codes(db)
    comp = db.load_companies(codes)[["code", "name", "sector", "category", "market_cap_mn"]]
    m = quality_metrics(db).drop(columns=["sector", "category", "market_cap_mn"], errors="ignore").reset_index()
    p = adjusted_prices(db)
    last = p.sort_values("date").groupby("code").tail(1)[["code", "date", "close", "ycp", "volume"]]
    last["change_pct"] = (last["close"] / last["ycp"] - 1) * 100
    df = comp.merge(m, on="code", how="left").merge(last.drop(columns="ycp"), on="code", how="left")
    for name in list_profiles(settings):
        qf = load_profile(name).filters.get("quality")
        res = rules.evaluate(quality_metrics(db), qf.rules if qf and qf.enabled else {})
        df[f"pass_{name}"] = df["code"].map(res["passed"])
    return records(df.sort_values("market_cap_mn", ascending=False))


@app.get("/api/stocks/{code}")
def stock(code: str, db: Database = Depends(get_db)):
    if code not in universe_codes(db):
        raise HTTPException(404, f"{code} is not in the universe")
    comp = db.load_companies([code])
    m = quality_metrics(db)
    news = db.load_news([code])
    news = news[~news["body"].str.lstrip().str.startswith("(Cont")].sort_values("post_date", ascending=False)
    acts = db.load_corporate_actions([code])
    return {
        "company": records(comp)[0] if len(comp) else {"code": code},
        "metrics": records(m.loc[[code]].reset_index())[0] if code in m.index else {},
        "shareholding": records(db.load_table("shareholding", [code]).sort_values("as_of", ascending=False)),
        "annual": records(db.load_table("annual_financials", [code]).sort_values("year", ascending=False)),
        "dividends": records(db.load_table("dividend_history", [code]).sort_values("year", ascending=False)),
        "corporate_actions": records(acts.sort_values("record_date", ascending=False)),
        "news": records(news.head(60)),
    }


@app.get("/api/stocks/{code}/chart")
def chart(code: str, profile: str = "swing", days: int = Query(250, ge=20, le=5000),
          db: Database = Depends(get_db)):
    """Adjusted daily bars + volume, RSI(14), MACD(12,26,9), 20-day avg volume, strategy markers, ex-dates."""
    prof = _profile(profile)
    p = adjusted_prices(db)
    g = p[p["code"] == code].sort_values("date").reset_index(drop=True)
    if g.empty:
        raise HTTPException(404, f"No prices for {code}")
    markers = []
    for strat, _cfg in engine.build_strategies(prof):
        if len(g) < strat.min_history:
            continue
        out = strat.compute(g)
        sig = out["signal"].astype(bool) & (out.index >= strat.min_history) & (g["volume"].fillna(0) > 0)
        starts = sig & ~sig.shift(1, fill_value=False)
        for i in out.index[starts]:
            markers.append({"time": g.at[i, "date"].strftime("%Y-%m-%d"), "strategy": strat.name,
                            "title": strat.title, "score": round(float(out.at[i, "score"]), 1)})

    return _chart_payload(db, code, profile, g, markers, max(len(g) - days, 0))


def _chart_payload(db: Database, code: str, profile: str, g: pd.DataFrame, markers: list[dict], start: int,
                   end: int | None = None) -> dict:
    """Bars, indicators (computed on full history, then sliced to rows start..end), markers, ex-dates."""
    close = g["close"]
    ind = pd.DataFrame({"date": g["date"], "rsi": indicators.rsi(close),
                        "vol_avg": indicators.sma(g["volume"].astype(float), 20)}).join(indicators.macd(close))
    g, ind = g.iloc[start:end], ind.iloc[start:end]
    first_day, last_day = g["date"].iloc[0], g["date"].iloc[-1]
    bars = g[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ("open", "high", "low"):          # no-trade days: flat bar at the carried close
        bars[col] = bars[col].fillna(bars["close"])
    acts = db.load_corporate_actions([code])
    ex = [d.strftime("%Y-%m-%d") for d in acts["ex_date"].dropna() if first_day <= d <= last_day]
    lo, hi = first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")
    return {
        "code": code, "profile": profile,
        "bars": records(bars.rename(columns={"date": "time"})),
        "indicators": records(ind.rename(columns={"date": "time"})),
        "markers": [mk for mk in markers if lo <= mk["time"] <= hi],
        "ex_dates": ex,
    }


# --- quality, profiles, backtest ---------------------------------------------

@app.get("/api/quality/{profile}")
def quality_view(profile: str, db: Database = Depends(get_db)):
    prof = _profile(profile)
    m = quality_metrics(db)
    qf = prof.filters.get("quality")
    res = rules.evaluate(m, qf.rules if qf and qf.enabled else {})
    df = m.join(res).reset_index()
    rules_cfg = {k: v.model_dump(by_alias=True, exclude_none=True) for k, v in (qf.rules if qf else {}).items()}
    return {"profile": profile, "rules": rules_cfg, "metrics": quality.METRICS,
            "rows": records(df.sort_values(["passed", "market_cap_mn"], ascending=[False, False]))}


@app.get("/api/profiles")
def profiles():
    out = []
    for name in list_profiles(settings):
        path = CONFIG_DIR / "profiles" / f"{name}.yaml"
        out.append({"name": name, "path": f"config/profiles/{name}.yaml", "yaml": path.read_text(encoding="utf-8")})
    out.append({"name": "settings", "path": "config/settings.yaml",
                "yaml": (CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")})
    return out


def _backtest_result(name: str, db: Database) -> backtest.BacktestResult:
    """Cached until the data or the profile file changes."""
    prof = _profile(name)
    mtime = (CONFIG_DIR / "profiles" / f"{name}.yaml").stat().st_mtime

    def run():
        codes = resolve_universe(prof.universe, db)
        return backtest.run_backtest(prof, adjusted_prices(db), quality_metrics(db), db.load_corporate_actions(codes))

    return cached(("backtest", name, mtime, _data_version(db)), 3600, run)


@app.get("/api/backtest/{profile}")
def backtest_view(profile: str, db: Database = Depends(get_db)):
    """Summary per holding period and exit style, recall on big winners, recent trades."""
    prof = _profile(profile)
    res = _backtest_result(profile, db)
    w = res.winners_cfg
    trades = res.trades.drop(columns=["i"]).sort_values("date", ascending=False)
    return {
        "profile": profile, "start": res.start.strftime("%Y-%m-%d"), "end": res.end.strftime("%Y-%m-%d"),
        "in_sample_until": res.in_sample_until.strftime("%Y-%m-%d") if res.in_sample_until is not None else None,
        "cost_pct": prof.backtest.cost_pct, "primary_horizon": res.primary, "horizons": res.horizons,
        "exits": [{"name": n, "label": backtest.exit_label(n, r), "open": int((res.trades[f"why_{n}"] == "open").sum())}
                  for n, r in res.exits.items()],
        "universe_size": len(res.universe),
        "summary": {str(k): records(backtest.summarize(res, k).reset_index()) for k in res.keys},
        "recall": records(backtest.recall(res).reset_index()),
        "winners": w.model_dump(),
        "trades": records(trades),
    }


@app.get("/api/casestudy/{code}")
def casestudy_view(code: str, profile: str = "swing", start: date | None = None, end: date | None = None,
                   shortlist: bool = False, db: Database = Depends(get_db)):
    """Every signal of one profile on any stock over a period, with outcomes, big moves and a chart.

    shortlist=true also runs (or reuses) the profile's backtest to show the stock's rank among all stocks.
    """
    prof = _profile(profile)
    code = code.upper()
    g = engine.load_adjusted_prices(db, settings, [code]).sort_values("date").reset_index(drop=True)
    if g.empty:
        raise HTTPException(404, f"No prices for {code}")
    last = g["date"].iloc[-1]
    start_ts = pd.Timestamp(start) if start else last - pd.DateOffset(years=1)
    m = quality_metrics(db)
    metrics = m.loc[[code]] if code in m.index else quality.compute_quality_metrics(db, [code])
    picks = _backtest_result(profile, db).picks if shortlist else None
    try:
        cs = casestudy.run_casestudy(prof, g, metrics, db.load_corporate_actions([code]), start_ts, end, picks)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    sig = cs.signals
    markers = [{"time": r.date.strftime("%Y-%m-%d"), "strategy": r.strategy, "title": r.title,
                "score": round(r.score, 1)} for r in sig.itertuples() if r.status == "signal"] if len(sig) else []
    # Chart: the window plus 60 trading days before it, so the base before the first signal is visible
    rows = g.index[(g["date"] >= cs.start) & (g["date"] <= cs.end)]
    chart_data = _chart_payload(db, code, profile, g, markers, max(int(rows[0]) - 60, 0), int(rows[-1]) + 1)
    comp = db.load_companies([code])
    w = cs.window
    return {
        "code": code, "profile": profile, "name": comp["name"].iloc[0] if len(comp) else None,
        "start": cs.start.strftime("%Y-%m-%d"), "end": cs.end.strftime("%Y-%m-%d"),
        "last_date": cs.last_date.strftime("%Y-%m-%d"), "last_close": cs.last_close,
        "window": {**w, "low_date": w["low_date"].strftime("%Y-%m-%d"), "high_date": w["high_date"].strftime("%Y-%m-%d")},
        "quality_passed": cs.quality_passed, "quality_failures": cs.quality_failures,
        "horizons": cs.horizons, "primary_horizon": cs.primary, "cost_pct": cs.cost_pct, "min_score": cs.min_score,
        "exits": [{"name": n, "label": backtest.exit_label(n, prof.backtest.exits[n])} for n in cs.exits],
        "shortlist": shortlist,
        "signals": records(sig) if len(sig) else [],
        "moves": records(cs.moves),
        "chart": chart_data,
    }


# --- trade lab (docs/06-trade-lab-plan.md) -------------------------------------

def _plan_json(plan: TradePlan) -> dict:
    return plan.model_dump(mode="json", by_alias=True)


def _validate_plan(data: dict) -> TradePlan:
    try:
        return TradePlan.model_validate(data)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            where = ".".join(str(x) for x in err["loc"])
            msgs.append(f"{where}: {err['msg'].removeprefix('Value error, ')}" if where else err["msg"])
        raise HTTPException(400, "; ".join(msgs)) from e


@app.get("/api/lab")
def lab_meta(db: Database = Depends(get_db)):
    """Saved plans, condition columns, strategies and profiles for the trade lab form."""
    plans = []
    for name in list_plans():
        try:
            plan = load_plan(name)
        except (ValueError, OSError) as e:
            plans.append({"name": name, "error": str(e)})
            continue
        plans.append({"name": name, "description": plan.description, "plan": _plan_json(plan),
                      "describe": simulate.describe(plan)})
    first, last = db.date_range()
    return {
        "plans": plans, "columns": features.catalog(), "operators": list(OPERATORS),
        "strategies": [{"name": n, "title": cls.title} for n, cls in REGISTRY.items()],
        "profiles": list_profiles(settings), "first_date": first, "last_date": last,
        "universes": sorted(f.stem for f in (CONFIG_DIR / "universes").glob("*.yaml")),
        "default_plan": _plan_json(TradePlan.model_validate({"entry": {"when": ["close > sma_50"]}})),
    }


class SimulateBody(BaseModel):
    plan: dict
    basket_profile: str | None = "swing"   # compare with that profile's quality-passing stocks; None = off
    chart_code: str | None = None          # which stock's chart to return (default: the one with the most trades)


class SweepBody(BaseModel):
    plan: dict
    grid: dict[str, list]                   # plan path -> values, e.g. {"exit.stop_pct": [5, 8, 10]}
    basket_profile: str | None = "swing"


MAX_LAB_STOCKS = 400
MAX_WEB_COMBOS = 36


def _lab_inputs(plan: TradePlan, db: Database) -> tuple[list[str], pd.DataFrame]:
    """The plan's stocks (codes + universe, quality-filtered) and their adjusted prices."""
    if not (plan.codes or plan.universe):
        raise HTTPException(400, "Pick at least one stock or a universe")
    try:
        codes = simulate.plan_codes(plan, db, quality_metrics(db) if plan.quality else None)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    if not codes:
        raise HTTPException(400, "No stocks left after the universe / quality filter")
    if len(codes) > MAX_LAB_STOCKS:
        raise HTTPException(400, f"{len(codes)} stocks; at most {MAX_LAB_STOCKS} per run")
    known = set(universe_codes(db))
    if all(c in known for c in codes):          # the cached all-stock prices cover them
        p = adjusted_prices(db)
        return codes, p[p["code"].isin(codes)]
    return codes, engine.load_adjusted_prices(db, settings, codes)


def _basket(profile: str | None, db: Database) -> simulate.Basket | None:
    if not profile:
        return None
    codes = _basket_codes(profile, db)
    return cached(("basket", profile, _data_version(db)), 600,
                  lambda: simulate.Basket(adjusted_prices(db), codes, f"{len(codes)} {profile} quality stocks"))


def _basket_codes(profile: str, db: Database) -> list[str]:
    prof = _profile(profile)
    return simulate.quality_codes(prof, quality_metrics(db), resolve_universe(prof.universe, db))


@app.post("/api/simulate")
def simulate_view(body: SimulateBody, db: Database = Depends(get_db)):
    """Run a trade plan: trades, stats, per-stock results, basket comparison, equity curves, one chart."""
    plan = _validate_plan(body.plan)
    codes, prices = _lab_inputs(plan, db)
    try:
        res = simulate.run_plan(plan, prices, codes=codes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    basket = _basket(body.basket_profile, db) if not res.stocks.empty else None
    if basket is not None:
        basket.apply(res)

    summary = simulate.summarize(res).reset_index() if not res.trades.empty else pd.DataFrame()
    stocks = res.stocks.reset_index() if not res.stocks.empty else pd.DataFrame()
    if len(stocks):
        stocks = stocks.sort_values(["trades", "pnl"], ascending=False)

    wanted = (body.chart_code or "").upper()
    chart_code = wanted if wanted in set(stocks["code"]) else (stocks["code"].iloc[0] if len(stocks) else None)
    # Equity: the portfolio vs the same money split over its stocks and held; or the chart stock vs holding it
    equity = {}
    if res.portfolio is not None:
        e = res.equity
        equity["portfolio"] = [{"time": d.strftime("%Y-%m-%d"), "plan": round(float(v), 2), "hold": round(float(h), 2)}
                               for d, v, h in zip(e["date"], e["equity"], e["bench"])]
    elif chart_code:
        e = res.equity[res.equity["code"] == chart_code]
        g = prices[(prices["code"] == chart_code) & prices["date"].isin(e["date"])].sort_values("date")
        first = g["open"].iloc[0] if pd.notna(g["open"].iloc[0]) else g["close"].iloc[0]
        hold = plan.capital.start * g["close"].to_numpy(float) / first
        equity[chart_code] = [{"time": d.strftime("%Y-%m-%d"), "plan": round(float(v), 2), "hold": round(float(h), 2)}
                              for d, v, h in zip(e["date"], e["equity"], hold)]
    chart = _lab_chart(db, plan, prices, res, chart_code) if chart_code else None
    return {
        "plan": _plan_json(plan), "describe": simulate.describe(plan), "codes": codes,
        "trades": records(res.trades), "summary": records(summary), "stocks": records(stocks),
        "warnings": res.warnings, "pending": res.pending, "basket": res.basket, "portfolio": res.portfolio,
        "equity": equity, "chart_code": chart_code, "chart": chart,
    }


@app.post("/api/sweep")
def sweep_view(body: SweepBody, db: Database = Depends(get_db)):
    """Run the plan once per combination of grid values: one row per combination (see simulate.sweep)."""
    plan = _validate_plan(body.plan)
    grid = {k.strip(): v for k, v in body.grid.items() if k.strip() and v}
    if not grid:
        raise HTTPException(400, "Give at least one grid path with values")
    n = 1
    for v in grid.values():
        n *= len(v)
    if n > MAX_WEB_COMBOS:
        raise HTTPException(400, f"{n} combinations; at most {MAX_WEB_COMBOS} here (the CLI allows {simulate.MAX_COMBOS})")
    codes, prices = _lab_inputs(plan, db)
    try:
        table = simulate.sweep(plan, grid, prices, _basket(body.basket_profile, db), codes=codes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"plan": _plan_json(plan), "describe": simulate.describe(plan), "grid": grid, "stocks": len(codes),
            "split": plan.in_sample_until is not None, "rows": records(table)}


def _lab_chart(db: Database, plan: TradePlan, prices: pd.DataFrame, res: simulate.LabResult, code: str) -> dict:
    """The stock's chart over the window (plus 60 days before), buy/sell markers, price-unit columns the plan uses."""
    g = prices[prices["code"] == code].sort_values("date").reset_index(drop=True)
    st = res.stocks.loc[code]
    rows = g.index[(g["date"] >= st["start"]) & (g["date"] <= st["end"])]
    start, end = max(int(rows[0]) - 60, 0), int(rows[-1]) + 1
    payload = _chart_payload(db, code, "lab", g, [], start, end)
    t = res.trades[res.trades["code"] == code]
    marks = []
    for r in t.itertuples():
        marks.append({"time": r.entry_date.strftime("%Y-%m-%d"), "side": "buy", "price": round(r.entry, 2),
                      "text": f"Buy {r.entry:.1f}"})
        if r.why != "open":
            marks.append({"time": r.exit_date.strftime("%Y-%m-%d"), "side": "sell", "price": round(r.exit, 2),
                          "ret": round(r.ret_pct, 2), "text": f"Sell {r.exit:.1f} ({r.why}) {r.ret_pct:+.1f}%"})
    payload["trades"] = marks
    names = [n for cd in [*plan.entry.when, *plan.exit.when_any] for n in (cd[0], cd[2])
             if isinstance(n, str) and features.PRICE_UNITS.match(n) and n not in features.PRICE]
    if plan.exit.trail_ma:
        names.append(f"sma_{plan.exit.trail_ma}")
    cols = features.Columns(g)
    overlays = []
    for name in dict.fromkeys(names):
        if len(overlays) == 3:
            break
        v = cols[name].iloc[start:end]
        overlays.append({"name": name, "points": [{"time": d.strftime("%Y-%m-%d"), "value": round(float(x), 3)}
                                                  for d, x in zip(g["date"].iloc[start:end], v) if pd.notna(x)]})
    payload["overlays"] = overlays
    return payload


class SavePlanBody(BaseModel):
    name: str
    plan: dict
    overwrite: bool = False


@app.post("/api/plans")
def save_plan(body: SavePlanBody):
    """Save a plan as config/plans/<name>.yaml (lowercase letters, digits, - and _)."""
    name = body.name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        raise HTTPException(400, "Plan name: lowercase letters, digits, - and _ (up to 41 characters), e.g. ma-pullback")
    plan = _validate_plan({**body.plan, "name": name})
    path = plan_path(name)
    if path.exists() and not body.overwrite:
        raise HTTPException(409, f"A plan called '{name}' already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(plan_to_yaml_data(plan), sort_keys=False, allow_unicode=True)
    path.write_text("# Trade lab plan (docs/06-trade-lab-plan.md), saved from the dashboard.\n" + text, encoding="utf-8")
    return {"name": name, "path": f"config/plans/{name}.yaml"}


@app.get("/api/config/raw")
def config_raw():
    """Parsed profiles (for future editing UI)."""
    return {n: yaml.safe_load((CONFIG_DIR / "profiles" / f"{n}.yaml").read_text(encoding="utf-8"))
            for n in list_profiles(settings)}


# --- research & AI review -----------------------------------------------------

class AddDocBody(BaseModel):
    url: str
    doc_type: str | None = None


class ReviewBody(BaseModel):
    doc_ids: list[int] | None = None


_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _has_api_key() -> bool:
    from ..research.review import has_credentials

    return has_credentials(settings)


@app.get("/api/research")
def research_overview(db: Database = Depends(get_db)):
    from ..research import documents, ledger, review

    docs = documents.load_docs(db).head(100)
    reviews = review.load_reviews(db).head(50)
    rows = [{"id": int(r.id), "created_at": r.created_at, "as_of": r.as_of, "model": r.model, "doc_ids": r.doc_ids,
             "headline": r.review.get("headline"), "calls": len(r.review.get("calls", []))} for r in reviews.itertuples()]
    with _jobs_lock:
        running = [dict(id=k, **v) for k, v in _jobs.items() if v["status"] == "running"]
    return {
        "has_api_key": _has_api_key(), "model": settings.research.model,
        "guide": str(settings.research.guide).replace("\\", "/"), "sources": str(settings.research.sources).replace("\\", "/"),
        "inbox": str(settings.research.inbox).replace("\\", "/"),
        "docs": records(docs.drop(columns=["file_path"])),
        "reviews": rows,
        "track_record": ledger.track_record(db),
        "calibration": records(ledger.calibration_table(db)),
        "running": running,
    }


@app.get("/api/research/reviews/{review_id}")
def research_review(review_id: int, db: Database = Depends(get_db)):
    from ..research import documents, ledger, review

    reviews = review.load_reviews(db)
    row = reviews[reviews["id"] == review_id]
    if row.empty:
        raise HTTPException(404, f"No review #{review_id}")
    r = row.iloc[0]
    calls = ledger.load_calls(db)
    calls = calls[calls["review_id"] == review_id]
    docs = documents.load_docs(db, r["doc_ids"])
    return {"id": review_id, "created_at": r["created_at"], "as_of": r["as_of"], "model": r["model"],
            "usage": r["usage"], "review": r["review"],
            "docs": records(docs[["id", "source", "filename", "doc_type", "published", "url"]]),
            "scores": records(calls[["code", "stance", "horizon_days", "confidence", "ret", "bench", "excess", "correct"]])}


@app.post("/api/research/docs")
def research_add(body: AddDocBody, db: Database = Depends(get_db)):
    from ..research import documents

    try:
        res = documents.add_url(db, settings, body.url.strip(), body.doc_type or None)
    except (ValueError, OSError) as e:      # bad link, not a PDF, too big, network error
        raise HTTPException(400, str(e)) from e
    return res.__dict__


@app.post("/api/research/inbox")
def research_inbox(db: Database = Depends(get_db)):
    from ..research import documents

    return [r.__dict__ for r in documents.scan_inbox(db, settings)]


@app.post("/api/research/review")
def research_run(body: ReviewBody):
    """Start an AI review in the background (it takes 1-3 minutes); poll /api/research/jobs/{id}."""
    if not _has_api_key():
        raise HTTPException(400, "No Anthropic API key: add anthropic.api_key to config/secrets.yaml (see secrets.example.yaml)")
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "started": time.time(), "review_id": None, "error": None}

    def work():
        from ..research import review

        db = Database(settings.resolve(settings.paths.db), check_same_thread=False)
        try:
            run = review.run_review(db, settings, body.doc_ids)
            update = {"status": "done", "review_id": run.review_id}
        except Exception as e:  # noqa: BLE001 - reported to the page
            update = {"status": "error", "error": str(e)}
        finally:
            db.close()
        with _jobs_lock:
            _jobs[job_id].update(update)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/research/jobs/{job_id}")
def research_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {"id": job_id, **job}
