"""Backtest a profile: what if you had bought each day's shortlist?

- Same strategies and ranking as the live screen (engine.rank), evaluated on every date.
  Strategy windows look backward only, so computing once over the full history and
  reading the row for date t equals screening on date t (verified by a test).
- Entry: next trading day's open (the screen runs after the close); exit: close
  `h` trading days after the signal. Round-trip cost subtracted.
- Benchmark: equal-weight basket of every quality-passing stock, same entry/exit.
- Non-overlapping: after a pick, the same stock is not counted again until its
  primary-horizon trade has ended.

Known biases (be careful when reading results):
- Quality filter and fundamentals are today's values applied to the past.
- The universe is today's DS30 (survivorship: stocks that dropped out are missing).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import rules
from .config import Profile
from .engine import SIGNAL_COLUMNS, _record_dates_near, build_strategies, rank


@dataclass
class BacktestResult:
    profile: str
    trades: pd.DataFrame        # one row per pick: date, code, final_score, strategies, ret_h, bench_h, excess_h
    horizons: list[int]
    primary: int
    in_sample_until: pd.Timestamp | None
    universe: list[str]
    start: pd.Timestamp
    end: pd.Timestamp


def forward_returns(g: pd.DataFrame, horizons: list[int], cost_pct: float) -> pd.DataFrame:
    """For each row i: buy at open of i+1 (close if no open), sell at close of i+h. Net of costs."""
    entry = g["open"].shift(-1).fillna(g["close"].shift(-1))
    out = pd.DataFrame(index=g.index)
    for h in horizons:
        out[f"ret_{h}"] = (g["close"].shift(-h) / entry - 1) * 100 - cost_pct
    return out


def run_backtest(
    profile: Profile,
    prices: pd.DataFrame,
    metrics: pd.DataFrame,
    actions: pd.DataFrame | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> BacktestResult:
    bt = profile.backtest
    horizons = sorted(set(bt.horizons) | {bt.primary_horizon})
    qf = profile.filters.get("quality")
    q = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
    passed = q.index[q["passed"]].tolist()
    strategies = build_strategies(profile)

    signal_rows, fwd_rows = [], []
    for code in passed:
        g = prices[prices["code"] == code].sort_values("date").reset_index(drop=True)
        if g.empty:
            continue
        traded = g["volume"].fillna(0) > 0
        fwd = forward_returns(g, horizons, bt.cost_pct)
        fwd["date"], fwd["code"], fwd["traded"] = g["date"], code, traded
        fwd_rows.append(fwd)
        for strat, cfg in strategies:
            out = strat.compute(g)
            hit = out["signal"].astype(bool) & (out.index >= strat.min_history) & traded
            for i in out.index[hit]:
                signal_rows.append({
                    "date": g.at[i, "date"], "code": code, "strategy": strat.name, "title": strat.title,
                    "role": cfg.role, "score": float(out.at[i, "score"]),
                    "weighted": float(out.at[i, "score"]) * cfg.weight, "reasons": [], "metrics": {},
                })

    fwd_all = pd.concat(fwd_rows, ignore_index=True) if fwd_rows else pd.DataFrame()
    signals = pd.DataFrame(signal_rows, columns=["date", *SIGNAL_COLUMNS])
    lo = pd.Timestamp(start) if start else fwd_all["date"].min()
    hi = pd.Timestamp(end) if end else fwd_all["date"].max()
    signals = signals[(signals["date"] >= lo) & (signals["date"] <= hi)]

    # Benchmark per date: mean forward return of all quality-passing stocks traded that day
    bench = fwd_all[fwd_all["traded"]].groupby("date")[[f"ret_{h}" for h in horizons]].mean()

    picks = []
    window = profile.ranking.record_date_window_days
    for day, sig in signals.groupby("date"):
        ranked = rank(sig.drop(columns="date"), metrics, profile, _record_dates_near(actions, day.date(), window))
        for r, p in enumerate(ranked.itertuples(), 1):
            picks.append({"date": day, "code": p.code, "rank": r, "final_score": p.final_score,
                          "strategies": "+".join(sorted(p.strategies))})
    trades = pd.DataFrame(picks, columns=["date", "code", "rank", "final_score", "strategies"])
    trades = _non_overlapping(trades, fwd_all, bt.primary_horizon)
    trades = trades.merge(fwd_all[["date", "code", *[f"ret_{h}" for h in horizons]]], on=["date", "code"],
                          how="left")
    for h in horizons:
        trades[f"bench_{h}"] = trades["date"].map(bench[f"ret_{h}"])
        trades[f"excess_{h}"] = trades[f"ret_{h}"] - trades[f"bench_{h}"]

    cut = pd.Timestamp(bt.in_sample_until) if bt.in_sample_until else None
    return BacktestResult(profile.name, trades, horizons, bt.primary_horizon, cut, passed, lo, hi)


def _non_overlapping(trades: pd.DataFrame, fwd_all: pd.DataFrame, hold: int) -> pd.DataFrame:
    """Drop repeat picks of a stock while its previous trade (hold trading days) is still open."""
    if trades.empty:
        return trades
    pos = {code: {d: i for i, d in enumerate(g["date"])} for code, g in fwd_all.groupby("code")}
    keep, busy_until = [], {}
    for t in trades.sort_values(["date", "rank"]).itertuples():
        i = pos[t.code][t.date]
        if i <= busy_until.get(t.code, -1):
            continue
        busy_until[t.code] = i + hold
        keep.append(t.Index)
    return trades.loc[keep].sort_values(["date", "rank"]).reset_index(drop=True)


def summarize(result: BacktestResult, horizon: int | None = None) -> pd.DataFrame:
    """Stats per segment for one horizon: all / in-sample / out-of-sample / per strategy mix."""
    h = horizon or result.primary
    t = result.trades.dropna(subset=[f"ret_{h}"])
    segments = {"all": t}
    if result.in_sample_until is not None:
        segments["in-sample"] = t[t["date"] <= result.in_sample_until]
        segments["out-of-sample"] = t[t["date"] > result.in_sample_until]
    for mix, g in t.groupby("strategies"):
        segments[f"  {mix}"] = g
    rows = []
    for name, g in segments.items():
        r, b, x = g[f"ret_{h}"], g[f"bench_{h}"], g[f"excess_{h}"]
        rows.append({
            "segment": name, "trades": len(g),
            "median_ret": r.median(), "mean_ret": r.mean(), "hit_rate": (r > 0).mean() * 100 if len(g) else np.nan,
            "median_bench": b.median(), "median_excess": x.median(), "mean_excess": x.mean(),
            "beat_bench": (x > 0).mean() * 100 if len(g) else np.nan, "worst": r.min(), "best": r.max(),
        })
    return pd.DataFrame(rows).set_index("segment")
