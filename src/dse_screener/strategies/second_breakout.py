"""S4: re-entry after a shakeout. A base breakout fails (the close falls back into the
base), the base holds, and then the stock clears the failed breakout's high on strong
volume. On DSE the first breakout often shakes out weak holders; the second one is
frequently where the real move starts (PTL: first breakout 25 Feb 2026, shakeout in
March, second breakout 12 Apr, then +40% by September)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy, StrategyParams, scale
from .base_breakout import breakout_days


class Params(StrategyParams):
    # The first breakout: same definition as base_breakout (set these equal to its params)
    base_days: int = 25
    max_base_range_pct: float = 10.0
    min_breakout_pct: float = 1.0
    min_volume_x: float = 2.0
    # The shakeout
    fail_below_pivot_pct: float = 0.0   # failed = close this far below the old base high (0 = any close back in the base)
    max_undercut_pct: float = 5.0       # cancel if the shakeout closes this far below the base low (the base broke)
    # The second breakout
    window_days: int = 40               # must come within this many trading days of the first breakout
    min_rebreak_pct: float = 1.0        # close must clear the failed breakout's highest close by this much
    min_rebreak_volume_x: float = 2.0   # re-break volume vs the average of the prior `base_days`
    max_days_since: int = 3             # keep showing the signal this many days, while the close stays above that high
    # Score is 0 at the minimums and full at these levels
    strong_volume_x: float = 5.0
    strong_rebreak_pct: float = 5.0
    deep_shakeout_pct: float = 10.0     # shakeout this far below the old base high scores 0 for "held"
    recency_penalty: float = 5.0        # score points lost per day since the second breakout


class SecondBreakout(Strategy):
    name = "second_breakout"
    title = "Second breakout"
    Params = Params

    @property
    def min_history(self) -> int:
        return self.p.base_days + 1

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        b = breakout_days(df, p.base_days, p.max_base_range_pct, p.min_breakout_pct, p.min_volume_x)
        close = df["close"].to_numpy(dtype=float)
        volume_x = b["volume_x"].to_numpy(dtype=float)
        is_breakout = b["is_breakout"].to_numpy(dtype=bool)
        base_high, base_low = b["base_high"].to_numpy(dtype=float), b["base_low"].to_numpy(dtype=float)

        # Walk forward through time, one breakout setup at a time (only past rows are used)
        events, setup = [], None
        for i in range(len(df)):
            c = close[i]
            if setup is not None and i - setup["start"] > p.window_days:
                setup = None
            if setup is not None and np.isfinite(c):
                if not setup["failed"]:
                    if c < setup["pivot"] * (1 - p.fail_below_pivot_pct / 100):
                        setup["failed"], setup["shake_low"] = True, c
                    else:
                        setup["peak"] = max(setup["peak"], c)
                else:
                    setup["shake_low"] = min(setup["shake_low"], c)
                    if setup["shake_low"] < setup["base_low"] * (1 - p.max_undercut_pct / 100):
                        setup = None
                    elif (c >= setup["peak"] * (1 + p.min_rebreak_pct / 100)
                          and volume_x[i] >= p.min_rebreak_volume_x):
                        events.append({**setup, "i": i, "volume_x": volume_x[i]})
                        setup = None
            if setup is None and is_breakout[i]:
                setup = {"start": i, "pivot": base_high[i], "base_low": base_low[i], "peak": c,
                         "failed": False, "shake_low": np.nan}

        out = pd.DataFrame(index=df.index)
        out["signal"] = False
        out["score"] = 0.0
        out["first_date"] = pd.NaT
        for col in ["days_since", "days_from_first", "pivot", "failed_high", "shake_low_pct",
                    "volume_x", "rebreak_pct"]:
            out[col] = np.nan
        dates = df["date"] if "date" in df else pd.Series(pd.NaT, index=df.index)
        idx = df.index
        for e in events:   # later events overwrite earlier ones: the most recent wins
            i, peak = e["i"], e["peak"]
            rebreak_pct = (close[i] / peak - 1) * 100
            shake_low_pct = (e["shake_low"] / e["pivot"] - 1) * 100
            day_score = (
                50 * scale(e["volume_x"], p.min_rebreak_volume_x, p.strong_volume_x)
                + 30 * (1 - scale(-shake_low_pct, 0, p.deep_shakeout_pct))
                + 20 * scale(rebreak_pct, p.min_rebreak_pct, p.strong_rebreak_pct)
            )
            for k in range(p.max_days_since + 1):
                j = i + k
                if j >= len(df) or not close[j] >= peak:
                    break
                values = {
                    "signal": True, "score": max(day_score - p.recency_penalty * k, 0.0),
                    "first_date": dates.iloc[e["start"]], "days_since": k, "days_from_first": i - e["start"],
                    "pivot": e["pivot"], "failed_high": peak, "shake_low_pct": shake_low_pct,
                    "volume_x": e["volume_x"], "rebreak_pct": rebreak_pct,
                }
                for col, v in values.items():
                    out.at[idx[j], col] = v
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        when = "today" if row.days_since == 0 else f"{int(row.days_since)} day(s) ago"
        first = f"on {row.first_date:%d %b}" if pd.notna(row.first_date) else \
            f"{int(row.days_from_first)} trading days earlier"
        return [
            f"First breakout {first} failed: fell back to {row.shake_low_pct:+.1f}% vs the old base high "
            f"{row.pivot:.1f}, but the base held",
            f"Broke above that breakout's high ({row.failed_high:.1f}) {when} "
            f"on {row.volume_x:.1f}x volume, close {row.rebreak_pct:+.1f}% above it",
        ]
