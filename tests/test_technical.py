import numpy as np
import pandas as pd
import pytest

from dse_screener.backtest import run_backtest
from dse_screener.config import Profile
from dse_screener.engine import evaluate_profile
from dse_screener.rules import Rule, passes
from dse_screener.technical import describe, technical_frame


def _g(close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"close": close})


def test_macd_cross_counter():
    close = np.r_[np.linspace(100, 80, 60), np.linspace(80, 100, 40)]
    tf = technical_frame(_g(close))
    first_cross = tf["days_since_macd_cross"].first_valid_index()
    assert tf.loc[first_cross, "days_since_macd_cross"] == 0
    assert tf["days_since_macd_cross"].iloc[-1] == len(close) - 1 - first_cross
    assert tf["macd_above_signal"].iloc[-1] == 1


def test_vectorized_passes_matches_rule_check():
    frame = pd.DataFrame({"rsi": [80.0, 55.0, np.nan], "macd_hist": [0.5, -0.1, 0.2]})
    rules = {"rsi": Rule(max=70), "macd_hist": Rule(min=0)}
    vec = passes(frame, rules).tolist()
    row_wise = [all(r.check(frame.loc[i, k]) is None for k, r in rules.items()) for i in frame.index]
    assert vec == row_wise == [False, False, False]
    assert passes(pd.DataFrame({"rsi": [60.0]}), {"rsi": Rule(max=70)}).tolist() == [True]


def test_describe_is_plain_language():
    row = pd.Series({"rsi": 75.0, "macd_above_signal": 1.0, "macd_hist_change": 0.1, "days_since_macd_cross": 2.0})
    assert describe(row) == "RSI 75 (overbought) · MACD above signal, momentum rising · bullish MACD cross 2d ago"


# --- the filter in the engine and the backtest ---------------------------------

def _stock(code, n=200, surge_at=150, trend=0.0, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(trend, 0.3, n))
    vol = np.full(n, 100_000.0)
    vol[surge_at:surge_at + 20] = 300_000
    return pd.DataFrame({
        "code": code, "date": pd.bdate_range("2025-01-01", periods=n), "open": close, "high": close + 1,
        "low": close - 1, "close": close, "ltp": close, "ycp": close, "volume": vol, "trades": 500.0,
        "value_mn": close * vol / 1e6,
    })


def _profile(rules):
    return Profile.model_validate({
        "name": "t",
        "filters": {"technical": {"enabled": True, "rules": rules}},
        "strategies": {"quiet_accumulation": {"params": {"max_price_range_pct": 30, "min_divergence": 1,
                                                         "min_price_change_pct": -10, "max_price_change_pct": 10}}},
        "ranking": {"min_score": 0},
        "backtest": {"horizons": [5], "primary_horizon": 5},
    })


@pytest.fixture
def data():
    prices = pd.concat([_stock("AAA", seed=1), _stock("BBB", surge_at=120, seed=2)], ignore_index=True)
    return prices, pd.DataFrame(index=pd.Index(["AAA", "BBB"], name="code"))


def test_impossible_rule_removes_all_picks(data):
    prices, metrics = data
    day = prices["date"].iloc[160].date()
    base = evaluate_profile(_profile({}), prices, metrics, day)
    assert not base.picks.empty and any(r.startswith("Tech: RSI") for r in base.picks.iloc[0]["reasons"])
    blocked = evaluate_profile(_profile({"rsi": {"max": -1}}), prices, metrics, day)
    assert blocked.picks.empty and set(blocked.technical_excluded) == set(base.picks["code"])
    assert run_backtest(_profile({"rsi": {"max": -1}}), prices, metrics).trades.empty


def test_backtest_matches_live_with_filter(data):
    prices, metrics = data
    prof = _profile({"rsi": {"max": 60}, "macd_hist_change": {"min": 0}})
    res = run_backtest(prof, prices, metrics)
    for day in res.trades["date"].unique():
        live = evaluate_profile(prof, prices, metrics, pd.Timestamp(day).date())
        assert set(res.trades.loc[res.trades["date"] == day, "code"]) <= set(live.picks["code"])
