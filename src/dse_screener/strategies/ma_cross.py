"""S5: moving-average cross in an uptrend, with volume support (docs/06 §13).

Default = the 20/50 "golden cross": MA20 crosses above MA50, the close is above MA50, and the last
10 days' average volume is above the 50-day average. With fast 10 / slow 20 / trend_ma 50 it is the
faster 10/20 cross inside an uptrend (MA20 > MA50, close > MA50), which the 2-year check found no edge in.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy, StrategyParams, scale


class Params(StrategyParams):
    fast: int = 20                      # fast moving average (days)
    slow: int = 50                      # slow moving average: the signal is the fast one crossing above it
    trend_ma: int | None = None         # also require slow MA > this MA and close > it (e.g. 50 for a 10/20 cross)
    require_close_above_slow: bool = True
    # Volume support: average volume of the last vol_short_days / of the last vol_baseline_days, on the cross day.
    # Must be above min_volume_ratio. None = off.
    vol_short_days: int = 10
    vol_baseline_days: int = 50
    min_volume_ratio: float | None = 1.0
    max_days_since: int = 2             # keep showing the signal this many days after the cross, while the fast MA
                                        # stays above the slow one and the close above the slow MA
    # Score points (sum 100): any valid cross, volume above its baseline, close near the slow MA (not extended)
    base_points: float = 50.0
    volume_points: float = 25.0
    strong_volume_ratio: float = 2.0    # full volume points at this ratio
    near_points: float = 25.0
    max_extension_pct: float = 10.0     # no "near" points once the close is this % above the slow MA
    recency_penalty: float = 5.0        # score points lost per day since the cross
    # Watch list: fast MA below the slow one by at most this %, and rising over watch_rising_days
    watch_gap_pct: float = 1.5
    watch_rising_days: int = 5


class MaCross(Strategy):
    name = "ma_cross"
    title = "MA cross"
    Params = Params

    @property
    def min_history(self) -> int:
        # The slow MA exists from row slow - 1, so the first possible cross (needs the day before) is row slow
        return max(self.p.slow, self.p.trend_ma or 0, self.p.vol_baseline_days)

    def _frame(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        close, vol = df["close"].astype(float), df["volume"].astype(float)
        f = pd.DataFrame(index=df.index)
        f["fast_ma"] = close.rolling(p.fast).mean()
        f["slow_ma"] = close.rolling(p.slow).mean()
        f["trend"] = close.rolling(p.trend_ma).mean() if p.trend_ma else np.nan
        f["volume_ratio"] = vol.rolling(p.vol_short_days).mean() / vol.rolling(p.vol_baseline_days).mean()
        f["extension_pct"] = (close / f["slow_ma"] - 1) * 100
        return f

    def _holds(self, f: pd.DataFrame, close: pd.Series) -> pd.Series:
        """The trend part, checked on every signal day: fast above slow (+ close above slow, + uptrend)."""
        p = self.p
        ok = f["fast_ma"] > f["slow_ma"]
        if p.require_close_above_slow:
            ok &= close > f["slow_ma"]
        if p.trend_ma:
            ok &= (f["slow_ma"] > f["trend"]) & (close > f["trend"])
        return ok.fillna(False)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        close = df["close"].astype(float)
        f = self._frame(df)
        holds = self._holds(f, close)
        crossed = (f["fast_ma"] > f["slow_ma"]) & (f["fast_ma"].shift() <= f["slow_ma"].shift())
        cross = (crossed & holds).fillna(False)
        if p.min_volume_ratio is not None:
            cross &= (f["volume_ratio"] > p.min_volume_ratio).fillna(False)
        day_score = (p.base_points
                     + p.volume_points * scale(f["volume_ratio"].fillna(1.0), 1.0, p.strong_volume_ratio))

        out = pd.DataFrame(index=df.index)
        out["signal"] = False
        out["score"] = 0.0
        shown = ["fast_ma", "slow_ma", "volume_ratio", "extension_pct"]
        for col in ["days_since", "cross_volume_ratio", *shown]:
            out[col] = np.nan
        # Most recent cross wins: fill from k = max_days_since down to 0
        for k in range(p.max_days_since, -1, -1):
            hit = cross.shift(k, fill_value=False) & holds
            out.loc[hit, "signal"] = True
            out.loc[hit, "days_since"] = k
            out.loc[hit, "cross_volume_ratio"] = f["volume_ratio"].shift(k)[hit]
            for col in shown:
                out.loc[hit, col] = f[col][hit]
            near = p.near_points * (1 - scale(f["extension_pct"], 0.0, p.max_extension_pct))
            out.loc[hit, "score"] = (day_score.shift(k)[hit] + near[hit] - p.recency_penalty * k).clip(lower=0)
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        p = self.p
        k = int(row.days_since)
        when = "today" if k == 0 else f"{k} day(s) ago"
        out = [f"MA{p.fast} crossed above MA{p.slow} {when} (MA{p.fast} {row.fast_ma:.1f}, MA{p.slow} {row.slow_ma:.1f})",
               f"Close {row.extension_pct:+.1f}% vs MA{p.slow}"
               + (f", in an uptrend (MA{p.slow} above MA{p.trend_ma})" if p.trend_ma else "")]
        if pd.notna(row.get("cross_volume_ratio")):
            out.append(f"Volume support: {p.vol_short_days}-day average volume {row.cross_volume_ratio:.2f}x "
                       f"the {p.vol_baseline_days}-day average on the cross day")
        return out

    def watch(self, df: pd.DataFrame) -> dict | None:
        """A cross that could come soon: fast MA just below the slow one and rising, close above the slow MA."""
        p = self.p
        if len(df) < self.min_history + p.watch_rising_days:
            return None
        close = df["close"].astype(float)
        f = self._frame(df)
        last = f.iloc[-1]
        gap = (last["fast_ma"] / last["slow_ma"] - 1) * 100
        rising = last["fast_ma"] > f["fast_ma"].iloc[-1 - p.watch_rising_days]
        if not (-p.watch_gap_pct <= gap < 0 and rising and close.iloc[-1] > last["slow_ma"]):
            return None
        if p.trend_ma and not (last["slow_ma"] > last["trend"] and close.iloc[-1] > last["trend"]):
            return None
        return {"gap_pct": gap, "fast_ma": last["fast_ma"], "slow_ma": last["slow_ma"],
                "volume_ratio": last["volume_ratio"], "close": close.iloc[-1]}

    def watch_reasons(self, w: dict) -> list[str]:
        p = self.p
        vol = "" if p.min_volume_ratio is None else (
            f"; volume {w['volume_ratio']:.2f}x its {p.vol_baseline_days}-day average "
            f"(needs > {p.min_volume_ratio:g}x)")
        return [f"MA{p.fast} {w['fast_ma']:.1f} is {abs(w['gap_pct']):.1f}% below MA{p.slow} {w['slow_ma']:.1f} "
                f"and rising: a cross is close",
                f"Close {w['close']:.1f} is above MA{p.slow}{vol}"]
