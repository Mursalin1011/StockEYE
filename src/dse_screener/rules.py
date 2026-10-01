"""Generic config-driven rules: `metric: {min: x, max: y, in: [...]}`.

Used by filters now and strategies later, so every threshold lives in YAML.
"""

from __future__ import annotations

import math

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class Rule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    min: float | None = None
    max: float | None = None
    in_: list[str] | None = Field(default=None, alias="in")
    not_in: list[str] | None = None

    def check(self, value) -> str | None:
        """Return None if the value passes, else a short reason."""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "no data"
        if self.in_ is not None and str(value) not in self.in_:
            return f"{value} not in {self.in_}"
        if self.not_in is not None and str(value) in self.not_in:
            return f"{value} is excluded"
        if self.min is not None and value < self.min:
            return f"{_fmt(value)} < {_fmt(self.min)}"
        if self.max is not None and value > self.max:
            return f"{_fmt(value)} > {_fmt(self.max)}"
        return None


def _fmt(v) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def evaluate(metrics: pd.DataFrame, rules: dict[str, Rule]) -> pd.DataFrame:
    """metrics: one row per code (index), one column per metric.

    Returns `passed` (bool) and `failures` (list of "metric: reason").
    """
    results = []
    for code, row in metrics.iterrows():
        failures = [
            f"{name}: {reason}"
            for name, rule in rules.items()
            if (reason := rule.check(row.get(name))) is not None
        ]
        results.append({"code": code, "passed": not failures, "failures": failures})
    return pd.DataFrame(results).set_index("code")
