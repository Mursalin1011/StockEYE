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
        return self.p.base_days + 1

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        close = df["close"]
        b = breakout_days(df, p.base_days, p.max_base_range_pct, p.min_breakout_pct, p.min_volume_x)
        base_high, base_range, volume_x, breakout_pct, is_breakout = (
            b["base_high"], b["base_range_pct"], b["volume_x"], b["breakout_pct"], b["is_breakout"]
        )
        day_score = (
            50 * scale(volume_x, p.min_volume_x, p.strong_volume_x)
            + 30 * (1 - scale(base_range, p.tight_base_pct, p.max_base_range_pct))
            + 20 * scale(breakout_pct, p.min_breakout_pct, p.strong_breakout_pct)
        )

        out = pd.DataFrame(index=df.index)
        out["signal"] = False
        out["score"] = 0.0
        for col in ["days_since", "base_range_pct", "volume_x", "breakout_pct", "base_high"]:
            out[col] = np.nan
        # Most recent breakout wins: fill from k = max_days_since down to 0
        for k in range(p.max_days_since, -1, -1):
            hit = is_breakout.shift(k, fill_value=False) & (close >= base_high.shift(k))
            out.loc[hit, "signal"] = True
            out.loc[hit, "days_since"] = k
            out.loc[hit, "base_range_pct"] = base_range.shift(k)[hit]
            out.loc[hit, "volume_x"] = volume_x.shift(k)[hit]
            out.loc[hit, "breakout_pct"] = breakout_pct.shift(k)[hit]
            out.loc[hit, "base_high"] = base_high.shift(k)[hit]
            out.loc[hit, "score"] = (day_score.shift(k)[hit] - p.recency_penalty * k).clip(lower=0)
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        when = "today" if row.days_since == 0 else f"{int(row.days_since)} day(s) ago"
        return [
            f"Broke out of a {self.p.base_days}-day base {when} "
            f"(base range {row.base_range_pct:.0f}%, high {row.base_high:.1f})",
            f"Breakout volume {row.volume_x:.1f}x the base average, close {row.breakout_pct:+.1f}% above the base",
        ]
