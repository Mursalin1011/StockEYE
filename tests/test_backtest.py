import numpy as np
import pandas as pd
import pytest

from dse_screener.backtest import forward_returns, run_backtest, summarize
from dse_screener.config import Profile
from dse_screener.engine import evaluate_profile


def _stock(code, n=200, surge_at=150, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    vol = np.full(n, 100_000.0)
    vol[surge_at:surge_at + 20] = 300_000
    return pd.DataFrame({
        "code": code, "date": pd.bdate_range("2025-01-01", periods=n), "open": close, "high": close + 1,
        "low": close - 1, "close": close, "ltp": close, "ycp": close, "volume": vol,
        "trades": 500.0, "value_mn": close * vol / 1e6,
    })


PROFILE = Profile.model_validate({
    "name": "t",
    "strategies": {"quiet_accumulation": {"params": {"max_price_range_pct": 30, "min_divergence": 1,
                                                     "min_price_change_pct": -10, "max_price_change_pct": 10}},
                   "base_breakout": {}},
    "ranking": {"min_score": 0},
    "backtest": {"horizons": [5, 10], "primary_horizon": 10, "cost_pct": 1.0, "in_sample_until": "2025-07-01"},
})


@pytest.fixture
def data():
    prices = pd.concat([_stock("AAA", seed=1), _stock("BBB", surge_at=120, seed=2), _stock("CCC", surge_at=999, seed=3)],
                       ignore_index=True)
    metrics = pd.DataFrame(index=pd.Index(["AAA", "BBB", "CCC"], name="code"))
    return prices, metrics


def test_forward_returns_enter_next_open_and_subtract_costs():
    g = pd.DataFrame({"open": [10.0, 11.0, 12.0, 13.0], "close": [10.0, 11.0, 12.0, 14.0]})
    f = forward_returns(g, [2], cost_pct=1.0)
    # signal on row 0: buy at row 1 open (11), sell at row 2 close (12)
    assert f.loc[0, "ret_2"] == pytest.approx((12 / 11 - 1) * 100 - 1.0)
    assert np.isnan(f.loc[3, "ret_2"])            # no future data: no return


def test_backtest_picks_match_live_screen(data):
    """The backtest must pick exactly what the live screen would have picked on each day."""
    prices, metrics = data
    res = run_backtest(PROFILE, prices, metrics)
    assert not res.trades.empty
    # Compare on every date that has a backtest pick (before de-overlapping, so re-run rank via the live path)
    for day in res.trades["date"].unique()[:10]:
        live = evaluate_profile(PROFILE, prices, metrics, pd.Timestamp(day).date())
        assert set(res.trades.loc[res.trades["date"] == day, "code"]) <= set(live.picks["code"])


def test_trades_do_not_overlap(data):
    prices, metrics = data
    t = run_backtest(PROFILE, prices, metrics).trades
    for code, g in t.groupby("code"):
        dates = prices.loc[prices["code"] == code, "date"].reset_index(drop=True)
        pos = dates.searchsorted(g["date"])
        assert (np.diff(pos) > 10).all()          # primary horizon 10 days


def test_summary_has_segments(data):
    prices, metrics = data
    s = summarize(run_backtest(PROFILE, prices, metrics))
    assert {"all", "in-sample", "out-of-sample"} <= set(s.index)
    assert s.loc["all", "trades"] == s.loc["in-sample", "trades"] + s.loc["out-of-sample", "trades"]
