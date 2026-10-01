"""Technical metrics for the `technical` filter (RSI, MACD), per stock and date.

Rules in config/profiles/*.yaml (filters.technical.rules) use these names, e.g.
    rsi:              { max: 70 }   # skip overbought
    macd_hist_change: { min: 0 }    # momentum improving
Values on date t use data up to t only, like the strategies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from . import indicators

TECH_METRICS = {
    "rsi": "RSI (Wilder), 0-100; above 70 is usually called overbought",
    "macd_hist": "MACD histogram (MACD line - signal line); > 0 = bullish momentum",
    "macd_hist_change": "MACD histogram today minus yesterday; > 0 = momentum improving",
    "macd_above_signal": "1 if the MACD line is above its signal line, else 0",
    "days_since_macd_cross": "Trading days since MACD last crossed above its signal (0 = today)",
}


class TechnicalParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9


def technical_frame(g: pd.DataFrame, params: TechnicalParams | dict | None = None) -> pd.DataFrame:
    """One stock, sorted by date. Returns the TECH_METRICS columns aligned to g.index."""
    p = params if isinstance(params, TechnicalParams) else TechnicalParams.model_validate(params or {})
    close = g["close"]
    m = indicators.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    out = pd.DataFrame(index=g.index)
    out["rsi"] = indicators.rsi(close, p.rsi_window)
    out["macd_hist"] = m["hist"]
    out["macd_hist_change"] = m["hist"].diff()
    out["macd_above_signal"] = (m["macd"] > m["signal"]).astype(float).where(m["signal"].notna())

    cross = (m["macd"] > m["signal"]) & (m["macd"].shift() <= m["signal"].shift())
    pos = pd.Series(np.arange(len(g)), index=g.index, dtype=float)
    last_cross = pos.where(cross).ffill()
    out["days_since_macd_cross"] = pos - last_cross      # NaN until the first cross
    return out


def describe(row: pd.Series) -> str:
    """Short plain-language line for reports: 'RSI 61 · MACD above signal, momentum rising'."""
    if pd.isna(row.get("rsi")):
        return ""
    parts = [f"RSI {row['rsi']:.0f}" + (" (overbought)" if row["rsi"] > 70 else " (oversold)" if row["rsi"] < 30 else "")]
    if pd.notna(row.get("macd_above_signal")):
        parts.append("MACD " + ("above" if row["macd_above_signal"] else "below") + " signal")
        if pd.notna(row.get("macd_hist_change")):
            parts[-1] += ", momentum " + ("rising" if row["macd_hist_change"] > 0 else "falling")
    d = row.get("days_since_macd_cross")
    if pd.notna(d) and d <= 10:
        parts.append(f"bullish MACD cross {int(d)}d ago" if d else "bullish MACD cross today")
    return " · ".join(parts)
