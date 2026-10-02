"""Trade lab: your own entry/exit rules (a TradePlan) on one or more stocks (docs/06-trade-lab-plan.md).

Per stock, day by day, one position at a time: flat -> in a position -> flat.
- Entry: a signal on day t (after the close; the stock must have traded) buys at t+1's open (its close if it
  has no open), or at t's close with `fill: same_close`. Explicit dates are buy days instead.
- Exit: the first rule to trigger, checked each day from entry + hold.min_days: stop, target (intraday,
  gaps fill at the open, stop first if both hit), trailing %, trailing MA, conditions (at the close),
  time limit (max_days after the signal day). If the window (plan.end, default the last stored day) ends
  first, the trade is marked at that close as "open". Data after the window is never used.
  Stop/target/trailing rules are only checked on days the stock traded.
- Returns are net of the round-trip cost. Money: each trade puts capital.per_trade_pct of the current
  equity in; the rest waits in cash; the cost is charged at the exit.

Same conventions as backtest.simulate_exit, which this reproduces for stop + trailing MA + time limit
with min_days 0 (verified by a test).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules
from .config import Profile, TradePlan, condition_text, load_profile
from .features import Columns
from .strategies import REGISTRY, Strategy

TRADE_COLUMNS = ["code", "signal_date", "entry_date", "entry", "entry_actual", "exit_date", "exit", "exit_actual",
                 "why", "days", "ret_pct", "best_pct", "worst_pct", "flags"]


@dataclass
class LabResult:
    plan: TradePlan
    trades: pd.DataFrame          # TRADE_COLUMNS, one row per trade, in date order
    equity: pd.DataFrame          # date, code, equity, invested (bool): daily mark-to-market per stock
    stocks: pd.DataFrame          # per code: window, buy & hold, plan return, drawdowns, time in market
    warnings: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)   # signals on the last stored day (buy at the next open)
    basket: str | None = None     # what add_basket compared with, e.g. "61 swing quality stocks"


def entry_strategy(plan: TradePlan) -> tuple[Strategy | None, pd.Timestamp | None]:
    """The plan's strategy (profile params, then the plan's overrides) and the date its profile was tuned up to."""
    e = plan.entry
    if not e.strategy:
        return None, None
    if e.strategy not in REGISTRY:
        raise ValueError(f"unknown strategy '{e.strategy}'. Known: {', '.join(sorted(REGISTRY))}")
    params, tuned = {}, None
    if e.profile:
        prof = load_profile(e.profile)
        cfg = prof.strategies.get(e.strategy)
        if cfg is None:
            raise ValueError(f"profile '{e.profile}' has no strategy '{e.strategy}'")
        params = dict(cfg.params)
        if prof.backtest.in_sample_until:
            tuned = pd.Timestamp(prof.backtest.in_sample_until)
    return REGISTRY[e.strategy]({**params, **e.params}), tuned


def run_plan(plan: TradePlan, prices: pd.DataFrame, strategy: Strategy | None = None,
             tuned_until: pd.Timestamp | None = None) -> LabResult:
    """prices: adjusted prices (all history, so indicators warm up) for the plan's codes.
    strategy: defaults to entry_strategy(plan) (reads the profile from config)."""
    if strategy is None and plan.entry.strategy:
        strategy, tuned_until = entry_strategy(plan)
    codes = plan.codes or sorted(prices["code"].unique())
    by_code = {c: g for c, g in prices.groupby("code", sort=False)}
    trades, equity, stocks, warnings, pending = [], [], [], [], []
    for code in codes:
        g = by_code.get(code)
        if g is None or g.empty:
            warnings.append(f"{code}: no prices stored")
            continue
        g = g.sort_values("date").reset_index(drop=True)
        res = _simulate_stock(plan, g, strategy)
        if res is None:
            warnings.append(f"{code}: no prices in the window")
            continue
        t, eq, info, notes, pend = res
        trades += t
        equity.append(eq)
        stocks.append(info)
        warnings += notes
        pending += pend

    trades = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    equity = pd.concat(equity, ignore_index=True) if equity else pd.DataFrame(columns=["date", "code", "equity", "invested"])
    stocks = pd.DataFrame(stocks)
    if not stocks.empty:
        stocks = stocks.set_index("code")

    closed = trades[trades["why"] != "open"]
    if 0 < len(closed) < 10:
        warnings.append(f"only {len(closed)} closed trade(s): treat as anecdotes, not evidence")
    if n_open := int((trades["why"] == "open").sum()):
        warnings.append(f"{n_open} trade(s) still open at the end of the window (marked at its close, not in the stats)")
    if n_flag := int((trades["flags"] != "").sum()):
        warnings.append(f"{n_flag} trade(s) flagged: the fill may not have been possible (see flags)")
    if not plan.exit.any:
        warnings.append("no exit rule: every trade is held until the end of the data")
    if tuned_until is not None and not trades.empty and trades["signal_date"].min() <= tuned_until:
        warnings.append(f"{plan.entry.strategy}'s {plan.entry.profile} settings were tuned on data up to "
                        f"{tuned_until:%Y-%m-%d}: trades before then are in-sample; judge on the later ones")
    return LabResult(plan, trades.sort_values(["entry_date", "code"]).reset_index(drop=True), equity, stocks,
                     warnings, pending)


def _signals(plan: TradePlan, g: pd.DataFrame, cols: Columns, strategy: Strategy | None) -> pd.Series:
    """Entry signal per row (after that day's close), on the full history."""
    e = plan.entry
    sig = pd.Series(True, index=g.index)
    if strategy is not None:
        out = strategy.compute(g)
        sig &= out["signal"].fillna(False).astype(bool) & (g.index >= strategy.min_history)
    if e.when:
        sig &= cols.all_true(e.when)
    sig &= g["volume"].fillna(0) > 0
    if e.new_signal_only:
        sig &= ~sig.shift(1, fill_value=False)
    return sig


def _simulate_stock(plan: TradePlan, g: pd.DataFrame, strategy: Strategy | None):
    lo_d = pd.Timestamp(plan.start) if plan.start else g["date"].iloc[0]
    hi_d = pd.Timestamp(plan.end) if plan.end else g["date"].iloc[-1]
    in_window = ((g["date"] >= lo_d) & (g["date"] <= hi_d)).to_numpy()
    if not in_window.any():
        return None
    code = str(g["code"].iloc[0])
    w0, w1 = int(np.flatnonzero(in_window)[0]), int(np.flatnonzero(in_window)[-1])
    last_stored = w1 == len(g) - 1
    g = g.iloc[:w1 + 1]                  # the window's end is the end of the data: no peeking past it
    n = len(g)
    e_cfg, x_cfg = plan.entry, plan.exit
    nxt = e_cfg.fill == "next_open"
    cols = Columns(g)
    notes, pending = [], []

    # Candidate (signal row, entry row) pairs, signal (or buy date) inside the window
    if e_cfg.dates:
        cands = []
        for d in sorted(e_cfg.dates):
            e = int(g["date"].searchsorted(pd.Timestamp(d)))
            if e > w1 or e < w0:
                notes.append(f"{code}: buy date {d} is outside the window or the data")
                continue
            cands.append((e - 1 if nxt else e, e))
    else:
        sig = _signals(plan, g, cols, strategy).to_numpy()
        rows = [s for s in np.flatnonzero(sig) if w0 <= s <= w1]
        cands = [(s, s + 1 if nxt else s) for s in rows]
        warm = cols.first_valid(e_cfg.when + x_cfg.when_any)
        if strategy is not None:
            warm = max(warm, strategy.min_history)
        if warm > w0 and plan.start is not None:      # only worth saying when you chose the start
            first = g["date"].iloc[warm] if warm < n else None
            notes.append(f"{code}: indicators need {warm} trading days of history; first possible signal "
                         + (f"{first:%Y-%m-%d}" if first is not None else "never (not enough data)"))
        if not cands:
            win = slice(w0, w1 + 1)
            parts = [f"{condition_text(cd)} on {int(cols.check(cd).iloc[win].sum())}" for cd in e_cfg.when]
            if strategy is not None:
                out = strategy.compute(g)["signal"].fillna(False).astype(bool)
                parts.insert(0, f"{strategy.name} on {int(out.iloc[win].sum())}")
            notes.append(f"{code}: no entry signal in the window; days each part held: " + ", ".join(parts))

    o, h, lo, c = (g[k].astype(float).to_numpy() for k in ("open", "high", "low", "close"))
    traded = (g["volume"].fillna(0) > 0).to_numpy()
    adj = g["price_adj"].astype(float).to_numpy() if "price_adj" in g else np.ones(n)
    ma = cols[f"sma_{x_cfg.trail_ma}"].to_numpy() if x_cfg.trail_ma else None
    rule_exits = [(condition_text(cd), cols.check(cd).to_numpy()) for cd in x_cfg.when_any]
    cost = plan.costs.round_trip_pct

    trades, busy_until = [], -1
    for s, e in cands:
        if e >= n:
            if last_stored:
                pending.append(f"{code}: entry signal on {g['date'].iloc[s]:%Y-%m-%d} (the last stored day): "
                               f"buy at the next open")
            continue
        if e <= busy_until:
            continue
        entry = o[e] if nxt and not np.isnan(o[e]) else c[e]
        j, px, why = _exit(plan, s, e, entry, o, h, lo, c, traded, ma, rule_exits)
        busy_until = j + plan.hold.cooldown_days
        path = slice(e if nxt else e + 1, j + 1)
        flags = []
        if not traded[e]:
            flags.append("no trades on the entry day")
        elif nxt and e > 0 and h[e] == lo[e] and c[e] > c[e - 1]:
            flags.append("entry day high = low, up (possibly locked at the upper limit)")
        if why not in ("time", "open", "target") and j > 0 and traded[j] and h[j] == lo[j] and c[j] < c[j - 1]:
            flags.append("exit day high = low, down (possibly locked at the lower limit)")
        with np.errstate(invalid="ignore"):
            best = (np.nanmax(h[path]) / entry - 1) * 100 if path.start < path.stop else np.nan
            worst = (np.nanmin(lo[path]) / entry - 1) * 100 if path.start < path.stop else np.nan
        trades.append({
            "code": code, "signal_date": g["date"].iloc[max(s, 0)], "entry_date": g["date"].iloc[e],
            "entry": entry, "entry_actual": entry / adj[e], "exit_date": g["date"].iloc[j], "exit": px,
            "exit_actual": px / adj[j], "why": why, "days": j - s, "ret_pct": (px / entry - 1) * 100 - cost,
            "best_pct": best, "worst_pct": worst, "flags": "; ".join(flags), "_e": e, "_j": j,
        })

    eq = _equity(plan, g, trades, w0, w1)
    first_px = o[w0] if not np.isnan(o[w0]) else c[w0]
    closes = pd.Series(c[w0:w1 + 1])
    info = {
        "code": code, "start": g["date"].iloc[w0], "end": g["date"].iloc[w1],
        "first_close": c[w0], "last_close": c[w1],
        "buy_hold_pct": (c[w1] / first_px - 1) * 100 - cost,
        "buy_hold_max_dd_pct": _max_drawdown(closes),
        "plan_pct": (eq["equity"].iloc[-1] / plan.capital.start - 1) * 100,
        "plan_max_dd_pct": _max_drawdown(eq["equity"]),
        "in_market_pct": eq["invested"].mean() * 100,
        "trades": len(trades), "open": sum(t["why"] == "open" for t in trades),
        "end_equity": eq["equity"].iloc[-1],
    }
    return trades, eq, info, notes, pending


def _exit(plan: TradePlan, s: int, e: int, entry: float, o, h, lo, c, traded, ma,
          rule_exits: list[tuple[str, np.ndarray]]) -> tuple[int, float, str]:
    """(exit row, exit price, reason) for an entry at row e on signal row s."""
    x = plan.exit
    n = len(c)
    first = e + plan.hold.min_days
    if plan.entry.fill == "same_close":
        first = max(first, e + 1)                    # bought at the close: nothing left of that day
    stop = entry * (1 - x.stop_pct / 100) if x.stop_pct else None
    target = entry * (1 + x.target_pct / 100) if x.target_pct else None
    time_row = max(s + x.max_days, first) if x.max_days is not None else None
    last = min(time_row, n - 1) if time_row is not None else n - 1
    peak = entry
    for j in range(e, last + 1):
        if j > e or plan.entry.fill == "next_open":
            peak = max(peak, c[j]) if not np.isnan(c[j]) else peak
        if j < first:
            continue
        if traded[j]:
            if stop is not None and o[j] <= stop:
                return j, float(o[j]), "stop"            # gapped below the stop: filled at the open
            if target is not None and o[j] >= target:
                return j, float(o[j]), "target"          # gapped above the target
            if stop is not None and lo[j] <= stop:
                return j, float(stop), "stop"            # both in the day's range: assume the stop came first
            if target is not None and h[j] >= target:
                return j, float(target), "target"
            if j > e:
                if x.trail_pct and c[j] <= peak * (1 - x.trail_pct / 100):
                    return j, float(c[j]), f"trail {x.trail_pct:g}%"
                if ma is not None and c[j] < ma[j]:
                    return j, float(c[j]), f"below MA{x.trail_ma}"
                for text, hit in rule_exits:
                    if hit[j]:
                        return j, float(c[j]), text
        if j == time_row:
            return j, float(c[j]), "time"
    return n - 1, float(c[-1]), "open"


def _equity(plan: TradePlan, g: pd.DataFrame, trades: list[dict], w0: int, w1: int) -> pd.DataFrame:
    """Daily equity over the window: cash, plus the position marked at the close; cost charged at the exit."""
    c = g["close"].astype(float).to_numpy()
    eq = np.empty(w1 - w0 + 1)
    invested = np.zeros(w1 - w0 + 1, dtype=bool)
    cash, k = plan.capital.start, w0
    pos = {t["_e"]: t for t in trades}
    while k <= w1:
        t = pos.get(k)
        if t is None:
            eq[k - w0] = cash
            k += 1
            continue
        stake = cash * plan.capital.per_trade_pct / 100
        rest = cash - stake
        j = t["_j"]
        for d in range(k, j):
            eq[d - w0] = rest + stake * c[d] / t["entry"]
            invested[d - w0] = True
        cash = rest + stake * (1 + t["ret_pct"] / 100)
        eq[j - w0] = cash
        invested[j - w0] = True
        k = j + 1
    return pd.DataFrame({"date": g["date"].iloc[w0:w1 + 1].to_numpy(), "code": g["code"].iloc[0],
                         "equity": eq, "invested": invested})


def _max_drawdown(values: pd.Series) -> float:
    v = pd.Series(values, dtype=float).reset_index(drop=True)
    return float(((v / v.cummax() - 1) * 100).min()) if len(v) else np.nan


def quality_codes(profile: Profile, metrics: pd.DataFrame, universe: list[str]) -> list[str]:
    """The profile's universe stocks that pass its quality filter today: the basket the backtest also uses."""
    qf = profile.filters.get("quality")
    q = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
    keep = set(universe)
    return [c for c in q.index[q["passed"]] if c in keep]


def add_basket(result: LabResult, prices: pd.DataFrame, codes: list[str], label: str) -> None:
    """Compare with an equal-weight basket of `codes` over the same dates (in place).

    Per trade: every basket stock that traded on the entry day, bought like the trade (that day's open, or its
    close with same_close) and sold at its close on the exit day, net of the same cost -> basket_pct, excess_pct.
    Per stock: the basket held over the stock's window (first open to last close) -> basket_hold_pct.
    """
    p = prices[prices["code"].isin(codes)]
    if p.empty:
        return
    close = p.pivot(index="date", columns="code", values="close").astype(float)
    open_ = p.pivot(index="date", columns="code", values="open").astype(float).fillna(close)
    traded = p.assign(t=p["volume"].fillna(0).astype(float) > 0).pivot(index="date", columns="code", values="t")
    traded = traded.astype("boolean").fillna(False).astype(bool)
    buy = open_ if result.plan.entry.fill == "next_open" else close
    cost = result.plan.costs.round_trip_pct

    def basket(d0, d1, px0, mask=None) -> float:
        if d0 not in close.index or d1 not in close.index:
            return np.nan
        r = close.loc[d1] / px0.loc[d0] - 1
        if mask is not None:
            r = r[mask.loc[d0]]
        r = r.dropna()
        return float(r.mean() * 100 - cost) if len(r) else np.nan

    t = result.trades
    t["basket_pct"] = [basket(a, b, buy, traded) for a, b in zip(t["entry_date"], t["exit_date"])]
    t["excess_pct"] = t["ret_pct"] - t["basket_pct"]
    if not result.stocks.empty:
        result.stocks["basket_hold_pct"] = [basket(a, b, open_) for a, b in
                                            zip(result.stocks["start"], result.stocks["end"])]
    result.basket = label


def summarize(result: LabResult) -> pd.DataFrame:
    """Stats on closed trades: all, tuning/test periods (plan.in_sample_until), per stock, per exit reason."""
    t = result.trades[result.trades["why"] != "open"]
    segments = {"all": t}
    cut = result.plan.in_sample_until
    if cut is not None:
        segments["in-sample"] = t[t["signal_date"] <= pd.Timestamp(cut)]
        segments["out-of-sample"] = t[t["signal_date"] > pd.Timestamp(cut)]
    if t["code"].nunique() > 1:
        for code, gg in t.groupby("code"):
            segments[f"  {code}"] = gg
    for why, gg in t.groupby("why"):
        segments[f"  exit: {why}"] = gg
    rows = []
    for name, gg in segments.items():
        r = gg["ret_pct"]
        win, loss = r[r > 0], r[r <= 0]
        rows.append({
            "segment": name, "trades": len(gg),
            "win_rate": (r > 0).mean() * 100 if len(gg) else np.nan,
            "mean_ret": r.mean(), "median_ret": r.median(), "avg_win": win.mean(), "avg_loss": loss.mean(),
            "profit_factor": win.sum() / -loss.sum() if loss.sum() < 0 else np.nan,
            "best": r.max(), "worst": r.min(), "median_days": gg["days"].median(),
        })
        if "basket_pct" in gg:
            x = gg["excess_pct"]
            rows[-1].update({"mean_basket": gg["basket_pct"].mean(), "mean_excess": x.mean(),
                             "median_excess": x.median(),
                             "beat_basket": (x > 0).mean() * 100 if x.notna().any() else np.nan})
    return pd.DataFrame(rows).set_index("segment")


def describe(plan: TradePlan) -> list[str]:
    """The plan in plain words: buy / sell / hold / money lines."""
    e, x, hd = plan.entry, plan.exit, plan.hold
    at = "at the next open" if e.fill == "next_open" else "at the close"
    if e.dates:
        buy = f"Buy on {', '.join(f'{d:%d %b %Y}' for d in e.dates)}, " + ("at the open" if e.fill == "next_open" else "at the close")
    else:
        what = []
        if e.strategy:
            src = f"{e.profile} settings" if e.profile else "default settings"
            what.append(f"{e.strategy} signals with {src}" + (f" + {e.params}" if e.params else ""))
        what += [condition_text(cd) for cd in e.when]
        buy = f"Buy {at} when " + " and ".join(what) + ("; first day of each setup only" if e.new_signal_only else "")
    sells = []
    if x.stop_pct:
        sells.append(f"-{x.stop_pct:g}% stop (intraday low)")
    if x.target_pct:
        sells.append(f"+{x.target_pct:g}% target (intraday high)")
    if x.trail_pct:
        sells.append(f"close {x.trail_pct:g}% below its highest since entry")
    if x.trail_ma:
        sells.append(f"close below MA{x.trail_ma}")
    sells += [f"close with {condition_text(cd)}" for cd in x.when_any]
    if x.max_days is not None:
        sells.append(f"{x.max_days} trading days after the signal")
    sell = ("Sell on the first of: " + "; ".join(sells)) if sells else "Never sell (held to the end of the data)"
    hold = f"No exit before {hd.min_days} trading day(s) after entry"
    if hd.cooldown_days:
        hold += f"; wait {hd.cooldown_days} trading day(s) after an exit before buying again"
    money = (f"Costs {plan.costs.round_trip_pct:g}% round trip; {plan.capital.per_trade_pct:g}% of equity per trade, "
             f"starting with {plan.capital.start:,.0f}; one position at a time per stock")
    return [buy, sell, hold, money]
