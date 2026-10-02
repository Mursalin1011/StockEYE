"""Case study: what every strategy of a profile did on one stock over a period, and how it turned out.

For any stock you spot (it doesn't have to pass the quality filter or be in the universe):
- each signal's first day (a run of consecutive signal days counts once), whether the RSI/MACD
  filter blocked it, the stock's ranking score that day and whether it clears the shortlist cut;
- outcomes from the next day's open: fixed holds, the profile's exit styles, best/worst within the
  main hold, and the return to the last close (all net of the round-trip cost, like the backtest);
- the stock's big-winner moves in the period and which strategies caught them early.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import rules, technical
from .backtest import big_moves, entry_prices, forward_returns, simulate_exit
from .config import Profile
from .engine import SIGNAL_COLUMNS, _plain, _record_dates_near, build_strategies, rank


@dataclass
class CaseStudy:
    code: str
    profile: str
    start: pd.Timestamp
    end: pd.Timestamp
    last_date: pd.Timestamp
    last_close: float
    window: dict                 # first/last close, change, low/high and their dates
    quality_passed: bool
    quality_failures: list[str]
    signals: pd.DataFrame        # one row per signal start (see module docstring)
    moves: pd.DataFrame          # big-winner moves starting in the window, with caught_by
    horizons: list[int]
    primary: int
    exits: list[str]
    cost_pct: float
    min_score: float


def run_casestudy(
    profile: Profile,
    g: pd.DataFrame,
    metrics: pd.DataFrame,
    actions: pd.DataFrame | None,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    picks: pd.DataFrame | None = None,
) -> CaseStudy:
    """g: adjusted prices for one stock (all history, so indicators warm up). metrics: its quality metrics row.
    picks: optional backtest shortlists (date, code, rank) to show the stock's actual rank among all stocks."""
    g = g.sort_values("date").reset_index(drop=True)
    code = str(g["code"].iloc[0])
    start = pd.Timestamp(start)
    end = pd.Timestamp(end) if end is not None else g["date"].iloc[-1]
    bt = profile.backtest
    horizons = sorted(set(bt.horizons) | {bt.primary_horizon})
    in_window = (g["date"] >= start) & (g["date"] <= end)
    if not in_window.any():
        raise ValueError(f"{code}: no prices between {start:%Y-%m-%d} and {end:%Y-%m-%d}")

    qf = profile.filters.get("quality")
    q = rules.evaluate(metrics.loc[[code]] if code in metrics.index else pd.DataFrame(index=pd.Index([code], name="code")),
                       qf.rules if qf and qf.enabled else {})
    tf = profile.filters.get("technical")
    use_tech = bool(tf and tf.enabled and tf.rules)
    tech = technical.technical_frame(g, tf.params if tf else None)
    tech_ok = rules.passes(tech, tf.rules) if use_tech else pd.Series(True, index=g.index)
    traded = g["volume"].fillna(0) > 0

    # Per strategy: effective signal (what the screen acts on) and signals blocked by the RSI/MACD filter
    outs, effective, blocked = {}, {}, {}
    strategies = build_strategies(profile)
    for strat, cfg in strategies:
        out = strat.compute(g)
        sig = out["signal"].astype(bool) & (out.index >= strat.min_history) & traded
        ok = tech_ok if (use_tech and tf.applies_to(strat.name)) else pd.Series(True, index=g.index)
        outs[strat.name], effective[strat.name], blocked[strat.name] = out, sig & ok, sig & ~ok

    fwd = forward_returns(g, horizons, bt.cost_pct)
    entry = entry_prices(g)
    close = g["close"]
    mas = {r.trail_ma: close.rolling(r.trail_ma).mean() for r in bt.exits.values() if r.trail_ma}
    window_days = profile.ranking.record_date_window_days
    pick_rank = {}
    if picks is not None and not picks.empty:
        mine = picks[picks["code"] == code]
        pick_rank = dict(zip(mine["date"], mine["rank"]))

    def day_score(i: int) -> float | None:
        """The stock's ranking score on day i from every strategy that fired (as the live screen ranks it)."""
        rows = [{"code": code, "strategy": s.name, "title": s.title, "role": c.role,
                 "score": float(outs[s.name].at[i, "score"]),
                 "weighted": float(outs[s.name].at[i, "score"]) * c.weight, "reasons": [], "metrics": {}}
                for s, c in strategies if effective[s.name][i]]
        if not rows:
            return None
        day = g.at[i, "date"]
        ranked = rank(pd.DataFrame(rows, columns=SIGNAL_COLUMNS), metrics, _uncut(profile),
                      _record_dates_near(actions, day.date(), window_days))
        return float(ranked["final_score"].iloc[0]) if len(ranked) else None

    rows = []
    for strat, cfg in strategies:
        for status, sig in (("signal", effective[strat.name]), ("blocked", blocked[strat.name])):
            starts = sig & ~sig.shift(1, fill_value=False) & in_window
            for i in g.index[starts]:
                out_row = outs[strat.name].loc[i]
                e = entry[i]
                days_on = int(sig.iloc[i:].astype(int).cumprod().sum())
                # The stock's score on each day of the run: a breakout's score often jumps on day 2
                run = list(range(i, i + days_on))
                scores = [day_score(k) for k in run] if status == "signal" else []
                valid = [(k, s) for k, s in zip(run, scores) if s is not None]
                cut = next((k for k, s in valid if s >= profile.ranking.min_score), None)
                ranks = [pick_rank[g.at[k, "date"]] for k in run if g.at[k, "date"] in pick_rank]
                row = {
                    "date": g.at[i, "date"], "strategy": strat.name, "title": strat.title, "role": cfg.role,
                    "status": status, "score": float(out_row["score"]),
                    "days_on": days_on,
                    "day_score": scores[0] if scores else None,
                    "best_score": max(s for _, s in valid) if valid else None,
                    "clears_cut": cut is not None,
                    "cut_date": g.at[cut, "date"] if cut is not None else None,
                    "shortlist_rank": min(ranks) if ranks else None,
                    "tech": technical.describe(tech.loc[i]),
                    "blocked_by": [f"{k}: {why}" for k, rule in (tf.rules.items() if use_tech else [])
                                   if (why := rule.check(tech.at[i, k])) is not None] if status == "blocked" else [],
                    "reasons": strat.reasons(out_row),
                    "close": float(close[i]), "entry": float(e) if pd.notna(e) else None,
                }
                for h in horizons:
                    row[f"ret_{h}"] = _plain(fwd.at[i, f"ret_{h}"])
                path = close.iloc[i + 1:i + 1 + bt.primary_horizon]
                ok = pd.notna(e) and len(path)
                row["best"] = (path.max() / e - 1) * 100 if ok else None
                row["worst"] = (path.min() / e - 1) * 100 if ok else None
                row["to_last"] = (close.iloc[-1] / e - 1) * 100 - bt.cost_pct if pd.notna(e) else None
                for name, rule in bt.exits.items():
                    res = simulate_exit(g, i, rule, mas.get(rule.trail_ma))
                    if res is None:
                        row[f"ret_{name}"], row[f"days_{name}"], row[f"why_{name}"] = None, None, None
                        continue
                    j, px, why = res
                    row[f"ret_{name}"] = (px / e - 1) * 100 - bt.cost_pct
                    row[f"days_{name}"], row[f"why_{name}"] = j - i, why
                rows.append(row)
    signals = pd.DataFrame(rows)
    if not signals.empty:
        signals["cut_date"] = pd.to_datetime(signals["cut_date"])
        signals = signals.sort_values(["date", "status", "strategy"], ascending=[True, False, True]).reset_index(drop=True)

    moves = big_moves(g, bt.winners)
    moves = moves[(moves["date"] >= start) & (moves["date"] <= end)].reset_index(drop=True)
    moves["caught_by"] = [_caught_by(m, g, effective, entry, bt.winners) for m in moves.itertuples()]

    w = g[in_window]
    return CaseStudy(
        code=code, profile=profile.name, start=w["date"].iloc[0], end=w["date"].iloc[-1],
        last_date=g["date"].iloc[-1], last_close=float(close.iloc[-1]),
        window={
            "first_close": float(w["close"].iloc[0]), "last_close": float(w["close"].iloc[-1]),
            "change_pct": float((w["close"].iloc[-1] / w["close"].iloc[0] - 1) * 100),
            "low": float(w["close"].min()), "low_date": w.loc[w["close"].idxmin(), "date"],
            "high": float(w["close"].max()), "high_date": w.loc[w["close"].idxmax(), "date"],
        },
        quality_passed=bool(q["passed"].iloc[0]), quality_failures=list(q["failures"].iloc[0]),
        signals=signals, moves=moves, horizons=horizons, primary=bt.primary_horizon,
        exits=list(bt.exits), cost_pct=bt.cost_pct, min_score=profile.ranking.min_score,
    )


def _uncut(profile: Profile) -> Profile:
    """Same ranking without the min_score/top_n cut, so a below-cut day still shows its score."""
    p = profile.model_copy(deep=True)
    p.ranking.min_score, p.ranking.top_n = -np.inf, 10**6
    return p


def _caught_by(move, g, effective: dict[str, pd.Series], entry: pd.Series, cfg) -> list[str]:
    lo, hi = move.i - cfg.before_days, move.i + cfg.after_days
    cap = move.start * (1 + cfg.max_entry_premium_pct / 100)
    out = []
    for name, sig in effective.items():
        idx = sig.index[sig & (sig.index >= lo) & (sig.index <= hi)]
        if any(entry[i] <= cap for i in idx):
            out.append(name)
    return out
