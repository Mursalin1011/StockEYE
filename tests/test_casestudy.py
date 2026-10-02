import numpy as np
import pandas as pd
import pytest

from dse_screener.backtest import forward_returns
from dse_screener.casestudy import run_casestudy
from dse_screener.config import Profile


def _breakout_stock(n=160, at=120):
    """Flat base, then a high-volume breakout at `at` and a +60% run-up."""
    close = np.full(n, 100.0)
    close[at:] = np.linspace(105, 170, n - at)
    vol = np.full(n, 10_000.0)
    vol[at:at + 3] = 50_000
    return pd.DataFrame({
        "code": "AAA", "date": pd.bdate_range("2025-01-01", periods=n), "open": close, "high": close + 0.5,
        "low": close - 0.5, "close": close, "volume": vol, "value_mn": close * vol / 1e6,
    })


PROFILE = Profile.model_validate({
    "name": "t",
    "strategies": {"base_breakout": {"params": {"base_days": 25, "max_base_range_pct": 10, "min_volume_x": 2.0,
                                                "max_days_since": 2}}},
    "ranking": {"min_score": 10},
    "backtest": {"horizons": [5, 20], "primary_horizon": 20, "cost_pct": 1.0,
                 "exits": {"stop5": {"stop_pct": 5, "max_days": 20}},
                 "winners": {"min_gain_pct": 50, "within_days": 60}},
})


def test_casestudy_lists_the_breakout_with_backtest_identical_outcomes():
    g = _breakout_stock()
    metrics = pd.DataFrame(index=pd.Index(["AAA"], name="code"))
    cs = run_casestudy(PROFILE, g, metrics, None, "2025-03-01")
    sig = cs.signals[cs.signals["status"] == "signal"]
    assert len(sig) == 1
    row = sig.iloc[0]
    i = int(g.index[g["date"] == row["date"]][0])
    assert i == 120 and row["days_on"] >= 3
    fwd = forward_returns(g, [5, 20], 1.0)
    assert row["ret_5"] == pytest.approx(fwd.at[i, "ret_5"]) and row["ret_20"] == pytest.approx(fwd.at[i, "ret_20"])
    assert row["why_stop5"] == "time" and row["ret_stop5"] == pytest.approx(fwd.at[i, "ret_20"])
    assert row["clears_cut"] and row["cut_date"] == row["date"]
    assert cs.quality_passed   # no quality rules in this profile
    # the run-up is a big move, caught early by the breakout
    assert len(cs.moves) >= 1 and "base_breakout" in cs.moves.iloc[0]["caught_by"]


def test_casestudy_marks_signals_blocked_by_the_technical_filter():
    g = _breakout_stock()
    prof = PROFILE.model_copy(deep=True)
    prof.filters = Profile.model_validate({"name": "x", "filters": {"technical": {"rules": {"rsi": {"max": 1}}}}}).filters
    cs = run_casestudy(prof, g, pd.DataFrame(index=pd.Index(["AAA"], name="code")), None, "2025-03-01")
    assert set(cs.signals["status"]) == {"blocked"}
    assert cs.signals.iloc[0]["blocked_by"][0].startswith("rsi:")


def test_casestudy_rejects_an_empty_window():
    with pytest.raises(ValueError):
        run_casestudy(PROFILE, _breakout_stock(), pd.DataFrame(), None, "2030-01-01")
