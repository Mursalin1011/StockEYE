"""S2: the 'it's starting' moment. Close breaks above a long, tight range on high
volume. Often what follows quiet accumulation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy, StrategyParams, scale


class Params(StrategyParams):
    base_days: int = 40                 # length of the flat base before the breakout
    max_base_range_pct: float = 12.0    # base must be this tight (highest/lowest close - 1)
    min_breakout_pct: float = 1.0       # close must clear the base high by this much
    min_volume_x: float = 2.0           # breakout-day volume vs the base's average volume
    max_days_since: int = 3             # keep showing the signal this many days after the breakout...
    # ...as long as the close is still above the old base high
    strong_volume_x: float = 5.0
    tight_base_pct: float = 5.0
    strong_breakout_pct: float = 5.0
    recency_penalty: float = 5.0        # score points lost per day since the breakout
    # Optional (W5). Volume dry-up: in the `dryup_days` before the breakout, average volume must be at most
    # `max_dryup_ratio` x the `dryup_baseline_days` before that (sellers exhausted, like PTL's base). None = off.
    max_dryup_ratio: float | None = None
    dryup_days: int = 10
    dryup_baseline_days: int = 50
    # Optional (W5). Follow-through: signal only once the close has stayed above the old base high on
    # `follow_through_closes` of the `follow_through_days` days after the breakout. 0 = off (signal on the day).
    follow_through_days: int = 0
    follow_through_closes: int = 2
    # Optional (W9, docs/06 §11-12). Don't chase: signal only while the close is at most this % above the base high
    # (checked on each signal day, so a breakout that runs away drops out). None = off.
    max_extension_pct: float | None = None
    # Score points (keep the sum at 100 so the shortlist's min_score still means the same): breakout-day volume,
    # tight base, breakout size, and closeness to the base high on the signal day (1 at the base high, 0 at
    # strong_breakout_pct above it). Defaults = the original score.
    volume_points: float = 50.0
    tight_points: float = 30.0
    breakout_points: float = 20.0
    near_base_points: float = 0.0


def breakout_days(df: pd.DataFrame, base_days: int, max_base_range_pct: float,
                  min_breakout_pct: float, min_volume_x: float) -> pd.DataFrame:
    """Per day: the prior `base_days` base (high, low, range), volume vs the base average,
    and whether the close broke out of a tight base on high volume. Backward-looking only."""
    close, vol = df["close"], df["volume"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["base_high"] = close.shift(1).rolling(base_days).max()
    out["base_low"] = close.shift(1).rolling(base_days).min()
    out["base_range_pct"] = (out["base_high"] / out["base_low"] - 1) * 100
    out["volume_x"] = vol / vol.shift(1).rolling(base_days).mean()
    out["breakout_pct"] = (close / out["base_high"] - 1) * 100
    out["is_breakout"] = (
        (out["breakout_pct"] >= min_breakout_pct)
        & (out["volume_x"] >= min_volume_x)
        & (out["base_range_pct"] <= max_base_range_pct)
    )
    return out


class BaseBreakout(Strategy):
    name = "base_breakout"
    title = "Base breakout"
    Params = Params

    @property
    def min_history(self) -> int:
        dryup = self.p.dryup_days + self.p.dryup_baseline_days if self.p.max_dryup_ratio is not None else 0
        return max(self.p.base_days, dryup) + 1

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        close = df["close"]
        vol = df["volume"].fillna(0).astype(float)
        b = breakout_days(df, p.base_days, p.max_base_range_pct, p.min_breakout_pct, p.min_volume_x)
        b["dryup_ratio"] = (vol.shift(1).rolling(p.dryup_days).mean()
                            / vol.shift(1 + p.dryup_days).rolling(p.dryup_baseline_days).mean())
        is_breakout = b["is_breakout"]
        if p.max_dryup_ratio is not None:
            is_breakout = is_breakout & (b["dryup_ratio"] <= p.max_dryup_ratio)
        b["day_score"] = (
            p.volume_points * scale(b["volume_x"], p.min_volume_x, p.strong_volume_x)
            + p.tight_points * (1 - scale(b["base_range_pct"], p.tight_base_pct, p.max_base_range_pct))
            + p.breakout_points * scale(b["breakout_pct"], p.min_breakout_pct, p.strong_breakout_pct)
        )
        stats = ["base_range_pct", "volume_x", "breakout_pct", "base_high", "dryup_ratio", "day_score"]

        # Events: the breakout day itself, or (follow-through on) the day the breakout is confirmed.
        # Each event carries its breakout's stats; lag = trading days from the breakout to the event.
        ev = b[stats].where(is_breakout)
        ev["event"], ev["lag"] = is_breakout, 0.0
        if p.follow_through_days > 0:
            ev.loc[:, stats + ["lag"]] = np.nan
            ev["event"] = False
            for k in range(p.follow_through_days, 0, -1):      # most recent breakout wins
                pivot = b["base_high"].shift(k)                 # base high of the breakout k days ago
                closes_above = [(close.shift(j) > pivot).astype(int) for j in range(k)]   # days t, t-1, ..., t-k+1
                n_now, n_before = sum(closes_above), sum(closes_above[1:])
                hit = (is_breakout.shift(k, fill_value=False) & (n_now >= p.follow_through_closes)
                       & (n_before < p.follow_through_closes))  # the day it is first confirmed
                ev.loc[hit, "event"] = True
                ev.loc[hit, "lag"] = k
                for col in stats:
                    ev.loc[hit, col] = b[col].shift(k)[hit]

        out = pd.DataFrame(index=df.index)
        out["signal"] = False
        out["score"] = 0.0
        shown = ["lag", "base_range_pct", "volume_x", "breakout_pct", "base_high", "dryup_ratio"]
        for col in ["days_since", "extension_pct", *shown]:
            out[col] = np.nan
        # Keep showing the signal max_days_since days after the event while the close stays above the old
        # base high. Most recent event wins: fill from k = max_days_since down to 0
        for k in range(p.max_days_since, -1, -1):
            shifted = ev.shift(k)
            ext = (close / shifted["base_high"] - 1) * 100            # today's close above the old base high, %
            hit = shifted["event"].fillna(False).astype(bool) & (close >= shifted["base_high"])
            if p.max_extension_pct is not None:
                hit &= ext <= p.max_extension_pct
            out.loc[hit, "signal"] = True
            out.loc[hit, "days_since"] = k
            out.loc[hit, "extension_pct"] = ext[hit]
            for col in shown:
                out.loc[hit, col] = shifted[col][hit]
            near = p.near_base_points * (1 - scale(ext, 0.0, p.strong_breakout_pct))
            out.loc[hit, "score"] = (shifted["day_score"][hit] + near[hit] - p.recency_penalty * k).clip(lower=0)
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        since = int(row.days_since) + (int(row.lag) if pd.notna(row.get("lag")) else 0)
        when = "today" if since == 0 else f"{since} day(s) ago"
        out = [
            f"Broke out of a {self.p.base_days}-day base {when} "
            f"(base range {row.base_range_pct:.0f}%, high {row.base_high:.1f})",
            f"Breakout volume {row.volume_x:.1f}x the base average, close {row.breakout_pct:+.1f}% above the base",
        ]
        if self.p.max_dryup_ratio is not None and pd.notna(row.get("dryup_ratio")):
            out.append(f"Volume dried up before it: {row.dryup_ratio:.2f}x its earlier average")
        if self.p.follow_through_days > 0:
            out.append(f"Confirmed: closed above the base high on {self.p.follow_through_closes} days after the breakout")
        if self.p.max_extension_pct is not None and pd.notna(row.get("extension_pct")):
            out.append(f"Not extended: close {row.extension_pct:.1f}% above the base high "
                       f"(limit {self.p.max_extension_pct:g}%)")
        return out
