"""Backtest a profile: what if you had bought each day's shortlist?

- Same strategies and ranking as the live screen (engine.rank), evaluated on every date.
  Strategy windows look backward only, so computing once over the full history and
  reading the row for date t equals screening on date t (verified by a test).
- Entry: next trading day's open (the screen runs after the close); exit: close
  `h` trading days after the signal. Round-trip cost subtracted.
- Exit styles (`backtest.exits`): stop / trailing MA / time limit, on the same entries.
- Benchmark: equal-weight basket of every quality-passing stock, same entry/exit dates.
- Non-overlapping: after a pick, the same stock is not counted again until its
  primary-horizon trade has ended.
- Recall: share of "big winner" moves (e.g. +50% within 120 days) that a pick or a
  strategy signal caught early, and how many signals that took.

Known biases (be careful when reading results):
- Quality filter and fundamentals are today's values applied to the past.
- The universe is today's list (survivorship: stocks that dropped out are missing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules, technical
from .config import ExitRule, Profile, WinnersConfig
from .engine import SIGNAL_COLUMNS, _record_dates_near, build_strategies, rank


@dataclass
class BacktestResult:
    profile: str
    trades: pd.DataFrame        # one row per pick: date, code, final_score, strategies, ret_h, bench_h, excess_h, ...
    horizons: list[int]
    primary: int
    in_sample_until: pd.Timestamp | None
    universe: list[str]
    start: pd.Timestamp
    end: pd.Timestamp
    exits: dict[str, ExitRule] = field(default_factory=dict)
    signals: pd.DataFrame = field(default_factory=pd.DataFrame)  # first day of each strategy signal: date, code, strategy, role, i, entry
    picks: pd.DataFrame = field(default_factory=pd.DataFrame)    # every daily shortlist, before the non-overlap rule
    winners: pd.DataFrame = field(default_factory=pd.DataFrame)  # big-winner moves: code, date, i, start, peak_gain_pct
    winners_cfg: WinnersConfig = field(default_factory=WinnersConfig)

    @property
    def keys(self) -> list[int | str]:
        """Summary keys: holding periods, then exit styles."""
        return [*self.horizons, *self.exits]


def forward_returns(g: pd.DataFrame, horizons: list[int], cost_pct: float) -> pd.DataFrame:
    """For each row i: buy at open of i+1 (close if no open), sell at close of i+h. Net of costs."""
    entry = entry_prices(g)
    out = pd.DataFrame(index=g.index)
    for h in horizons:
        out[f"ret_{h}"] = (g["close"].shift(-h) / entry - 1) * 100 - cost_pct
    return out


def entry_prices(g: pd.DataFrame) -> pd.Series:
    """Entry for a signal on row i: the next day's open (its close if it has no open)."""
    return g["open"].shift(-1).fillna(g["close"].shift(-1))


def simulate_exit(g: pd.DataFrame, i: int, rule: ExitRule, ma: pd.Series | None = None) -> tuple[int, float, str] | None:
    """Exit for a signal on row i (entry at row i+1's open): (exit row, exit price, reason).

    Reasons: stop, trail (close below the MA), time (max_days after the signal), open (data ends first,
    marked at the last close). Stop and trail are checked only on days the stock traded.
    """
    n = len(g)
    e = i + 1
    if e >= n:
        return None
    o, lo, c = g["open"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
    traded = g["volume"].fillna(0).to_numpy() > 0
    entry = o[e] if not np.isnan(o[e]) else c[e]
    stop = entry * (1 - rule.stop_pct / 100) if rule.stop_pct else None
    m = ma.to_numpy(float) if ma is not None else None
    for j in range(e, min(i + rule.max_days, n - 1) + 1):
        if traded[j]:
            if stop is not None and lo[j] <= stop:
                return j, float(np.fmin(stop, o[j])), "stop"        # a gap down fills at the open
            if m is not None and j > e and c[j] < m[j]:
                return j, float(c[j]), "trail"
        if j == i + rule.max_days:
            return j, float(c[j]), "time"
    return n - 1, float(c[-1]), "open"


def big_moves(g: pd.DataFrame, cfg: WinnersConfig) -> pd.DataFrame:
    """Big-winner moves: from day t (traded) the close rises >= min_gain_pct within within_days.

    One move per episode: t is the first qualifying day, and the move lasts until its peak close;
    qualifying days before that peak (pullbacks inside the same run-up) are the same move.
    """
    close = g["close"].to_numpy(float)
    fwd_max = g["close"][::-1].rolling(cfg.within_days, min_periods=1).max()[::-1].shift(-1).to_numpy(float)
    big = (fwd_max / close >= 1 + cfg.min_gain_pct / 100) & (g["volume"].fillna(0).to_numpy() > 0)
    rows, busy_until = [], -1
    for i in np.flatnonzero(big):
        if i <= busy_until:
            continue
        window = close[i + 1:i + 1 + cfg.within_days]
        peak = i + 1 + int(np.nanargmax(window))
        busy_until = peak
        rows.append({"date": g.at[i, "date"], "i": int(i), "start": close[i],
                     "peak_date": g.at[peak, "date"], "peak_gain_pct": (close[peak] / close[i] - 1) * 100})
    return pd.DataFrame(rows, columns=["date", "i", "start", "peak_date", "peak_gain_pct"]).astype(
        {"date": "datetime64[ns]", "i": int, "start": float, "peak_date": "datetime64[ns]", "peak_gain_pct": float})


def exit_label(name: str, rule: ExitRule) -> str:
    if rule.label:
        return rule.label
    parts = []
    if rule.stop_pct:
        parts.append(f"-{rule.stop_pct:g}% stop")
    if rule.trail_ma:
        parts.append(f"below MA{rule.trail_ma}")
    parts.append(f"max {rule.max_days} days")
    return ", ".join(parts)


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
    tf_cfg = profile.filters.get("technical")
    use_tech = bool(tf_cfg and tf_cfg.enabled and tf_cfg.rules)

    signal_rows, fwd_rows, move_rows, series = [], [], [], {}
    by_code = {c: g for c, g in prices.groupby("code", sort=False)}
    for code in passed:
        g = by_code.get(code)
        if g is None or g.empty:
            continue
        g = g.sort_values("date").reset_index(drop=True)
        series[code] = g
        traded = g["volume"].fillna(0) > 0
        fwd = forward_returns(g, horizons, bt.cost_pct)
        fwd["date"], fwd["code"], fwd["traded"] = g["date"], code, traded
        fwd["i"], fwd["entry"] = g.index, entry_prices(g)
        fwd_rows.append(fwd)
        moves = big_moves(g, bt.winners)
        moves["code"] = code
        move_rows.append(moves)
        # Technical filter (RSI/MACD) evaluated on each signal's own day, as the live screen does
        tech_ok = rules.passes(technical.technical_frame(g, tf_cfg.params), tf_cfg.rules) if use_tech else True
        for strat, cfg in strategies:
            out = strat.compute(g)
            ok = tech_ok if (not use_tech or tf_cfg.applies_to(strat.name)) else True
            hit = out["signal"].astype(bool) & (out.index >= strat.min_history) & traded & ok
            for i in out.index[hit]:
                signal_rows.append({
                    "date": g.at[i, "date"], "code": code, "strategy": strat.name, "title": strat.title,
                    "role": cfg.role, "score": float(out.at[i, "score"]),
                    "weighted": float(out.at[i, "score"]) * cfg.weight, "reasons": [], "metrics": {}, "i": i,
                })

    fwd_all = pd.concat(fwd_rows, ignore_index=True) if fwd_rows else pd.DataFrame()
    all_signals = pd.DataFrame(signal_rows, columns=["date", *SIGNAL_COLUMNS, "i"])
    lo = pd.Timestamp(start) if start else fwd_all["date"].min()
    hi = pd.Timestamp(end) if end else fwd_all["date"].max()
    all_signals = all_signals[(all_signals["date"] >= lo) & (all_signals["date"] <= hi)]
    signals = all_signals.drop(columns="i")

    # Benchmark per date: mean forward return of all quality-passing stocks traded that day
    bench = fwd_all[fwd_all["traded"]].groupby("date")[[f"ret_{h}" for h in horizons]].mean()

    picks = []
    window = profile.ranking.record_date_window_days
    for day, sig in signals.groupby("date"):
        ranked = rank(sig.drop(columns="date"), metrics, profile, _record_dates_near(actions, day.date(), window))
        for r, p in enumerate(ranked.itertuples(), 1):
            picks.append({"date": day, "code": p.code, "rank": r, "final_score": p.final_score,
                          "strategies": "+".join(sorted(p.strategies))})
    all_picks = pd.DataFrame(picks, columns=["date", "code", "rank", "final_score", "strategies"])
    trades = _non_overlapping(all_picks, fwd_all, bt.primary_horizon)
    trades = trades.merge(fwd_all[["date", "code", "i", "entry", *[f"ret_{h}" for h in horizons]]],
                          on=["date", "code"], how="left")
    for h in horizons:
        trades[f"bench_{h}"] = trades["date"].map(bench[f"ret_{h}"])
        trades[f"excess_{h}"] = trades[f"ret_{h}"] - trades[f"bench_{h}"]
    if bt.exits and not trades.empty:
        _apply_exits(trades, bt.exits, series, fwd_all, bt.cost_pct)

    moves = pd.concat(move_rows, ignore_index=True) if move_rows else pd.DataFrame(
        columns=["date", "i", "start", "peak_date", "peak_gain_pct", "code"])
    moves = moves[(moves["date"] >= lo) & (moves["date"] <= hi)].reset_index(drop=True)

    cut = pd.Timestamp(bt.in_sample_until) if bt.in_sample_until else None
    return BacktestResult(profile.name, trades, horizons, bt.primary_horizon, cut, passed, lo, hi,
                          exits=dict(bt.exits), signals=_first_days(all_signals, fwd_all), picks=all_picks,
                          winners=moves, winners_cfg=bt.winners)


def _apply_exits(trades: pd.DataFrame, exits: dict[str, ExitRule], series: dict[str, pd.DataFrame],
                 fwd_all: pd.DataFrame, cost_pct: float) -> None:
    """Add ret_/bench_/excess_/days_/exit_/why_<name> columns for each exit style (in place).

    The basket is held over the same dates: every quality stock traded on the signal day,
    bought at its next open and sold at its close on the trade's exit day.
    """
    entry_px = fwd_all.pivot(index="date", columns="code", values="entry")
    traded = fwd_all.assign(t=fwd_all["traded"].astype(float)).pivot(index="date", columns="code", values="t").fillna(0) > 0
    close_px = pd.concat({c: g.set_index("date")["close"] for c, g in series.items()}, axis=1)
    for name, rule in exits.items():
        mas = {c: g["close"].rolling(rule.trail_ma).mean() for c, g in series.items()} if rule.trail_ma else {}
        rets, benches, days, dates, why = [], [], [], [], []
        for t in trades.itertuples():
            g = series[t.code]
            res = simulate_exit(g, int(t.i), rule, mas.get(t.code))
            if res is None:
                rets.append(np.nan), benches.append(np.nan), days.append(np.nan), dates.append(pd.NaT), why.append(None)
                continue
            j, px, reason = res
            d1 = g.at[j, "date"]
            cols = traded.columns[traded.loc[t.date].to_numpy()]
            basket = (close_px.loc[d1, cols] / entry_px.loc[t.date, cols] - 1).mean() * 100 - cost_pct
            rets.append((px / t.entry - 1) * 100 - cost_pct)
            benches.append(basket)
            days.append(j - int(t.i))
            dates.append(d1)
            why.append(reason)
        trades[f"ret_{name}"], trades[f"bench_{name}"] = rets, benches
        trades[f"excess_{name}"] = trades[f"ret_{name}"] - trades[f"bench_{name}"]
        trades[f"days_{name}"], trades[f"exit_{name}"], trades[f"why_{name}"] = days, dates, why


def _first_days(signals: pd.DataFrame, fwd_all: pd.DataFrame) -> pd.DataFrame:
    """First day of each consecutive run of a strategy's signal, with its entry price."""
    if signals.empty:
        return pd.DataFrame(columns=["date", "code", "strategy", "role", "i", "entry"])
    s = signals[["date", "code", "strategy", "role", "i"]].sort_values(["code", "strategy", "i"])
    new_run = (s["code"] != s["code"].shift()) | (s["strategy"] != s["strategy"].shift()) | (s["i"] != s["i"].shift() + 1)
    s = s[new_run]
    return s.merge(fwd_all[["date", "code", "entry"]], on=["date", "code"], how="left").reset_index(drop=True)


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


def summarize(result: BacktestResult, key: int | str | None = None) -> pd.DataFrame:
    """Stats per segment for one holding period (int) or exit style (name):
    all / in-sample / out-of-sample / per strategy mix. Exit-style trades still open are left out."""
    k = key if key is not None else result.primary
    t = result.trades.dropna(subset=[f"ret_{k}"])
    is_exit = isinstance(k, str)
    if is_exit:
        t = t[t[f"why_{k}"] != "open"]
    segments = {"all": t}
    if result.in_sample_until is not None:
        segments["in-sample"] = t[t["date"] <= result.in_sample_until]
        segments["out-of-sample"] = t[t["date"] > result.in_sample_until]
    for mix, g in t.groupby("strategies"):
        segments[f"  {mix}"] = g
    rows = []
    for name, g in segments.items():
        r, b, x = g[f"ret_{k}"], g[f"bench_{k}"], g[f"excess_{k}"]
        win, loss = r[r > 0], r[r <= 0]
        rows.append({
            "segment": name, "trades": len(g),
            "median_ret": r.median(), "mean_ret": r.mean(), "hit_rate": (r > 0).mean() * 100 if len(g) else np.nan,
            "avg_win": win.mean(), "avg_loss": loss.mean(),
            # Gross profit / gross loss: > 1 means the winners paid for the losers
            "profit_factor": win.sum() / -loss.sum() if loss.sum() < 0 else np.nan,
            "median_bench": b.median(), "median_excess": x.median(), "mean_excess": x.mean(),
            "beat_bench": (x > 0).mean() * 100 if len(g) else np.nan, "worst": r.min(), "best": r.max(),
            "median_days": g[f"days_{k}"].median() if is_exit else float(k),
        })
    return pd.DataFrame(rows).set_index("segment")


def recall(result: BacktestResult) -> pd.DataFrame:
    """How many big-winner moves were caught early, by the shortlist and by each strategy.

    Shortlist = the non-overlapping trades; strategies = the first day of each signal. Caught = a hit on the
    same stock from before_days before to after_days after the move's first day, entry <= start x (1 + premium).
    """
    w, cfg = result.winners, result.winners_cfg
    sources = {"shortlist": result.trades[["date", "code", "i", "entry"]]}
    for strat, g in (result.signals.groupby("strategy") if not result.signals.empty else []):
        role = g["role"].iloc[0]
        sources[f"  {strat}" + (" (confirm)" if role != "primary" else "")] = g
    periods = {"": (None, None)}
    if result.in_sample_until is not None:
        periods = {"": (None, None), ", in-sample": (None, result.in_sample_until),
                   ", out-of-sample": (result.in_sample_until, None)}
    rows = []
    for src, hits in sources.items():
        for suffix, (after, upto) in periods.items():
            if src != "shortlist" and suffix:
                continue                      # per-period split only for the shortlist
            # Split by the move's start date; a catch may come from just across the boundary, so match
            # against every hit, but count only this period's hits as signals spent
            ww, hh = w, hits
            if after is not None:
                ww, hh = w[w["date"] > after], hits[hits["date"] > after]
            if upto is not None:
                ww, hh = w[w["date"] <= upto], hits[hits["date"] <= upto]
            caught, leads = _catches(ww, hits, cfg)
            rows.append({
                "segment": src + suffix, "moves": len(ww), "caught": caught,
                "recall_pct": caught / len(ww) * 100 if len(ww) else np.nan,
                "signals": len(hh), "signals_per_catch": len(hh) / caught if caught else np.nan,
                "median_days_after_start": float(np.median(leads)) if leads else np.nan,
            })
    return pd.DataFrame(rows).set_index("segment")


def _catches(moves: pd.DataFrame, hits: pd.DataFrame, cfg: WinnersConfig) -> tuple[int, list[int]]:
    if moves.empty or hits.empty:
        return 0, []
    m = moves.reset_index(drop=True).reset_index(names="move").merge(
        hits[["code", "i", "entry"]].rename(columns={"i": "hit_i"}), on="code")
    ok = ((m["hit_i"] >= m["i"] - cfg.before_days) & (m["hit_i"] <= m["i"] + cfg.after_days)
          & (m["entry"] <= m["start"] * (1 + cfg.max_entry_premium_pct / 100)))
    first = m[ok].sort_values("hit_i").groupby("move")["hit_i"].first()
    leads = (first - moves.reset_index(drop=True).loc[first.index, "i"]).astype(int).tolist()
    return len(first), leads
