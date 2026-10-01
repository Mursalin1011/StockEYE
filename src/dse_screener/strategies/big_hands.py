"""S3: fewer but larger trades. Average traded value per trade rises while the
price hasn't moved much yet, which suggests larger players are involved.

Uses DSE's trade count, which many markets don't publish. Value per trade is in
BDT actually traded, so it needs no corporate-action adjustment.
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy, StrategyParams, scale, window_ratio


class Params(StrategyParams):
    short_days: int = 20
    baseline_days: int = 60
    min_trade_size_growth: float = 1.3   # avg BDT per trade, recent / baseline
    min_avg_trades: float = 100          # ignore thinly traded stocks (noisy)
    max_price_change_pct: float = 10.0   # price change over the short window: still early
    min_price_change_pct: float = -8.0
    strong_trade_size_growth: float = 2.5


class BigHands(Strategy):
    name = "big_hands"
    title = "Big hands (larger trades)"
    Params = Params

    @property
    def min_history(self) -> int:
        return self.p.short_days + self.p.baseline_days

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        s, b = p.short_days, p.baseline_days
        value, trades = df["value_mn"] * 1e6, df["trades"].astype(float)

        out = pd.DataFrame(index=df.index)
        size_short = value.rolling(s).sum() / trades.rolling(s).sum()
        size_base = value.shift(s).rolling(b).sum() / trades.shift(s).rolling(b).sum()
        out["trade_size_bdt"] = size_short
        out["trade_size_growth"] = size_short / size_base
        out["avg_trades"] = trades.rolling(s).mean()
        out["price_change_pct"] = (df["close"] / df["close"].shift(s) - 1) * 100
        out["volume_ratio"] = window_ratio(df["volume"].astype(float), s, b)

        out["signal"] = (
            (out["trade_size_growth"] >= p.min_trade_size_growth)
            & (out["avg_trades"] >= p.min_avg_trades)
            & out["price_change_pct"].between(p.min_price_change_pct, p.max_price_change_pct)
        )
        out["score"] = (
            70 * scale(out["trade_size_growth"], p.min_trade_size_growth, p.strong_trade_size_growth)
            + 30 * scale(out["volume_ratio"], 1.0, 2.0)
        ).where(out["signal"], 0.0)
        return out

    def reasons(self, row: pd.Series) -> list[str]:
        return [
            f"Average trade size {row.trade_size_growth:.1f}x its prior {self.p.baseline_days}-day level "
            f"(now ~BDT {row.trade_size_bdt / 1000:,.0f}k per trade)",
            f"Price {row.price_change_pct:+.1f}% over {self.p.short_days} days, "
            f"volume {row.volume_ratio:.1f}x baseline",
        ]
