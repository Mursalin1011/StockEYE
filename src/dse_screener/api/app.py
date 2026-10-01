"""FastAPI app serving the stored data, screens, charts and backtests as JSON.

Read-mostly: the only write is POST /api/screens/run. Bound to localhost by the CLI.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import date

import pandas as pd
import yaml
from fastapi import Depends, FastAPI, HTTPException, Query

from .. import backtest, engine, indicators, quality, report, rules
from ..config import CONFIG_DIR, list_profiles, load_profile, load_settings, load_universe
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


def universe_codes() -> list[str]:
    return sorted({c for n in list_profiles(settings) for c in load_universe(load_profile(n).universe).codes})


def adjusted_prices(db: Database) -> pd.DataFrame:
    return cached(("prices", _data_version(db)), 600,
                  lambda: engine.load_adjusted_prices(db, settings, universe_codes()))


def quality_metrics(db: Database) -> pd.DataFrame:
    return cached(("metrics", _data_version(db)), 600,
                  lambda: quality.compute_quality_metrics(db, universe_codes()))


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
        "universe": universe_codes(),
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
    codes = sorted(set(picks["code"]))
    news = report.recent_news(db, codes, date.fromisoformat(as_of), settings.report)
    order = {n: i for i, n in enumerate(list_profiles(settings))}
    profiles = []
    for run in sorted(day.itertuples(), key=lambda r: order.get(r.profile, 99)):
        p_picks = picks[picks["run_id"] == run.run_id]
        profiles.append({
            "profile": run.profile,
            "description": load_profile(run.profile).description if run.profile in order else "",
            "run_id": int(run.run_id), "run_at": run.run_at,
            "universe_size": int(run.universe_size), "passed_quality": int(run.passed_quality),
            "signals": int((sigs["run_id"] == run.run_id).sum()),
            "picks": [{**r, "news": news.get(r["code"], [])}
                      for r in records(p_picks.drop(columns=["run_id"]))],
        })
    return {"as_of": as_of, "market": report.market_summary(db, date.fromisoformat(as_of)), "profiles": profiles}


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
    codes = universe_codes()
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
    if code not in universe_codes():
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
    close = g["close"]
    ind = pd.DataFrame({"date": g["date"], "rsi": indicators.rsi(close),
                        "vol_avg": indicators.sma(g["volume"].astype(float), 20)}).join(indicators.macd(close))

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

    start = max(len(g) - days, 0)
    g, ind = g.iloc[start:], ind.iloc[start:]
    first_day = g["date"].iloc[0].strftime("%Y-%m-%d")
    bars = g[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ("open", "high", "low"):          # no-trade days: flat bar at the carried close
        bars[col] = bars[col].fillna(bars["close"])
    acts = db.load_corporate_actions([code])
    ex = [d.strftime("%Y-%m-%d") for d in acts["ex_date"].dropna() if d >= g["date"].iloc[0]]
    return {
        "code": code, "profile": profile,
        "bars": records(bars.rename(columns={"date": "time"})),
        "indicators": records(ind.rename(columns={"date": "time"})),
        "markers": [mk for mk in markers if mk["time"] >= first_day],
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


@app.get("/api/backtest/{profile}")
def backtest_view(profile: str, db: Database = Depends(get_db)):
    """Backtest summary per holding period (cached until data or the profile file changes)."""
    prof = _profile(profile)
    mtime = (CONFIG_DIR / "profiles" / f"{profile}.yaml").stat().st_mtime

    def run():
        codes = load_universe(prof.universe).codes
        res = backtest.run_backtest(prof, adjusted_prices(db), quality_metrics(db), db.load_corporate_actions(codes))
        summaries = {str(h): records(backtest.summarize(res, h).reset_index()) for h in res.horizons}
        return {
            "profile": profile, "start": res.start.strftime("%Y-%m-%d"), "end": res.end.strftime("%Y-%m-%d"),
            "in_sample_until": res.in_sample_until.strftime("%Y-%m-%d") if res.in_sample_until is not None else None,
            "cost_pct": prof.backtest.cost_pct, "primary_horizon": res.primary, "horizons": res.horizons,
            "universe_size": len(res.universe), "summary": summaries,
            "trades": records(res.trades.sort_values("date", ascending=False)),
        }

    return cached(("backtest", profile, mtime, _data_version(db)), 3600, run)


@app.get("/api/config/raw")
def config_raw():
    """Parsed profiles (for future editing UI)."""
    return {n: yaml.safe_load((CONFIG_DIR / "profiles" / f"{n}.yaml").read_text(encoding="utf-8"))
            for n in list_profiles(settings)}
