"""Trade lab: your own entry/exit rules (a TradePlan) on one or more stocks (docs/06-trade-lab-plan.md).

Per stock, day by day, one position at a time: flat -> in a position -> flat.
- Entry: a signal on day t (after the close; the stock must have traded) buys at t+1's open (its close if it
  has no open), or at t's close with `fill: same_close`. Explicit dates are buy days instead.
- Exit: the first rule to trigger, checked each day from entry + hold.min_days: stop, target (intraday,
  gaps fill at the open, stop first if both hit), trailing %, trailing MA, conditions (at the close),
  time limit (max_days after the signal day). If the window (plan.end, default the last stored day) ends
  first, the trade is marked at that close as "open". Data after the window is never used.
  Stop/target/trailing rules are only checked on days the stock traded.
- Returns are net of the round-trip cost; the cost is charged at the exit.
- Money, each stock on its own (default): every stock has its own capital; each trade puts
  capital.per_trade_pct of that stock's current equity in, the rest waits in cash.
- Money, shared (plan.portfolio): one pot for all stocks, at most max_positions open at once, each
  equity / max_positions (capped at the cash available). When more stocks signal on a day than there are
  free slots, the highest by portfolio.rank_by go first; the rest are skipped.
- Liquidity: each trade's stake vs the stock's average daily traded value (plan.liquidity) -> value_pct.

Same conventions as backtest.simulate_exit, which this reproduces for stop + trailing MA + time limit
with min_days 0 (verified by a test).
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules
from .config import Profile, TradePlan, condition_text, load_profile, set_plan_value
from .features import Columns
from .strategies import REGISTRY, Strategy

TRADE_COLUMNS = ["code", "signal_date", "entry_date", "entry", "entry_actual", "exit_date", "exit", "exit_actual",
                 "why", "days", "ret_pct", "best_pct", "worst_pct", "stake", "pnl", "value_pct", "flags"]
LOCK_FLAGS = ("no trades on the entry day", "high = low")


@dataclass
class LabResult:
    plan: TradePlan
    trades: pd.DataFrame          # TRADE_COLUMNS, one row per trade, in date order
    equity: pd.DataFrame          # date, code, equity, invested: daily mark-to-market per stock, or code
                                  # "portfolio" (+ positions, bench) with shared capital
    stocks: pd.DataFrame          # per code: window, buy & hold, plan return, drawdowns, time in market
    warnings: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)   # signals on the last stored day (buy at the next open)
    basket: str | None = None     # what add_basket compared with, e.g. "61 swing quality stocks"
    portfolio: dict | None = None  # shared capital: return_pct, max_dd_pct, bench_pct, skipped, ...


@dataclass
class _Stock:
    """One stock, prepared: the data up to the window's end, its candidate entries and exit inputs."""

    code: str
    g: pd.DataFrame
    w0: int
    w1: int
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    traded: np.ndarray
    adj: np.ndarray
    avg_value: np.ndarray                 # average daily traded value (BDT), per row, over liquidity.days
    ma: np.ndarray | None
    rule_exits: list[tuple[str, np.ndarray]]
    cands: list[tuple[int, int, float]]   # (signal row, entry row, priority), entry inside the data


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


def plan_codes(plan: TradePlan, db, metrics: pd.DataFrame | None = None) -> list[str]:
    """The plan's codes, plus its universe, filtered by its quality profile (needs the database)."""
    from . import quality
    from .universes import universe_codes

    codes = list(plan.codes)
    if plan.universe:
        codes += universe_codes(plan.universe, db)
    codes = list(dict.fromkeys(codes))
    if plan.quality:
        m = metrics if metrics is not None else quality.compute_quality_metrics(db, codes)
        keep = set(quality_codes(load_profile(plan.quality), m, codes))
        codes = [c for c in codes if c in keep]
    return codes


def run_plan(plan: TradePlan, prices: pd.DataFrame, strategy: Strategy | None = None,
             tuned_until: pd.Timestamp | None = None, cache: dict | None = None,
             codes: list[str] | None = None) -> LabResult:
    """prices: adjusted prices (all history, so indicators warm up) for the plan's stocks.
    codes: the stocks to run (default: plan.codes, else every stock in prices); see plan_codes for universes.
    strategy: defaults to entry_strategy(plan) (reads the profile from config).
    cache: pass the same dict to repeated runs on the same prices (a parameter grid) to reuse columns and signals."""
    if strategy is None and plan.entry.strategy:
        strategy, tuned_until = entry_strategy(plan)
    codes = codes or plan.codes or sorted(prices["code"].unique())
    by_code = {c: g for c, g in prices.groupby("code", sort=False)}
    stocks, warnings, pending = [], [], []
    for code in codes:
        g = by_code.get(code)
        if g is None or g.empty:
            warnings.append(f"{code}: no prices stored")
            continue
        st = _prepare(plan, g, strategy, cache, warnings, pending)
        if st is None:
            warnings.append(f"{code}: no prices in the window")
            continue
        stocks.append(st)

    portfolio = None
    if plan.portfolio is not None and stocks:
        trades, equity, infos, portfolio = _portfolio(plan, stocks)
    else:
        trades, equity, infos = [], [], []
        for st in stocks:
            t, eq, info = _independent(plan, st)
            trades += t
            equity.append(eq)
            infos.append(info)
        equity = pd.concat(equity, ignore_index=True) if equity else pd.DataFrame(columns=["date", "code", "equity", "invested"])

    trades = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    stocks_df = pd.DataFrame(infos)
    if not stocks_df.empty:
        stocks_df = stocks_df.set_index("code")

    closed = trades[trades["why"] != "open"]
    if 0 < len(closed) < 10:
        warnings.append(f"only {len(closed)} closed trade(s): treat as anecdotes, not evidence")
    if n_open := int((trades["why"] == "open").sum()):
        warnings.append(f"{n_open} trade(s) still open at the end of the window (marked at its close, not in the stats)")
    if n_flag := int(trades["flags"].map(lambda f: any(k in f for k in LOCK_FLAGS)).sum()):
        warnings.append(f"{n_flag} trade(s) flagged: the fill may not have been possible (see flags)")
    if n_big := int((trades["value_pct"] > plan.liquidity.max_pct).sum()):
        warnings.append(f"{n_big} trade(s) bigger than {plan.liquidity.max_pct:g}% of the stock's average daily traded "
                        f"value: hard to buy or sell without moving the price")
    if portfolio and portfolio["skipped"]:
        warnings.append(f"{portfolio['skipped']} signal(s) skipped because all {plan.portfolio.max_positions} "
                        f"slots were full (or no cash was left)")
    if not plan.exit.any:
        warnings.append("no exit rule: every trade is held until the end of the data")
    if tuned_until is not None and not trades.empty and trades["signal_date"].min() <= tuned_until:
        warnings.append(f"{plan.entry.strategy}'s {plan.entry.profile} settings were tuned on data up to "
                        f"{tuned_until:%Y-%m-%d}: trades before then are in-sample; judge on the later ones")
    if plan.quality:
        warnings.append(f"the {plan.quality} quality filter uses today's fundamentals: stocks that pass it now are "
                        f"applied to the past (look-ahead)")
    if plan.universe:
        warnings.append(f"the {plan.universe} universe is today's list: stocks that left it are missing (survivorship)")
    return LabResult(plan, trades.sort_values(["entry_date", "code"]).reset_index(drop=True), equity, stocks_df,
                     warnings, pending, portfolio=portfolio)


def _cached(cache: dict | None, key: tuple, fn):
    if cache is None:
        return fn()
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _prepare(plan: TradePlan, g: pd.DataFrame, strategy: Strategy | None, cache: dict | None,
             notes: list[str], pending: list[str]) -> _Stock | None:
    g = g.sort_values("date").reset_index(drop=True)
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
    cols = _cached(cache, ("cols", code, w1), lambda: Columns(g))
    out = None
    if strategy is not None:
        key = ("strategy", code, w1, strategy.name, json.dumps(strategy.p.model_dump(), sort_keys=True, default=str))
        out = _cached(cache, key, lambda: strategy.compute(g))

    # Candidate (signal row, entry row) pairs, signal (or buy date) inside the window
    if e_cfg.dates:
        pairs = []
        for d in sorted(e_cfg.dates):
            e = int(g["date"].searchsorted(pd.Timestamp(d)))
            if e > w1 or e < w0:
                notes.append(f"{code}: buy date {d} is outside the window or the data")
                continue
            pairs.append((e - 1 if nxt else e, e))
    else:
        sig = pd.Series(True, index=g.index)
        if out is not None:
            sig &= out["signal"].fillna(False).astype(bool) & (g.index >= strategy.min_history)
        if e_cfg.when:
            sig &= cols.all_true(e_cfg.when)
        sig &= g["volume"].fillna(0) > 0
        if e_cfg.new_signal_only:
            sig &= ~sig.shift(1, fill_value=False)
        rows = [int(s) for s in np.flatnonzero(sig.to_numpy()) if w0 <= s <= w1]
        pairs = [(s, s + 1 if nxt else s) for s in rows]
        warm = cols.first_valid(e_cfg.when + x_cfg.when_any)
        if strategy is not None:
            warm = max(warm, strategy.min_history)
        if warm > w0 and plan.start is not None:      # only worth saying when you chose the start
            first = g["date"].iloc[warm] if warm < n else None
            notes.append(f"{code}: indicators need {warm} trading days of history; first possible signal "
                         + (f"{first:%Y-%m-%d}" if first is not None else "never (not enough data)"))
        if not pairs and plan.portfolio is None:       # with many stocks, a silent one is normal
            win = slice(w0, w1 + 1)
            parts = [f"{condition_text(cd)} on {int(cols.check(cd).iloc[win].sum())}" for cd in e_cfg.when]
            if out is not None:
                parts.insert(0, f"{strategy.name} on {int(out['signal'].fillna(False).astype(bool).iloc[win].sum())}")
            notes.append(f"{code}: no entry signal in the window; days each part held: " + ", ".join(parts))

    prio = _priority(plan, cols, out, n)
    cands = []
    for s, e in pairs:
        if e >= n:
            if last_stored:
                pending.append(f"{code}: entry signal on {g['date'].iloc[s]:%Y-%m-%d} (the last stored day): "
                               f"buy at the next open")
            continue
        cands.append((s, e, float(prio[max(s, 0)])))

    value = g["value_mn"].astype(float) * 1e6 if "value_mn" in g else pd.Series(np.nan, index=g.index)
    return _Stock(
        code=code, g=g, w0=w0, w1=w1,
        o=g["open"].astype(float).to_numpy(), h=g["high"].astype(float).to_numpy(),
        lo=g["low"].astype(float).to_numpy(), c=g["close"].astype(float).to_numpy(),
        traded=(g["volume"].fillna(0) > 0).to_numpy(),
        adj=g["price_adj"].astype(float).to_numpy() if "price_adj" in g else np.ones(n),
        avg_value=value.rolling(plan.liquidity.days, min_periods=1).mean().to_numpy(),
        ma=cols[f"sma_{x_cfg.trail_ma}"].to_numpy() if x_cfg.trail_ma else None,
        rule_exits=[(condition_text(cd), cols.check(cd).to_numpy()) for cd in x_cfg.when_any],
        cands=cands,
    )


def _priority(plan: TradePlan, cols: Columns, out: pd.DataFrame | None, n: int) -> np.ndarray:
    """Per row: the ranking value when stocks compete for portfolio slots (higher goes first)."""
    pf = plan.portfolio
    if pf is None or plan.entry.dates:
        return np.zeros(n)
    rank = pf.rank_by or ("score" if out is not None else "vol_x_20")
    vals = (out["score"] if rank == "score" else cols[rank]).astype(float).to_numpy()
    vals = vals if pf.descending else -vals
    return np.where(np.isnan(vals), -np.inf, vals)


def _trade(plan: TradePlan, st: _Stock, s: int, e: int) -> dict:
    """One trade: entry at row e (signal row s), its exit, outcome and fill flags. Stake is added by the caller."""
    nxt = plan.entry.fill == "next_open"
    o, h, lo, c, traded = st.o, st.h, st.lo, st.c, st.traded
    entry = o[e] if nxt and not np.isnan(o[e]) else c[e]
    j, px, why = _exit(plan, s, e, entry, o, h, lo, c, traded, st.ma, st.rule_exits)
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
    dates = st.g["date"]
    return {
        "code": st.code, "signal_date": dates.iloc[max(s, 0)], "entry_date": dates.iloc[e],
        "entry": entry, "entry_actual": entry / st.adj[e], "exit_date": dates.iloc[j], "exit": px,
        "exit_actual": px / st.adj[j], "why": why, "days": j - s, "ret_pct": (px / entry - 1) * 100 - plan.costs.round_trip_pct,
        "best_pct": best, "worst_pct": worst, "flags": flags, "_s": s, "_e": e, "_j": j,
    }


def _size(plan: TradePlan, st: _Stock, t: dict, stake: float) -> None:
    """Record the stake, the money made, and the stake vs the stock's average traded value (in place)."""
    t["stake"], t["pnl"] = stake, stake * t["ret_pct"] / 100
    value = st.avg_value[max(t["_s"], 0)]
    t["value_pct"] = stake / value * 100 if value > 0 else np.nan
    flags = t["flags"]
    if t["value_pct"] > plan.liquidity.max_pct:
        flags.append(f"stake is {t['value_pct']:.0f}% of the {plan.liquidity.days}-day average traded value")
    t["flags"] = "; ".join(flags)


def _stock_info(plan: TradePlan, st: _Stock, trades: list[dict]) -> dict:
    o, c, w0, w1 = st.o, st.c, st.w0, st.w1
    first_px = o[w0] if not np.isnan(o[w0]) else c[w0]
    held = np.zeros(w1 - w0 + 1, dtype=bool)
    for t in trades:
        held[max(t["_e"] - w0, 0):t["_j"] - w0 + 1] = True
    return {
        "code": st.code, "start": st.g["date"].iloc[w0], "end": st.g["date"].iloc[w1],
        "first_close": c[w0], "last_close": c[w1],
        "buy_hold_pct": (c[w1] / first_px - 1) * 100 - plan.costs.round_trip_pct,
        "buy_hold_max_dd_pct": _max_drawdown(pd.Series(c[w0:w1 + 1])),
        "in_market_pct": held.mean() * 100,
        "trades": len(trades), "open": sum(t["why"] == "open" for t in trades),
        "pnl": sum(t["pnl"] for t in trades),
    }


def _independent(plan: TradePlan, st: _Stock) -> tuple[list[dict], pd.DataFrame, dict]:
    """Each stock on its own: one position at a time, its own capital."""
    trades, busy_until = [], -1
    for s, e, _ in st.cands:
        if e <= busy_until:
            continue
        t = _trade(plan, st, s, e)
        busy_until = t["_j"] + plan.hold.cooldown_days
        trades.append(t)
    eq, stakes = _equity(plan, st, trades)
    for t, stake in zip(trades, stakes):
        _size(plan, st, t, stake)
    info = _stock_info(plan, st, trades)
    info.update({"plan_pct": (eq["equity"].iloc[-1] / plan.capital.start - 1) * 100,
                 "plan_max_dd_pct": _max_drawdown(eq["equity"]), "end_equity": eq["equity"].iloc[-1]})
    return trades, eq, info


def _portfolio(plan: TradePlan, stocks: list[_Stock]) -> tuple[list[dict], pd.DataFrame, list[dict], dict]:
    """Shared capital: walk every stock's candidate entries in date order, at most max_positions open at once."""
    pf, start = plan.portfolio, plan.capital.start
    same_close = plan.entry.fill == "same_close"
    span = {st.code: st.g["date"].iloc[st.w0:st.w1 + 1] for st in stocks}
    cal = pd.DatetimeIndex(sorted(set().union(*[set(d) for d in span.values()])))
    pos_of = {d: i for i, d in enumerate(cal)}
    close = pd.DataFrame({st.code: pd.Series(st.c[st.w0:st.w1 + 1], index=span[st.code].to_numpy())
                          for st in stocks}).reindex(cal).ffill()

    events = sorted(((st.g["date"].iat[e], -prio, st.code, s, e, st) for st in stocks for s, e, prio in st.cands),
                    key=lambda x: x[:3])
    cash, open_, busy, trades, skipped = start, [], {}, [], 0
    for day, group in itertools.groupby(events, key=lambda x: x[0]):
        still = []
        for p in open_:                    # sold at the close before today's open (or at today's close)
            if p["exit_date"] < day or (same_close and p["exit_date"] <= day):
                cash += p["proceeds"]
            else:
                still.append(p)
        open_ = still
        i = pos_of[day]
        mark = cal[i] if same_close else cal[max(i - 1, 0)]
        equity_now = cash + sum(p["shares"] * close.at[mark, p["code"]] for p in open_)
        for _, _, code, s, e, st in group:
            if e <= busy.get(code, -1):
                continue
            stake = min(equity_now / pf.max_positions, cash)
            if len(open_) >= pf.max_positions or stake <= 0:
                skipped += 1
                continue
            t = _trade(plan, st, s, e)
            _size(plan, st, t, stake)
            cash -= stake
            open_.append({"code": code, "exit_date": t["exit_date"], "shares": stake / t["entry"],
                          "proceeds": stake + t["pnl"]})
            busy[code] = t["_j"] + plan.hold.cooldown_days
            trades.append(t)

    # Daily equity: cash (stakes out on entry days, proceeds in on exit days) + open positions at the close
    flow, value, count = np.zeros(len(cal)), np.zeros(len(cal)), np.zeros(len(cal), dtype=int)
    for t in trades:
        a, b = pos_of[t["entry_date"]], pos_of[t["exit_date"]]
        flow[a] -= t["stake"]
        flow[b] += t["stake"] + t["pnl"]
        value[a:b] += t["stake"] / t["entry"] * close[t["code"]].to_numpy()[a:b]
        count[a:b] += 1
    equity = start + np.cumsum(flow) + value
    # Benchmark: the same money split equally over the plan's stocks, bought at each one's first open and held
    bench, share = np.zeros(len(cal)), start / len(stocks)
    for st in stocks:
        i0 = pos_of[span[st.code].iloc[0]]
        first_px = st.o[st.w0] if not np.isnan(st.o[st.w0]) else st.c[st.w0]
        v = np.full(len(cal), share)
        v[i0:] = share * close[st.code].to_numpy()[i0:] / first_px
        bench += v
    eq = pd.DataFrame({"date": cal, "code": "portfolio", "equity": equity, "invested": count > 0,
                       "positions": count, "bench": bench})
    cost = plan.costs.round_trip_pct
    summary = {
        "return_pct": (equity[-1] / start - 1) * 100, "max_dd_pct": _max_drawdown(pd.Series(equity)),
        "bench_pct": (bench[-1] / start - 1) * 100 - cost, "bench_max_dd_pct": _max_drawdown(pd.Series(bench)),
        "avg_positions": float(count.mean()), "max_positions": pf.max_positions, "in_market_pct": float((count > 0).mean() * 100),
        "skipped": skipped, "end_equity": float(equity[-1]), "stocks": len(stocks),
    }
    infos = []
    for st in stocks:
        mine = [t for t in trades if t["code"] == st.code]
        info = _stock_info(plan, st, mine)
        info.update({"plan_pct": np.nan, "plan_max_dd_pct": np.nan, "end_equity": np.nan})
        infos.append(info)
    return trades, eq, infos, summary


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


def _equity(plan: TradePlan, st: _Stock, trades: list[dict]) -> tuple[pd.DataFrame, list[float]]:
    """Daily equity over the window (cash, plus the position marked at the close; cost charged at the exit),
    and each trade's stake."""
    c, w0, w1 = st.c, st.w0, st.w1
    eq = np.empty(w1 - w0 + 1)
    invested = np.zeros(w1 - w0 + 1, dtype=bool)
    cash, k, stakes = plan.capital.start, w0, []
    pos = {t["_e"]: t for t in trades}
    while k <= w1:
        t = pos.get(k)
        if t is None:
            eq[k - w0] = cash
            k += 1
            continue
        stake = cash * plan.capital.per_trade_pct / 100
        stakes.append(stake)
        rest = cash - stake
        j = t["_j"]
        for d in range(k, j):
            eq[d - w0] = rest + stake * c[d] / t["entry"]
            invested[d - w0] = True
        cash = rest + stake * (1 + t["ret_pct"] / 100)
        eq[j - w0] = cash
        invested[j - w0] = True
        k = j + 1
    return pd.DataFrame({"date": st.g["date"].iloc[w0:w1 + 1].to_numpy(), "code": st.code,
                         "equity": eq, "invested": invested}), stakes


def _max_drawdown(values: pd.Series) -> float:
    v = pd.Series(values, dtype=float).reset_index(drop=True)
    return float(((v / v.cummax() - 1) * 100).min()) if len(v) else np.nan


def quality_codes(profile: Profile, metrics: pd.DataFrame, universe: list[str]) -> list[str]:
    """The profile's universe stocks that pass its quality filter today: the basket the backtest also uses."""
    qf = profile.filters.get("quality")
    q = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
    keep = set(universe)
    return [c for c in q.index[q["passed"]] if c in keep]


class Basket:
    """An equal-weight basket of stocks to compare trades with. Build once, apply to many results (a grid)."""

    def __init__(self, prices: pd.DataFrame, codes: list[str], label: str):
        p = prices[prices["code"].isin(codes)]
        self.label = label
        self.close = p.pivot(index="date", columns="code", values="close").astype(float)
        self.open = p.pivot(index="date", columns="code", values="open").astype(float).fillna(self.close)
        traded = p.assign(t=p["volume"].fillna(0).astype(float) > 0).pivot(index="date", columns="code", values="t")
        self.traded = traded.astype("boolean").fillna(False).astype(bool)

    def _ret(self, d0, d1, px0: pd.DataFrame, cost: float, mask: pd.DataFrame | None = None) -> float:
        if d0 not in self.close.index or d1 not in self.close.index:
            return np.nan
        r = self.close.loc[d1] / px0.loc[d0] - 1
        if mask is not None:
            r = r[mask.loc[d0]]
        r = r.dropna()
        return float(r.mean() * 100 - cost) if len(r) else np.nan

    def apply(self, result: LabResult) -> None:
        """Per trade: every basket stock that traded on the entry day, bought like the trade (that day's open, or
        its close with same_close) and sold at its close on the exit day, net of the same cost -> basket_pct,
        excess_pct. Per stock: the basket held over the stock's window -> basket_hold_pct. In place."""
        if self.close.empty:
            return
        buy = self.open if result.plan.entry.fill == "next_open" else self.close
        cost = result.plan.costs.round_trip_pct
        t = result.trades
        t["basket_pct"] = [self._ret(a, b, buy, cost, self.traded) for a, b in zip(t["entry_date"], t["exit_date"])]
        t["excess_pct"] = t["ret_pct"] - t["basket_pct"]
        if not result.stocks.empty:
            result.stocks["basket_hold_pct"] = [self._ret(a, b, self.open, cost) for a, b in
                                                zip(result.stocks["start"], result.stocks["end"])]
        if result.portfolio is not None and not result.equity.empty:
            d = result.equity["date"]
            result.portfolio["basket_hold_pct"] = self._ret(d.iloc[0], d.iloc[-1], self.open, cost)
        result.basket = self.label


def add_basket(result: LabResult, prices: pd.DataFrame, codes: list[str], label: str) -> None:
    """Compare with an equal-weight basket of `codes` over the same dates (in place); see Basket.apply."""
    Basket(prices, codes, label).apply(result)


def summarize(result: LabResult) -> pd.DataFrame:
    """Stats on closed trades: all, tuning/test periods (plan.in_sample_until), per stock, per exit reason."""
    t = result.trades[result.trades["why"] != "open"]
    segments = {"all": t}
    cut = result.plan.in_sample_until
    if cut is not None:
        segments["in-sample"] = t[t["signal_date"] <= pd.Timestamp(cut)]
        segments["out-of-sample"] = t[t["signal_date"] > pd.Timestamp(cut)]
    if 1 < t["code"].nunique() <= 20:              # per stock only while it stays readable
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


MAX_COMBOS = 100


def sweep(plan: TradePlan, grid: dict[str, list], prices: pd.DataFrame, basket: Basket | None = None,
          codes: list[str] | None = None) -> pd.DataFrame:
    """Run the plan once per combination of grid values (paths like exit.stop_pct or entry.when.1.2).

    One row per combination: the values, then trades / mean / win rate / profit factor (/ vs basket) for all
    closed trades and, with in_sample_until, the tuning (in_) and test (out_) periods; return_pct and max_dd_pct
    (the portfolio's with shared capital, else the average stock's / the worst stock's).
    Choose on the tuning period; the test period is the honest check.
    """
    combos = list(itertools.product(*grid.values()))
    if len(combos) > MAX_COMBOS:
        raise ValueError(f"{len(combos)} combinations; at most {MAX_COMBOS}")
    base = plan.model_dump(mode="json", by_alias=True)
    cache: dict = {}
    rows = []
    for combo in combos:
        data = copy.deepcopy(base)
        for path, value in zip(grid, combo):
            try:
                set_plan_value(data, path, value)
            except (KeyError, IndexError, ValueError, TypeError) as e:
                raise ValueError(f"grid path '{path}' doesn't fit the plan ({e})") from e
        res = run_plan(TradePlan.model_validate(data), prices, cache=cache, codes=codes)
        if basket is not None:
            basket.apply(res)
        s = summarize(res)
        row = dict(zip(grid, combo))
        for seg, key in (("all", "all"), ("in-sample", "in"), ("out-of-sample", "out")):
            if seg in s.index:
                r = s.loc[seg]
                row.update({f"{key}_trades": int(r["trades"]), f"{key}_mean": r["mean_ret"], f"{key}_win": r["win_rate"],
                            f"{key}_pf": r["profit_factor"]})
                if "mean_excess" in r:
                    row[f"{key}_vs_basket"] = r["mean_excess"]
        if res.portfolio is not None:
            row["return_pct"], row["max_dd_pct"] = res.portfolio["return_pct"], res.portfolio["max_dd_pct"]
        elif not res.stocks.empty:
            row["return_pct"], row["max_dd_pct"] = res.stocks["plan_pct"].mean(), res.stocks["plan_max_dd_pct"].min()
        rows.append(row)
    return pd.DataFrame(rows)


def describe(plan: TradePlan) -> list[str]:
    """The plan in plain words: stocks (when a universe is used), buy / sell / hold / money lines."""
    e, x, hd = plan.entry, plan.exit, plan.hold
    lines = []
    if plan.universe or plan.quality:
        what = ", ".join(plan.codes)
        if plan.universe:
            what = (what + " + " if what else "") + f"every {plan.universe} stock"
        if plan.quality:
            what += f", only those passing the {plan.quality} quality filter today"
        lines.append(f"Stocks: {what}")
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
    if plan.portfolio:
        pf = plan.portfolio
        rank = pf.rank_by or ("score" if e.strategy else "vol_x_20")
        rank = "strategy score" if rank == "score" else rank
        money = (f"Shared capital {plan.capital.start:,.0f}: up to {pf.max_positions} positions at once, each 1/{pf.max_positions} "
                 f"of equity (capped at the cash left); with more signals than free slots, the {'highest' if pf.descending else 'lowest'} "
                 f"{rank} first; costs {plan.costs.round_trip_pct:g}% round trip")
    else:
        money = (f"Costs {plan.costs.round_trip_pct:g}% round trip; {plan.capital.per_trade_pct:g}% of equity per trade, "
                 f"starting with {plan.capital.start:,.0f}; one position at a time per stock")
    return [*lines, buy, sell, hold, money]
