import numpy as np
import pandas as pd
import pytest

from dse_screener.strategies import REGISTRY
from dse_screener.strategies.base_breakout import BaseBreakout
from dse_screener.strategies.big_hands import BigHands
from dse_screener.strategies.quiet_accumulation import QuietAccumulation


def make_df(close, volume, trades=None):
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    trades = np.asarray(trades if trades is not None else np.full(len(close), 500), dtype=float)
    return pd.DataFrame({
        "code": "TEST",
        "date": pd.bdate_range("2025-01-01", periods=len(close)),
        "close": close,
        "volume": volume,
        "trades": trades,
        "value_mn": close * volume / 1e6,
    })


def flat(n, level=100.0, wiggle=0.5):
    return level + wiggle * np.sin(np.arange(n))


# --- quiet accumulation -----------------------------------------------------

def test_accumulation_fires_on_flat_price_rising_volume():
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    out = QuietAccumulation().compute(make_df(flat(150), vol)).iloc[-1]
    assert out["signal"]
    assert out["volume_ratio"] == pytest.approx(3.0)
    assert out["score"] > 60


def test_accumulation_ignores_price_that_already_ran():
    close = np.r_[flat(130), np.linspace(100, 120, 20)]
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    assert not QuietAccumulation().compute(make_df(close, vol)).iloc[-1]["signal"]


def test_accumulation_needs_rising_volume():
    assert not QuietAccumulation().compute(make_df(flat(150), np.full(150, 100_000))).iloc[-1]["signal"]


def test_market_relative_ignores_market_wide_surges():
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    df = make_df(flat(150), vol)
    df["mkt_value_mn"] = np.r_[np.full(130, 5000.0), np.full(20, 15000.0)]   # whole market also tripled
    assert QuietAccumulation().compute(df).iloc[-1]["signal"]                 # off: looks like accumulation
    rel = QuietAccumulation({"market_relative": True}).compute(df).iloc[-1]
    assert rel["volume_ratio"] == pytest.approx(1.0) and not rel["signal"]

    df["mkt_value_mn"] = 5000.0                                               # market flat: stock-specific
    assert QuietAccumulation({"market_relative": True}).compute(df).iloc[-1]["signal"]


def test_no_lookahead():
    """Values on a date must not change when later data is appended."""
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    base = make_df(flat(150), vol)
    longer = make_df(np.r_[flat(150), np.full(30, 150.0)], np.r_[vol, np.full(30, 900_000)])
    for cls in REGISTRY.values():
        a = cls().compute(base)
        b = cls().compute(longer).iloc[:150]
        pd.testing.assert_frame_equal(a, b, check_dtype=False)


# --- base breakout ----------------------------------------------------------

def test_breakout_fires_and_decays():
    close = np.r_[flat(60), 105.0, 104.5]
    vol = np.r_[np.full(60, 100_000), 400_000, 150_000]
    out = BaseBreakout().compute(make_df(close, vol))
    today, next_day = out.iloc[-2], out.iloc[-1]
    assert today["signal"] and today["days_since"] == 0 and today["volume_x"] == pytest.approx(4.0)
    assert next_day["signal"] and next_day["days_since"] == 1
    assert next_day["score"] == pytest.approx(today["score"] - 5)   # recency penalty


def test_breakout_needs_volume():
    close = np.r_[flat(60), 105.0]
    assert not BaseBreakout().compute(make_df(close, np.full(61, 100_000))).iloc[-1]["signal"]


# --- big hands --------------------------------------------------------------

def test_big_hands_fires_when_trades_get_larger():
    n = 100
    trades = np.r_[np.full(80, 1000), np.full(20, 400)]          # same volume, fewer trades
    out = BigHands().compute(make_df(flat(n), np.full(n, 200_000), trades)).iloc[-1]
    assert out["signal"]
    assert out["trade_size_growth"] == pytest.approx(2.5, rel=0.02)


def test_params_typo_fails_loudly():
    with pytest.raises(Exception):
        QuietAccumulation({"min_volume_ratoi": 2})
