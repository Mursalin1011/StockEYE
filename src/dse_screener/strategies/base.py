"""Strategy contract.

A strategy computes, for one stock's adjusted daily series, a row per date with:
  signal (bool), score (0-100) and the metric columns its reasons are built from.
Every window looks backward only, so the value on date t uses data up to t.
The same code serves today's screen and historical backtests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict


class StrategyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in YAML should fail loudly


class Strategy(ABC):
    name: ClassVar[str]
    title: ClassVar[str]
    Params: ClassVar[type[StrategyParams]]

    def __init__(self, params: dict | None = None):
        self.p = self.Params.model_validate(params or {})

    @property
    @abstractmethod
    def min_history(self) -> int:
        """Trading days needed before the first signal is possible."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """df: one stock, sorted by date, adjusted prices. Returns frame aligned to df.index
        with at least `signal` and `score` columns."""

    @abstractmethod
    def reasons(self, row: pd.Series) -> list[str]:
        """Plain-language explanation for one signal row."""


def scale(x, lo: float, hi: float):
    """Linear 0..1 between lo and hi (clipped). Works for scalars and Series."""
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def window_ratio(series: pd.Series, short: int, baseline: int) -> pd.Series:
    """Mean of the last `short` days / mean of the `baseline` days before that."""
    return series.rolling(short).mean() / series.shift(short).rolling(baseline).mean()
