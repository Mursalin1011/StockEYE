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


# --- W2: exit styles, profit factor, recall -----------------------------------

from dse_screener.backtest import big_moves, recall, simulate_exit  # noqa: E402
from dse_screener.config import ExitRule, WinnersConfig  # noqa: E402


def _bars(close, open_=None, low=None, volume=None):
    close = np.asarray(close, float)
    return pd.DataFrame({
        "date": pd.bdate_range("2025-01-01", periods=len(close)),
        "open": close if open_ is None else np.asarray(open_, float),
        "low": close if low is None else np.asarray(low, float),
        "close": close,
        "volume": np.full(len(close), 1000.0) if volume is None else np.asarray(volume, float),
    })


def test_time_exit_matches_fixed_holding_period():
    g = _bars(100 + np.arange(30.0))
    j, px, why = simulate_exit(g, 3, ExitRule(max_days=10))
    assert (j, why) == (13, "time")
    fixed = forward_returns(g, [10], 1.0).loc[3, "ret_10"]
    assert (px / g["open"][4] - 1) * 100 - 1.0 == pytest.approx(fixed)


def test_stop_fills_at_the_stop_or_a_lower_open():
    close = [100, 100, 99, 95, 90, 90]
    g = _bars(close, open_=[100, 100, 99, 95, 85, 90], low=[100, 100, 98, 93, 84, 90])
    # entry 100 (row 1 open), -8% stop = 92: row 3 low 93 holds, row 4 gaps to 85 -> filled at the open
    assert simulate_exit(g, 0, ExitRule(stop_pct=8, max_days=20)) == (4, 85.0, "stop")
    g2 = _bars(close, low=[100, 100, 98, 91, 84, 90])
    assert simulate_exit(g2, 0, ExitRule(stop_pct=8, max_days=20)) == (3, 92.0, "stop")


def test_trailing_ma_exit_and_open_trades():
    close = [10, 11, 12, 13, 14, 12, 15]
    g = _bars(close)
    ma = g["close"].rolling(3).mean()
    assert simulate_exit(g, 1, ExitRule(trail_ma=3, max_days=20), ma) == (5, 12.0, "trail")
    # data ends before any exit: marked at the last close and flagged open
    assert simulate_exit(_bars([10, 11, 12, 13]), 0, ExitRule(max_days=20)) == (3, 13.0, "open")


def test_stop_and_trail_ignore_no_trade_days():
    g = _bars([100, 100, 100, 100], low=[100, 100, 80, 100], volume=[1, 1, 0, 1])
    assert simulate_exit(g, 0, ExitRule(stop_pct=8, max_days=3)) == (3, 100.0, "time")


def test_big_moves_count_one_run_up_once():
    # 10 -> 16 with a dip in the middle: one episode, not several
    close = [10, 10, 11, 12, 11, 12, 13, 14, 15, 16, 15, 15, 15]
    m = big_moves(_bars(close), WinnersConfig(min_gain_pct=50, within_days=20))
    assert len(m) == 1
    assert m.loc[0, "i"] == 0 and m.loc[0, "peak_gain_pct"] == pytest.approx(60)


def test_backtest_reports_exits_profit_factor_and_recall(data):
    prices, metrics = data
    prof = PROFILE.model_copy(deep=True)
    prof.backtest.exits = {"stop5": ExitRule(stop_pct=5, max_days=10)}
    res = run_backtest(prof, prices, metrics)
    t = res.trades
    assert {"ret_stop5", "bench_stop5", "excess_stop5", "days_stop5", "why_stop5"} <= set(t.columns)
    # no stop hit -> same as the fixed 10-day hold
    timed = t[t["why_stop5"] == "time"]
    assert np.allclose(timed["ret_stop5"], timed["ret_10"])
    s = summarize(res, "stop5")
    assert {"profit_factor", "avg_win", "avg_loss", "median_days"} <= set(s.columns)
    r = recall(res)
    assert "shortlist" in r.index and (r["caught"] <= r["moves"]).all()


def test_recall_counts_early_catches_only():
    from dse_screener.backtest import BacktestResult

    moves = pd.DataFrame({"code": ["A", "A"], "date": pd.to_datetime(["2025-03-01", "2025-09-01"]),
                          "i": [50, 200], "start": [10.0, 10.0]})
    trades = pd.DataFrame({"date": pd.to_datetime(["2025-02-20", "2025-12-01"]), "code": ["A", "A"],
                           "i": [45, 280], "entry": [10.5, 11.0]})
    res = BacktestResult("t", trades, [20], 20, None, ["A"], moves["date"].min(), moves["date"].max(),
                         winners=moves, winners_cfg=WinnersConfig())
    r = recall(res).loc["shortlist"]
    # first move caught 5 days early; the second only 80 days after its start (limit 60)
    assert (r["moves"], r["caught"], r["median_days_after_start"]) == (2, 1, -5)
