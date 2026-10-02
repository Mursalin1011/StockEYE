"""Columns a trade plan's conditions can use, by name (docs/06-trade-lab-plan.md).

Values on date t use data up to t only, like the strategies. `N` is any whole number:
`sma_50`, `rsi_9`, `high_20`, ... Unknown names fail with the list of known ones.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np
import pandas as pd

from . import indicators, technical
from .config import Condition

PRICE = ["open", "high", "low", "close", "volume", "value_mn"]


def _close(g: pd.DataFrame) -> pd.Series:
    return g["close"].astype(float)


def _vol(g: pd.DataFrame) -> pd.Series:
    return g["volume"].astype(float)


# name_N -> (description, function of (prices, N))
WINDOWED: dict[str, tuple[str, Callable[[pd.DataFrame, int], pd.Series]]] = {
    "sma": ("simple moving average of the close", lambda g, n: indicators.sma(_close(g), n)),
    "ema": ("exponential moving average of the close", lambda g, n: indicators.ema(_close(g), n)),
    "rsi": ("Wilder RSI, 0-100", lambda g, n: indicators.rsi(_close(g), n)),
    "atr": ("average true range (Wilder), in price units", lambda g, n: indicators.atr(g, n)),
    "high": ("highest close of the previous N days (so close > high_20 is a breakout)",
             lambda g, n: _close(g).shift(1).rolling(n).max()),
    "low": ("lowest close of the previous N days", lambda g, n: _close(g).shift(1).rolling(n).min()),
    "vol_x": ("volume / average volume of the previous N days", lambda g, n: _vol(g) / _vol(g).shift(1).rolling(n).mean()),
    "avg_vol": ("average volume of the last N days", lambda g, n: _vol(g).rolling(n).mean()),
    "ret": ("% change of the close over N days", lambda g, n: (_close(g) / _close(g).shift(n) - 1) * 100),
    "pct_from_high": ("% below the highest close of the last N days (0 = at the high)",
                      lambda g, n: (_close(g) / _close(g).rolling(n).max() - 1) * 100),
}

FIXED: dict[str, str] = {
    "change_pct": "% change of the close from the previous day",
    "macd": "MACD line (12/26)",
    "macd_signal": "MACD signal line (9)",
    **{k: v for k, v in technical.TECH_METRICS.items() if k.startswith(("macd_", "days_since"))},
}

_NAME = re.compile(rf"^({'|'.join(sorted(WINDOWED, key=len, reverse=True))})_(\d+)$")


def known() -> list[str]:
    """One line per column, for help texts and error messages."""
    return ([f"{' '.join(PRICE)}: the day's prices and volume"] + [f"{k}_N: {d}" for k, (d, _) in WINDOWED.items()]
            + [f"{k}: {d}" for k, d in FIXED.items()])


class Columns:
    """Lazily computed, cached columns for one stock (sorted by date, index 0..n-1, adjusted prices)."""

    def __init__(self, g: pd.DataFrame):
        self.g = g
        self._cache: dict[str, pd.Series] = {}

    def __getitem__(self, name: str) -> pd.Series:
        if name not in self._cache:
            self._cache[name] = self._compute(name)
        return self._cache[name]

    def _compute(self, name: str) -> pd.Series:
        g = self.g
        if name in PRICE:
            return g[name].astype(float)
        if m := _NAME.match(name):
            n = int(m.group(2))
            if n < 1:
                raise ValueError(f"column '{name}': N must be at least 1")
            return WINDOWED[m.group(1)][1](g, n).astype(float)
        if name == "change_pct":
            return (_close(g) / _close(g).shift() - 1) * 100
        if name in ("macd", "macd_signal"):
            m = indicators.macd(_close(g))
            return m["macd" if name == "macd" else "signal"]
        if name in FIXED:
            if "_tech" not in self._cache:
                self._cache["_tech"] = technical.technical_frame(g)
            return self._cache["_tech"][name]
        raise ValueError(f"unknown column '{name}'. Known columns:\n  " + "\n  ".join(known()))

    def operand(self, x: float | str) -> pd.Series:
        return pd.Series(float(x), index=self.g.index) if isinstance(x, float) else self[x]

    def check(self, cond: Condition) -> pd.Series:
        """True where the condition holds on that day's close (missing values: False)."""
        left, op, right = cond
        a, b = self[left], self.operand(right)
        with np.errstate(invalid="ignore"):
            if op == ">":
                out = a > b
            elif op == "<":
                out = a < b
            elif op == ">=":
                out = a >= b
            elif op == "<=":
                out = a <= b
            elif op == "crosses_above":
                out = (a > b) & (a.shift() <= b.shift())
            elif op == "crosses_below":
                out = (a < b) & (a.shift() >= b.shift())
            else:
                raise ValueError(f"unknown operator '{op}'")
        return out.fillna(False).astype(bool)

    def all_true(self, conds: list[Condition]) -> pd.Series:
        out = pd.Series(True, index=self.g.index)
        for c in conds:
            out &= self.check(c)
        return out

    def first_valid(self, conds: list[Condition]) -> int:
        """First row on which every column the conditions use has a value (indicator warm-up)."""
        first = 0
        for left, _, right in conds:
            for name in (left, right):
                if isinstance(name, str):
                    s = self[name]
                    idx = s.first_valid_index()
                    first = max(first, len(s) if idx is None else int(idx))
        return first
