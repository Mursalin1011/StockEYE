"""Prediction ledger: every AI stock call is stored, then scored once its horizon has passed.

Scoring matches the backtest: buy at the next day's open after the review's as_of day, sell at the
close `horizon` trading days later, 1% round-trip cost, compared with the equal-weight basket of
quality stocks (swing profile filter) over the same dates. Bullish is right if it beats the basket,
bearish if it lags it. Neutral calls are not scored.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .. import engine, quality, rules
from ..backtest import forward_returns
from ..config import Settings, load_profile
from ..db import Database
from ..universes import universe_codes

COST_PCT = 1.0
BUCKETS = [(50, 60, "50-59"), (60, 70, "60-69"), (70, 101, "70+")]


def save_calls(db: Database, review_id: int, as_of: str, calls: list[dict]) -> None:
    with db.conn:
        db.conn.executemany(
            "INSERT INTO ai_calls (review_id, as_of, code, stance, horizon_days, confidence, thesis) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(review_id, as_of, c["code"], c["stance"], c["horizon_days"], c["confidence"], c["thesis"]) for c in calls],
        )


def load_calls(db: Database) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM ai_calls ORDER BY as_of DESC, id DESC", db.conn)


def quality_basket(db: Database, profile_name: str = "swing") -> list[str]:
    profile = load_profile(profile_name)
    universe = universe_codes(profile.universe, db)
    qf = profile.filters.get("quality")
    q = rules.evaluate(quality.compute_quality_metrics(db, universe), qf.rules if qf and qf.enabled else {})
    return q.index[q["passed"]].tolist()


def score_calls(db: Database, settings: Settings, basket: list[str] | None = None) -> int:
    """Score every call whose horizon has passed. Returns how many were scored.
    basket: benchmark stocks (default: today's swing quality list)."""
    calls = load_calls(db)
    todo = calls[calls["scored_at"].isna() & (calls["stance"] != "neutral")]
    if todo.empty:
        return 0
    basket = basket if basket is not None else quality_basket(db)
    codes = sorted(set(basket) | set(todo["code"]))
    prices = engine.load_adjusted_prices(db, settings, codes)
    horizons = sorted(todo["horizon_days"].astype(int).unique())
    fwd = []
    for code, g in prices.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        f = forward_returns(g, horizons, COST_PCT)
        f["date"], f["code"], f["traded"] = g["date"], code, g["volume"].fillna(0) > 0
        fwd.append(f)
    fwd = pd.concat(fwd, ignore_index=True)
    bench = fwd[fwd["traded"] & fwd["code"].isin(basket)].groupby("date")[[f"ret_{h}" for h in horizons]].mean()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    with db.conn:
        for c in todo.itertuples():
            day, h = pd.Timestamp(c.as_of), int(c.horizon_days)
            row = fwd[(fwd["code"] == c.code) & (fwd["date"] == day)]
            if row.empty or pd.isna(row[f"ret_{h}"].iloc[0]) or day not in bench.index:
                continue                      # horizon not over yet (or no price that day)
            ret, b = float(row[f"ret_{h}"].iloc[0]), float(bench.at[day, f"ret_{h}"])
            excess = ret - b
            correct = int(excess > 0) if c.stance == "bullish" else int(excess < 0)
            db.conn.execute("UPDATE ai_calls SET ret=?, bench=?, excess=?, correct=?, scored_at=? WHERE id=?",
                            (ret, b, excess, correct, now, int(c.id)))
            n += 1
    return n


def track_record(db: Database) -> dict:
    """Summary the analyst sees next time: hit rate overall and per confidence bucket."""
    calls = load_calls(db)
    scored = calls[calls["correct"].notna()]
    out = {"calls_made": int(len(calls)), "calls_scored": int(len(scored))}
    if scored.empty:
        out["note"] = "No calls scored yet."
        return out
    out["hit_rate_pct"] = round(scored["correct"].mean() * 100, 1)
    out["avg_excess_vs_basket_pct"] = round(scored["excess"].mean(), 2)
    out["by_confidence"] = []
    for lo, hi, label in BUCKETS:
        b = scored[(scored["confidence"] >= lo) & (scored["confidence"] < hi)]
        if len(b):
            out["by_confidence"].append({"bucket": label, "calls": int(len(b)),
                                         "hit_rate_pct": round(b["correct"].mean() * 100, 1),
                                         "avg_confidence": round(b["confidence"].mean(), 1)})
    out["by_stance"] = {s: {"calls": int(len(g)), "hit_rate_pct": round(g["correct"].mean() * 100, 1)}
                        for s, g in scored.groupby("stance")}
    return out


def calibration_table(db: Database) -> pd.DataFrame:
    calls = load_calls(db)
    scored = calls[calls["correct"].notna()]
    rows = []
    for lo, hi, label in BUCKETS:
        b = scored[(scored["confidence"] >= lo) & (scored["confidence"] < hi)]
        rows.append({"confidence": label, "calls": len(b),
                     "expected_hit_pct": b["confidence"].mean() if len(b) else np.nan,
                     "actual_hit_pct": b["correct"].mean() * 100 if len(b) else np.nan,
                     "avg_excess_pct": b["excess"].mean() if len(b) else np.nan})
    return pd.DataFrame(rows)
