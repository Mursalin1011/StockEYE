"""Big moves across every stock, and which strategies caught them early (dashboard page "Big moves").

For every stock given (the quality filter is not applied, so speculative names are included):
- its big-winner moves over the whole history (backtest.big_moves with the `backtest.winners` rule);
- the first day of every signal from every profile's strategies, after that profile's RSI/MACD filter
  (what the screen acts on), with outcomes from the next day's open;
- per move, the strategies that caught it early: the same rule as the backtest's recall (a signal from
  `before_days` before to `after_days` after the move's first day, entry <= start x (1 + premium)).

Strategies are keyed "profile:strategy" because the same strategy runs with different parameters per profile.

A full scan takes about a minute (every strategy of every profile on ~320 stocks), so the result is stored:
the daily job rebuilds it after the summary is sent, and `latest()` rebuilds it only when prices or a
profile changed since.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import engine, quality as quality_metrics, rules, technical
from .backtest import big_moves, entry_prices, forward_returns
from .config import Profile, Settings, WinnersConfig, list_profiles, load_profile
from .db import Database
from .engine import build_strategies
from .strategies import REGISTRY
from .universes import universe_codes

log = logging.getLogger(__name__)
_build_lock = threading.Lock()

MOVE_COLUMNS = ["code", "date", "peak_date", "start", "peak", "peak_gain_pct", "days", "avg_value_mn_60", "caught_by"]
SIGNAL_COLUMNS = ["date", "code", "profile", "strategy", "role", "score", "close", "ret", "best", "to_last",
                  "quality", "avg_value_mn_60"]


@dataclass
class MovesScan:
    start: pd.Timestamp
    end: pd.Timestamp
    winners: WinnersConfig
    horizon: int                  # trading days for `ret` and `best` on each signal
    moves: pd.DataFrame           # MOVE_COLUMNS; caught_by = [{key, profile, strategy, date, days_from_start, gain_left_pct}]
    signals: pd.DataFrame         # SIGNAL_COLUMNS, one row per signal start
    quality: dict[str, set[str]]  # profile -> codes passing its quality filter today


def effective_signals(profile: Profile, g: pd.DataFrame) -> list[tuple[str, str, pd.Series, pd.Series]]:
    """(strategy, role, signal, score) per enabled strategy: signal days the screen acts on (traded, warmed up,
    not blocked by the profile's RSI/MACD filter)."""
    # A strategy can't fire before min_history days (e.g. a new listing): skip its slow compute
    strategies = [(s, c) for s, c in build_strategies(profile) if len(g) > s.min_history]
    if not strategies:
        return []
    tf = profile.filters.get("technical")
    use_tech = bool(tf and tf.enabled and tf.rules)
    tech_ok = rules.passes(technical.technical_frame(g, tf.params), tf.rules) if use_tech else None
    traded = g["volume"].fillna(0) > 0
    out = []
    for strat, cfg in strategies:
        res = strat.compute(g)
        sig = res["signal"].astype(bool) & (res.index >= strat.min_history) & traded
        if use_tech and tf.applies_to(strat.name):
            sig &= tech_ok
        out.append((strat.name, cfg.role, sig, res["score"]))
    return out


def scan(profiles: list[Profile], prices: pd.DataFrame, metrics: pd.DataFrame,
         winners: WinnersConfig | None = None, horizon: int = 20) -> MovesScan:
    """prices: adjusted prices of every stock to scan. metrics: quality metrics (one row per code).
    winners: the big-move rule (default: the first profile's `backtest.winners`)."""
    winners = winners or profiles[0].backtest.winners
    cost = profiles[0].backtest.cost_pct
    quality = {}
    for p in profiles:
        qf = p.filters.get("quality")
        q = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
        quality[p.name] = set(q.index[q["passed"]])

    move_rows, signal_rows = [], []
    for code, g in prices.groupby("code", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        entry = entry_prices(g)
        close = g["close"]
        ret = forward_returns(g, [horizon], cost)[f"ret_{horizon}"]
        best = close[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1) / entry * 100 - 100
        avg_value = g["value_mn"].fillna(0).rolling(60, min_periods=20).mean()
        last = close.iloc[-1]

        fired = {}
        for p in profiles:
            for name, role, sig, score in effective_signals(p, g):
                key = f"{p.name}:{name}"
                fired[key] = (p.name, name, sig)
                for i in g.index[sig & ~sig.shift(1, fill_value=False)]:
                    signal_rows.append({
                        "date": g.at[i, "date"], "code": code, "profile": p.name, "strategy": name, "role": role,
                        "score": float(score[i]), "close": float(close[i]), "ret": _num(ret[i]), "best": _num(best[i]),
                        "to_last": _num((last / entry[i] - 1) * 100 - cost), "quality": code in quality[p.name],
                        "avg_value_mn_60": _num(avg_value[i]),
                    })

        for m in big_moves(g, winners).itertuples():
            peak = m.start * (1 + m.peak_gain_pct / 100)
            move_rows.append({
                "code": code, "date": m.date, "peak_date": m.peak_date, "start": m.start, "peak": peak,
                "peak_gain_pct": m.peak_gain_pct, "days": int(g.index[g["date"] == m.peak_date][0] - m.i),
                "avg_value_mn_60": _num(avg_value[m.i]), "caught_by": _caught_by(m, g, fired, entry, peak, winners),
            })

    signals = pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS)
    moves = pd.DataFrame(move_rows, columns=MOVE_COLUMNS)
    if len(moves):
        moves = moves.sort_values("peak_gain_pct", ascending=False).reset_index(drop=True)
    return MovesScan(prices["date"].min(), prices["date"].max(), winners, horizon, moves, signals, quality)


def _caught_by(move, g, fired: dict, entry: pd.Series, peak: float, cfg: WinnersConfig) -> list[dict]:
    lo, hi = move.i - cfg.before_days, move.i + cfg.after_days
    cap = move.start * (1 + cfg.max_entry_premium_pct / 100)
    out = []
    for key, (profile, name, sig) in fired.items():
        first = next((i for i in sig.index[sig & (sig.index >= lo) & (sig.index <= hi)] if entry[i] <= cap), None)
        if first is not None:
            out.append({"key": key, "profile": profile, "strategy": name, "date": g.at[first, "date"].strftime("%Y-%m-%d"),
                        "days_from_start": int(first - move.i), "gain_left_pct": (peak / entry[first] - 1) * 100})
    return sorted(out, key=lambda c: c["days_from_start"])


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) or not np.isfinite(v) else float(v)


# --- stored scan ---------------------------------------------------------------

def latest(db: Database, settings: Settings, force: bool = False) -> dict:
    """The stored scan if it is current (same last price date and profiles), otherwise a fresh one, stored."""
    profiles = [load_profile(n) for n in list_profiles(settings)]
    as_of, config = db.date_range()[1], _config_hash(profiles)
    with _build_lock:                       # the API may get several requests while a build runs
        stored = None if force else db.load_moves_scan()
        if stored and stored[0] == as_of and stored[1] == config:
            return stored[2]
        log.info("Building the big moves scan for prices up to %s", as_of)
        codes = sorted({c for p in profiles for c in universe_codes(p.universe, db)})
        res = scan(profiles, engine.load_adjusted_prices(db, settings, codes),
                   quality_metrics.compute_quality_metrics(db, codes))
        payload = to_payload(res, db.load_companies(codes), [p.name for p in profiles])
        db.save_moves_scan(as_of, config, payload)
        return payload


def to_payload(res: MovesScan, companies: pd.DataFrame, profiles: list[str]) -> dict:
    """JSON-safe dict for the dashboard: dates as YYYY-MM-DD, NaN as null, numbers rounded."""
    comp = companies.set_index("code") if len(companies) else pd.DataFrame()
    codes = sorted(set(res.moves["code"]) | set(res.signals["code"]) | set(comp.index))
    stocks = {}
    for c in codes:
        r = comp.loc[c] if c in comp.index else {}
        stocks[c] = {"name": _str(r.get("name")) or c, "sector": _str(r.get("sector")),
                     "category": _str(r.get("category")), "quality": [p for p in profiles if c in res.quality.get(p, ())]}
    moves = [{**m, "date": m["date"].strftime("%Y-%m-%d"), "peak_date": m["peak_date"].strftime("%Y-%m-%d"),
              "start": round(m["start"], 2), "peak": round(m["peak"], 2), "peak_gain_pct": round(m["peak_gain_pct"], 1),
              "avg_value_mn_60": _round(m["avg_value_mn_60"]),
              "caught_by": [{**c, "gain_left_pct": round(c["gain_left_pct"], 1)} for c in m["caught_by"]]}
             for m in res.moves.to_dict("records")]
    signals = [{**s, "date": s["date"].strftime("%Y-%m-%d"), "score": round(s["score"], 1), "close": round(s["close"], 2),
                **{k: _round(s[k]) for k in ("ret", "best", "to_last", "avg_value_mn_60")}}
               for s in res.signals.sort_values(["date", "code"], ascending=[False, True]).to_dict("records")]
    return {
        "as_of": res.end.strftime("%Y-%m-%d"), "from": res.start.strftime("%Y-%m-%d"),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "winners": res.winners.model_dump(), "horizon": res.horizon, "profiles": profiles,
        "strategies": {name: cls.title for name, cls in REGISTRY.items()},
        "stocks": stocks, "moves": moves, "signals": signals,
    }


def _config_hash(profiles: list[Profile]) -> str:
    return hashlib.sha1("".join(p.model_dump_json() for p in profiles).encode()).hexdigest()[:12]


def _round(v, digits: int = 1) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), digits)


def _str(v) -> str:
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)

