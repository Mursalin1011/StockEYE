"""S1: the owner's method. Price is stable, volume rises, and volume grows much
faster than price (someone is buying without pushing the price up)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy, StrategyParams, scale, window_ratio


class Params(StrategyParams):
    price_window_days: int = 60          # stability is judged over this window
    max_price_range_pct: float = 15.0    # (highest close / lowest close - 1) over the window
    vol_short_days: int = 20             # "recent" volume
    vol_baseline_days: int = 60          # compared with the days before that
    min_volume_ratio: float = 1.5        # recent avg volume / baseline avg volume
    min_price_change_pct: float = -2.0   # recent avg price vs baseline: a falling price on high volume may be selling...
    max_price_change_pct: float = 8.0    # ...and not already running up
    min_divergence: float = 3.0          # volume growth % / |price change %|
    price_change_floor_pct: float = 2.0  # |price change| below this counts as this (avoids /0)
    min_avg_value_mn: float = 2.0        # liquidity: avg daily traded value, BDT mn
    # Divide the stock's volume ratio by the whole market's (traded value), so a market-wide
    # surge doesn't look like accumulation in every stock at once
    market_relative: bool = False
    # Score is 0 at the minimum thresholds above and full at these "strong" levels
    strong_volume_ratio: float = 3.0
    strong_divergence: float = 10.0
    tight_range_pct: float = 6.0


class QuietAccumulation(Strategy):
    name = "quiet_accumulation"
    title = "Quiet accumulation"
    Params = Params

    @property
    def min_history(self) -> int:
        return max(self.p.price_window_days, self.p.vol_short_days + self.p.vol_baseline_days)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        close, vol = df["close"], df["volume"].astype(float)
        s, b = p.vol_short_days, p.vol_baseline_days

        out = pd.DataFrame(index=df.index)
        out["raw_volume_ratio"] = window_ratio(vol, s, b)
        if p.market_relative and "mkt_value_mn" in df:
            out["market_ratio"] = window_ratio(df["mkt_value_mn"].astype(float), s, b)
            out["volume_ratio"] = out["raw_volume_ratio"] / out["market_ratio"]
        else:
            out["market_ratio"] = np.nan
            out["volume_ratio"] = out["raw_volume_ratio"]
        out["price_change_pct"] = (window_ratio(close, s, b) - 1) * 100
        w = p.price_window_days
        out["range_pct"] = (close.rolling(w).max() / close.rolling(w).min() - 1) * 100
        vol_growth_pct = (out["volume_ratio"] - 1) * 100
        out["divergence"] = vol_growth_pct / out["price_change_pct"].abs().clip(lower=p.price_change_floor_pct)
        out["avg_value_mn"] = df["value_mn"].rolling(s).mean()
        obv = (np.sign(close.diff()).fillna(0) * vol).cumsum()
        out["obv_rising"] = obv > obv.shift(s)

        out["signal"] = (
            (out["volume_ratio"] >= p.min_volume_ratio)
            & (out["range_pct"] <= p.max_price_range_pct)
            & out["price_change_pct"].between(p.min_price_change_pct, p.max_price_change_pct)
            & (out["divergence"] >= p.min_divergence)
            & (out["avg_value_mn"] >= p.min_avg_value_mn)
        )
        out["score"] = (
            40 * scale(out["volume_ratio"], p.min_volume_ratio, p.strong_volume_ratio)
            + 30 * scale(out["divergence"], p.min_divergence, p.strong_divergence)
            + 20 * (1 - scale(out["range_pct"], p.tight_range_pct, p.max_price_range_pct))
            + 10 * out["obv_rising"].astype(float)
        ).where(out["signal"], 0.0)
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        p = self.p
        if pd.notna(row.market_ratio):
            vol_line = (f"Volume {row.raw_volume_ratio:.1f}x its prior {p.vol_baseline_days}-day average "
                        f"(last {p.vol_short_days} days) while the market did {row.market_ratio:.1f}x: "
                        f"{row.volume_ratio:.1f}x relative")
        else:
            vol_line = (f"Volume {row.volume_ratio:.1f}x its prior {p.vol_baseline_days}-day average "
                        f"(last {p.vol_short_days} days)")
        r = [
            vol_line,
            f"Price {row.price_change_pct:+.1f}% over the same period, "
            f"{row.range_pct:.0f}% range over {p.price_window_days} days",
            f"Volume grew {row.divergence:.0f}x more than price",
        ]
        if row.obv_rising:
            r.append("On-balance volume rising (more volume on up days)")
        return r
