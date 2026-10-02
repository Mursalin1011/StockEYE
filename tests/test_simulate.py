import numpy as np
import pandas as pd
import pytest

from dse_screener.backtest import simulate_exit
from dse_screener.config import CONFIG_DIR, ExitRule, TradePlan, list_plans, load_plan
from dse_screener.features import Columns
from dse_screener.simulate import describe, run_plan, summarize


def _prices(close, open_=None, high=None, low=None, volume=None, code="AAA", start="2025-01-01"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    return pd.DataFrame({
        "code": code, "date": pd.bdate_range(start, periods=n),
        "open": close if open_ is None else np.asarray(open_, dtype=float),
        "high": close + 1 if high is None else np.asarray(high, dtype=float),
        "low": close - 1 if low is None else np.asarray(low, dtype=float),
        "close": close, "volume": np.full(n, 1000.0) if volume is None else np.asarray(volume, dtype=float),
    })


def _plan(**kw) -> TradePlan:
    data = {"entry": {"dates": ["2025-01-02"]}, "hold": {"min_days": 0}, "costs": {"round_trip_pct": 0}}
    for key, value in kw.items():
        data[key] = {**data.get(key, {}), **value} if isinstance(value, dict) else value
    return TradePlan.model_validate(data)


# --- plan model -----------------------------------------------------------------

def test_conditions_parse_from_text_or_lists():
    p = TradePlan.model_validate({"entry": {"when": ["close > sma_50", ["rsi_14", "<", "40"]]},
                                  "exit": {"when_any": [["close", "crosses_below", "ema_20"]]}})
    assert p.entry.when == [("close", ">", "sma_50"), ("rsi_14", "<", 40.0)]
    assert p.exit.when_any == [("close", "crosses_below", "ema_20")]


@pytest.mark.parametrize("entry", [{}, {"dates": ["2025-01-02"], "strategy": "base_breakout"},
                                   {"when": ["close >> sma_5"]}, {"when": ["close > "]}, {"when": ["close > sma_5"], "profile": "swing"}])
def test_bad_entries_fail_loudly(entry):
    with pytest.raises(ValueError):
        TradePlan.model_validate({"entry": entry})


def test_saved_plans_load_and_read_well():
    assert list_plans(), f"expected example plans in {CONFIG_DIR / 'plans'}"
    for name in list_plans():
        plan = load_plan(name)
        assert len(describe(plan)) == 4


# --- columns ---------------------------------------------------------------------

def test_high_n_excludes_today_so_a_breakout_is_possible():
    cols = Columns(_prices([10, 11, 12, 13, 20]))
    assert cols["high_3"].iloc[4] == 13                     # max of the 3 days before
    assert cols.check(("close", ">", "high_3")).iloc[4]


def test_crosses_above_fires_only_on_the_crossing_day():
    cols = Columns(_prices([5, 5, 5, 9, 9, 9]))
    hit = cols.check(("close", "crosses_above", 7.0))
    assert hit.tolist() == [False, False, False, True, False, False]


def test_unknown_column_lists_known_ones():
    with pytest.raises(ValueError, match="sma_N"):
        Columns(_prices([1, 2, 3]))["smaa_5"]


def test_vol_x_against_previous_days():
    cols = Columns(_prices([10] * 5, volume=[100, 100, 100, 100, 300]))
    assert cols["vol_x_4"].iloc[4] == pytest.approx(3.0)


# --- exits -------------------------------------------------------------------------

def test_stop_gap_down_fills_at_the_open():
    #            0    1(buy)  2    3: opens far below the stop
    g = _prices([100, 100, 100, 80], open_=[100, 100, 100, 85], low=[99, 99, 95, 79])
    t = run_plan(_plan(exit={"stop_pct": 8}), g).trades.iloc[0]
    assert (t["why"], t["exit"], t["exit_date"]) == ("stop", 85, g["date"][3])


def test_stop_inside_the_range_fills_at_the_stop():
    g = _prices([100, 100, 100, 95], low=[99, 99, 99, 90])
    t = run_plan(_plan(exit={"stop_pct": 8}), g).trades.iloc[0]
    assert t["why"] == "stop" and t["exit"] == pytest.approx(92)


def test_target_and_stop_same_day_assumes_the_stop():
    g = _prices([100, 100, 100, 100], high=[101, 101, 101, 130], low=[99, 99, 99, 90])
    t = run_plan(_plan(exit={"stop_pct": 8, "target_pct": 20}), g).trades.iloc[0]
    assert t["why"] == "stop"


def test_target_gap_up_fills_at_the_open():
    g = _prices([100, 100, 100, 130], open_=[100, 100, 100, 128], high=[101, 101, 101, 131])
    t = run_plan(_plan(exit={"target_pct": 20}), g).trades.iloc[0]
    assert (t["why"], t["exit"]) == ("target", 128)


def test_min_days_delays_the_stop_until_shares_can_be_sold():
    # Buy on row 1; the stop is breached on row 2 but shares are sellable from row 3 (min_days 2)
    g = _prices([100, 100, 90, 95, 95], low=[99, 99, 89, 91, 94], open_=[100, 100, 92, 95, 95])
    t = run_plan(_plan(exit={"stop_pct": 8}, hold={"min_days": 2}), g).trades.iloc[0]
    assert t["exit_date"] == g["date"][3]
    assert (t["why"], t["exit"]) == ("stop", 92)            # still below the stop on row 3: filled at the stop


def test_trailing_percent_on_closes():
    g = _prices([100, 100, 110, 120, 110, 107])
    t = run_plan(_plan(exit={"trail_pct": 10}), g).trades.iloc[0]
    assert t["exit_date"] == g["date"][5] and t["why"] == "trail 10%"   # 107 <= 120 x 0.9 = 108


def test_condition_exit_and_open_trade():
    g = _prices([50, 50, 60, 70, 80, 60])
    res = run_plan(_plan(exit={"when_any": ["close > 75"]}), g)
    assert res.trades.iloc[0]["why"] == "close > 75" and res.trades.iloc[0]["exit_date"] == g["date"][4]
    still = run_plan(_plan(exit={"when_any": ["close > 500"]}), g).trades.iloc[0]
    assert still["why"] == "open" and still["exit"] == 60


def test_time_limit_counts_from_the_signal_day():
    g = _prices(np.full(10, 100.0))
    t = run_plan(_plan(entry={"dates": ["2025-01-02"]}, exit={"max_days": 3}), g).trades.iloc[0]
    # buy date row 1 at its open (signal = row 0), exit at the close of row 0 + 3
    assert t["entry_date"] == g["date"][1] and t["exit_date"] == g["date"][3] and t["why"] == "time"


def test_matches_backtest_simulate_exit():
    """Same entries, stop + trailing MA + time limit: identical to the backtest's exit rule."""
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    open_ = close * (1 + rng.normal(0, 0.01, 400))
    g = _prices(close, open_=open_, high=np.maximum(close, open_) * 1.01, low=np.minimum(close, open_) * 0.99)
    rule = ExitRule(stop_pct=5, trail_ma=50, max_days=25)
    ma = g["close"].rolling(50).mean()
    seen = set()
    for e in range(51, 400, 6):                    # one plan per entry, so no trade is skipped as overlapping
        plan = _plan(entry={"dates": [g["date"][e].date()]}, exit={"stop_pct": 5, "trail_ma": 50, "max_days": 25})
        t = run_plan(plan, g).trades.iloc[0]
        j, px, why = simulate_exit(g, e - 1, rule, ma)
        assert (g["date"][j], round(px, 6)) == (t.exit_date, round(t.exit, 6))
        assert {"stop": "stop", "trail": "below MA50", "time": "time", "open": "open"}[why] == t.why
        seen.add(why)
    assert {"stop", "trail", "time"} <= seen


# --- entries, positions, money --------------------------------------------------------

def test_one_position_at_a_time_and_cooldown():
    close = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32]
    plan = _plan(entry={"dates": [], "when": ["close > 0"], "new_signal_only": False},
                 exit={"max_days": 2}, hold={"cooldown_days": 2})
    t = run_plan(plan, _prices(close)).trades
    rows = [int(np.flatnonzero(pd.bdate_range("2025-01-01", periods=12) == d)[0]) for d in t["entry_date"]]
    exits = [int(np.flatnonzero(pd.bdate_range("2025-01-01", periods=12) == d)[0]) for d in t["exit_date"]]
    assert all(nxt > prev + 2 for prev, nxt in zip(exits, rows[1:]))    # buys only after exit + cooldown
    assert rows[0] == 1                                                  # first signal row 0 -> next open


def test_new_signal_only_skips_the_rest_of_a_run():
    close = [10, 10, 20, 21, 22, 23, 24, 10, 10, 20, 21, 21]
    plan = _plan(entry={"dates": [], "when": ["close > 15"]}, exit={"max_days": 1})
    t = run_plan(plan, _prices(close)).trades
    assert len(t) == 2                                                   # two separate setups: rows 2 and 9


def test_dates_roll_forward_to_the_next_trading_day():
    g = _prices([10, 11, 12, 13, 14])                    # 2025-01-01 is a Wednesday; 4-5 Jan is a weekend
    t = run_plan(_plan(entry={"dates": ["2025-01-04"]}, exit={"max_days": 1}), g).trades.iloc[0]
    assert t["entry_date"] == pd.Timestamp("2025-01-06") and t["entry"] == 13


def test_no_lookahead_past_the_window_end():
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))
    full = _prices(close)
    plan = _plan(entry={"dates": [], "when": ["close crosses_above sma_20"]}, exit={"trail_ma": 10, "stop_pct": 6})
    cut = full["date"][200]
    a = run_plan(plan.model_copy(update={"end": cut.date()}), full).trades
    b = run_plan(plan, full[full["date"] <= cut]).trades
    pd.testing.assert_frame_equal(a, b)


def test_strategy_entry_and_costs():
    """A base breakout: flat base, then a high-volume breakout."""
    close = np.r_[np.full(60, 100.0), np.linspace(106, 140, 20)]
    vol = np.r_[np.full(60, 1000.0), np.full(20, 5000.0)]
    plan = _plan(entry={"dates": [], "strategy": "base_breakout"}, exit={"max_days": 5}, costs={"round_trip_pct": 1})
    t = run_plan(plan, _prices(close, volume=vol)).trades
    assert len(t) == 1
    assert t.iloc[0]["signal_date"] == pd.bdate_range("2025-01-01", periods=80)[60]
    assert t.iloc[0]["ret_pct"] == pytest.approx((t.iloc[0]["exit"] / t.iloc[0]["entry"] - 1) * 100 - 1)


def test_equity_and_buy_and_hold():
    g = _prices([100, 100, 110, 110, 121, 121])
    plan = _plan(entry={"dates": ["2025-01-02", "2025-01-06"]}, exit={"max_days": 2},
                 capital={"start": 1000, "per_trade_pct": 50})
    res = run_plan(plan, g)
    # trade 1: 100 -> 110 (+10%) on half the money; trade 2: 110 -> 121 (+10%) on half of 1050
    assert res.stocks.loc["AAA", "end_equity"] == pytest.approx(1000 + 50 + 52.5)
    assert res.stocks.loc["AAA", "buy_hold_pct"] == pytest.approx(21)
    assert res.equity["equity"].iloc[0] == 1000
    s = summarize(res)
    assert s.loc["all", "trades"] == 2 and s.loc["all", "win_rate"] == 100


def test_pending_signal_on_the_last_day():
    res = run_plan(_plan(entry={"dates": [], "when": ["close > 15"]}), _prices([10, 10, 10, 20]))
    assert res.trades.empty and res.pending and "buy at the next open" in res.pending[0]


def test_actual_prices_undo_the_adjustment():
    # 1:1 bonus with ex-date row 3: traded at 100 before, 50 after; the adjusted series is flat at 50
    g = _prices([50, 50, 50, 50, 50]).assign(price_adj=[0.5, 0.5, 0.5, 1.0, 1.0])
    t = run_plan(_plan(exit={"max_days": 3}), g).trades.iloc[0]
    assert (t["entry_actual"], t["exit_actual"]) == (100, 50) and t["ret_pct"] == pytest.approx(0)


def test_basket_uses_the_trade_dates_and_only_stocks_that_traded():
    from dse_screener.simulate import add_basket

    g = _prices([100, 100, 110, 110, 121, 121])
    res = run_plan(_plan(entry={"dates": ["2025-01-02"]}, exit={"max_days": 2}, costs={"round_trip_pct": 1}), g)
    # basket: BBB +20% over the trade (open row 1 -> close row 2); CCC didn't trade on the entry day: left out
    bbb = _prices([50, 50, 60, 60, 60, 60], code="BBB")
    ccc = _prices([10, 10, 99, 99, 99, 99], code="CCC", volume=[1, 0, 1, 1, 1, 1])
    add_basket(res, pd.concat([bbb, ccc]), ["BBB", "CCC"], "2 test stocks")
    t = res.trades.iloc[0]
    assert t["ret_pct"] == pytest.approx(9) and t["basket_pct"] == pytest.approx(19)
    assert t["excess_pct"] == pytest.approx(-10)
    assert res.stocks.loc["AAA", "basket_hold_pct"] == pytest.approx(((60 / 50 - 1) + (99 / 10 - 1)) / 2 * 100 - 1)
    s = summarize(res)
    assert s.loc["all", "mean_excess"] == pytest.approx(-10) and s.loc["all", "beat_basket"] == 0
