"""Run a profile: quality filter -> strategies -> ranked, explained shortlist."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import quality, rules, technical
from .adjust import apply_adjustments
from .config import Profile, Settings, StrategyConfig
from .db import Database
from .strategies import REGISTRY, Strategy
from .universes import universe_codes

SIGNAL_COLUMNS = ["code", "strategy", "title", "role", "score", "weighted", "reasons", "metrics"]


@dataclass
class ScreenResult:
    profile: str
    as_of: date
    universe_size: int
    picks: pd.DataFrame                 # ranked shortlist: code, final_score, strategies, reasons
    signals: pd.DataFrame               # every strategy hit: code, strategy, score, weighted, reasons, metrics
    excluded: pd.DataFrame              # quality failures: code, failures
    skipped: list[str] = field(default_factory=list)  # no trading on as_of / not enough history
    technical_excluded: dict[str, list[str]] = field(default_factory=dict)  # had signals, failed RSI/MACD rules


def build_strategies(profile: Profile) -> list[tuple[Strategy, StrategyConfig]]:
    out = []
    for name, cfg in profile.strategies.items():
        if name not in REGISTRY:
            raise ValueError(f"Profile '{profile.name}': unknown strategy '{name}'. Known: {sorted(REGISTRY)}")
        if cfg.enabled:
            out.append((REGISTRY[name](cfg.params), cfg))
    return out


def load_adjusted_prices(db: Database, settings: Settings, codes: list[str]) -> pd.DataFrame:
    prices = apply_adjustments(
        db.load_prices(codes), db.load_corporate_actions(codes), settings.adjustments.adjust_cash_dividends
    )
    prices["close"] = prices.groupby("code")["close"].ffill()
    # Whole-market traded value per day, so strategies can tell stock-specific volume from market-wide surges
    return prices.merge(db.market_totals()[["date", "mkt_value_mn"]], on="date", how="left")


def evaluate_profile(
    profile: Profile,
    prices: pd.DataFrame,
    metrics: pd.DataFrame,
    as_of: date,
    actions: pd.DataFrame | None = None,
) -> ScreenResult:
    """Pure function: no I/O, uses only rows dated <= as_of. Reused by the backtest.

    `actions` (corporate actions) only feeds the record-date penalty; record dates
    are announced weeks ahead, so using upcoming ones is not lookahead.
    """
    qf = profile.filters.get("quality")
    q = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
    passed = q.index[q["passed"]].tolist()
    excluded = q.loc[~q["passed"], ["failures"]].reset_index()

    strategies = build_strategies(profile)
    tf_cfg = profile.filters.get("technical")
    as_of_ts = pd.Timestamp(as_of)
    signals, skipped, tech_notes, tech_excluded = [], [], {}, {}
    upto = prices[prices["date"] <= as_of_ts]
    by_code = {c: g for c, g in upto.groupby("code", sort=False)}   # one pass, not one scan per stock
    for code in passed:
        g = by_code.get(code)
        g = g.reset_index(drop=True) if g is not None else pd.DataFrame(columns=prices.columns)
        if g.empty or g["date"].iloc[-1] != as_of_ts or not g["volume"].iloc[-1]:
            skipped.append(code)
            continue
        tech = technical.technical_frame(g, tf_cfg.params if tf_cfg else None).iloc[-1]
        tech_notes[code] = technical.describe(tech)
        n_before = len(signals)
        for strat, cfg in strategies:
            if len(g) < strat.min_history:
                continue
            row = strat.compute(g).iloc[-1]
            if bool(row["signal"]):
                signals.append({
                    "code": code,
                    "strategy": strat.name,
                    "title": strat.title,
                    "role": cfg.role,
                    "score": float(row["score"]),
                    "weighted": float(row["score"]) * cfg.weight,
                    "reasons": strat.reasons(row),
                    "metrics": {k: _plain(v) for k, v in row.items() if k not in ("signal", "score")},
                })
        # Technical filter (RSI/MACD) on the signal day: drop this stock's signals if it fails
        if tf_cfg and tf_cfg.enabled and len(signals) > n_before:
            failures = [f"{k}: {why}" for k, rule in tf_cfg.rules.items() if (why := rule.check(tech.get(k))) is not None]
            if failures:
                tech_excluded[code] = failures
                del signals[n_before:]
    sig = pd.DataFrame(signals, columns=SIGNAL_COLUMNS)
    picks = rank(sig, metrics, profile, _record_dates_near(actions, as_of, profile.ranking.record_date_window_days),
                 tech_notes)
    return ScreenResult(profile.name, as_of, len(metrics), picks, sig, excluded, skipped, tech_excluded)


def _record_dates_near(actions: pd.DataFrame | None, as_of: date, days: int) -> dict[str, date]:
    if actions is None or actions.empty or days <= 0:
        return {}
    rec = pd.to_datetime(actions["record_date"])
    near = actions[(rec - pd.Timestamp(as_of)).abs() <= pd.Timedelta(days=days)]
    return {r.code: pd.Timestamp(r.record_date).date() for r in near.itertuples()}


def rank(
    signals: pd.DataFrame,
    metrics: pd.DataFrame,
    profile: Profile,
    record_dates: dict[str, date] | None = None,
    tech_notes: dict[str, str] | None = None,
) -> pd.DataFrame:
    r = profile.ranking
    rows = []
    for code, g in signals.groupby("code"):
        primary = g[g["role"] == "primary"].sort_values("weighted", ascending=False)
        if primary.empty:
            continue  # only confirming strategies fired: not enough on their own
        g = pd.concat([primary, g[g["role"] != "primary"]])
        score = primary["weighted"].iloc[0] + r.confluence_bonus * (len(g) - 1)
        reasons = [
            f"{s.title} ({s.score:.0f}{', confirming' if s.role != 'primary' else ''}): " + "; ".join(s.reasons)
            for s in g.itertuples()
        ]
        if len(g) > 1:
            reasons.append(f"+{r.confluence_bonus * (len(g) - 1):.0f} confluence: {len(g)} strategies agree")
        m = metrics.loc[code] if code in metrics.index else pd.Series(dtype=object)
        for b in r.boosts:
            value = m.get(b.metric)
            if b.when.check(value) is None:
                score += b.points
                detail = b.detail.format(value=value) if b.detail else f"{b.metric} = {_fmt(value)}"
                reasons.append(f"+{b.points:.0f} {b.label} ({detail})")
        if record_dates and code in record_dates:
            score -= r.record_date_penalty
            prefix = f"-{r.record_date_penalty:.0f}" if r.record_date_penalty else "Note:"
            reasons.append(f"{prefix} record date {record_dates[code]:%d %b}: volume may be dividend-driven")
        if tech_notes and tech_notes.get(code):
            reasons.append(f"Tech: {tech_notes[code]}")
        rows.append({"code": code, "final_score": round(score, 1), "strategies": g["strategy"].tolist(),
                     "reasons": reasons})
    picks = pd.DataFrame(rows, columns=["code", "final_score", "strategies", "reasons"])
    picks = picks[picks["final_score"] >= r.min_score].sort_values("final_score", ascending=False)
    return picks.head(r.top_n).reset_index(drop=True)


def run_profile(db: Database, settings: Settings, profile: Profile, as_of: date | None = None) -> ScreenResult:
    codes = universe_codes(profile.universe, db)
    prices = load_adjusted_prices(db, settings, codes)
    as_of = as_of or prices["date"].max().date()
    metrics = quality.compute_quality_metrics(db, codes)
    return evaluate_profile(profile, prices, metrics, as_of, db.load_corporate_actions(codes))


def _plain(v):
    """numpy/pandas scalars -> JSON-friendly Python values."""
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    try:
        return None if pd.isna(v) else v.item()
    except (AttributeError, ValueError):
        return str(v)


def _fmt(v) -> str:
    return f"{v:,.1f}" if isinstance(v, float) else str(v)
