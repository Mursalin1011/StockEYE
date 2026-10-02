"""Standard technical indicators on a single stock's (adjusted) series.

Backward-looking only, like the strategies, so values on date t use data up to t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _wilder(values: np.ndarray, window: int) -> np.ndarray:
    """Wilder smoothing: seed with the simple mean of the first `window` values, then
    avg_t = (avg_{t-1} * (window - 1) + value_t) / window. Index 0 (no change yet) is skipped."""
    out = np.full(len(values), np.nan)
    if len(values) <= window:
        return out
    avg = values[1 : window + 1].mean()
    out[window] = avg
    for t in range(window + 1, len(values)):
        avg = (avg * (window - 1) + values[t]) / window
        out[t] = avg
    return out


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI (0-100), as on most charting sites. Above 70 is usually called
    overbought, below 30 oversold."""
    delta = close.astype(float).diff().fillna(0).to_numpy()
    gain = _wilder(np.clip(delta, 0, None), window)
    loss = _wilder(np.clip(-delta, 0, None), window)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss))
    out[np.isnan(gain)] = np.nan
    return pd.Series(out, index=close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line (fast EMA - slow EMA), its signal line, and the histogram (difference)."""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Wilder's Average True Range: the typical daily range, gaps included, in price units."""
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return pd.Series(_wilder(tr.astype(float).to_numpy(), window), index=df.index)
