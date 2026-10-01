"""The contract every price source must follow."""

from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd

# Normalized end-of-day columns. Every adapter returns exactly these.
PRICE_COLUMNS = [
    "code",
    "date",
    "open",
    "high",
    "low",
    "close",
    "ltp",
    "ycp",
    "trades",
    "value_mn",
    "volume",
]


class PriceSource(Protocol):
    name: str

    def fetch_range(self, start: date, end: date, code: str | None = None) -> pd.DataFrame:
        """End-of-day rows for [start, end]; all instruments when code is None."""
        ...
