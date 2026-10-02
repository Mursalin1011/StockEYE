import numpy as np
import pandas as pd
import pytest

from dse_screener.strategies import REGISTRY
from dse_screener.strategies.base_breakout import BaseBreakout
from dse_screener.strategies.big_hands import BigHands
from dse_screener.strategies.quiet_accumulation import QuietAccumulation
from dse_screener.strategies.second_breakout import SecondBreakout


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


def _accumulation_then_breakout():
    """Flat ~100 with volume tripling (accumulation), then a 3-day push to 108 at the end."""
    close = np.r_[flat(145), 103.0, 105.0, 106.0, 107.0, 108.0]
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    return make_df(close, vol)


def test_range_exclude_keeps_accumulation_through_a_late_breakout():
    params = {"max_price_range_pct": 6, "max_price_change_pct": 6}
    df = _accumulation_then_breakout()
    assert not QuietAccumulation(params).compute(df).iloc[-1]["signal"]          # range 8% > 6%
    row = QuietAccumulation({**params, "range_exclude_days": 5}).compute(df).iloc[-1]
    assert row["signal"] and row["range_pct"] < 2                                # judged on the base before
    assert "before the last 5" in QuietAccumulation({**params, "range_exclude_days": 5}).reasons(row)[1]


def test_max_days_since_carries_the_signal_with_a_decaying_score():
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000), np.full(30, 20_000)]
    close = np.r_[flat(150), np.full(30, 100.0)]
    df = make_df(close, vol)
    off = QuietAccumulation({"vol_short_days": 20}).compute(df)
    on = QuietAccumulation({"vol_short_days": 20, "max_days_since": 3}).compute(df)
    last = off.index[off["signal"]][-1]
    assert not off.loc[last + 1, "signal"]
    for k in (1, 2, 3):
        assert on.loc[last + k, "signal"] and on.loc[last + k, "days_since"] == k
        assert on.loc[last + k, "score"] == pytest.approx(off.loc[last, "score"] - 5 * k)
    assert not on.loc[last + 4, "signal"]
    assert (on.loc[off["signal"], "score"] == off.loc[off["signal"], "score"]).all()   # fresh days unchanged


def test_w6_options_have_no_lookahead():
    vol = np.r_[np.full(130, 100_000), np.full(20, 300_000)]
    base = make_df(flat(150), vol)
    longer = make_df(np.r_[flat(150), np.full(30, 150.0)], np.r_[vol, np.full(30, 900_000)])
    s = QuietAccumulation({"range_exclude_days": 5, "max_days_since": 5})
    pd.testing.assert_frame_equal(s.compute(base), s.compute(longer).iloc[:150], check_dtype=False)


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


# --- second breakout --------------------------------------------------------

def shakeout(after_close=110.0, after_vol=1_000_000, shake=99.0, wait=10):
    """Flat base ~100, breakout to 105 (peak 107), back into the base at `shake`, then a re-break."""
    close = np.r_[flat(60), 105.0, 107.0, 104.0, shake, np.full(wait, 100.0), after_close]
    vol = np.r_[np.full(60, 100_000), 400_000, 200_000, 150_000, 150_000, np.full(wait, 100_000), after_vol]
    return make_df(close, vol)


def test_second_breakout_fires_after_shakeout():
    df = shakeout()
    out = SecondBreakout().compute(df).iloc[-1]
    assert out["signal"] and out["days_since"] == 0
    assert out["failed_high"] == pytest.approx(107.0)
    assert out["first_date"] == df["date"].iloc[60]
    assert out["shake_low_pct"] < 0 and out["score"] > 50
    assert "failed" in SecondBreakout().reasons(out)[0]


def test_second_breakout_needs_the_first_to_fail():
    close = np.r_[flat(60), 105.0, 107.0, np.full(10, 106.0), 112.0]     # never fell back into the base
    vol = np.r_[np.full(60, 100_000), 400_000, np.full(11, 100_000), 1_000_000]
    assert not SecondBreakout().compute(make_df(close, vol))["signal"].any()


def test_second_breakout_needs_volume_and_a_new_high():
    assert not SecondBreakout().compute(shakeout(after_vol=120_000)).iloc[-1]["signal"]
    assert not SecondBreakout().compute(shakeout(after_close=106.0)).iloc[-1]["signal"]   # below the 107 peak


def test_second_breakout_cancelled_if_base_breaks_or_too_late():
    assert not SecondBreakout().compute(shakeout(shake=90.0)).iloc[-1]["signal"]   # >5% under the base low
    assert not SecondBreakout().compute(shakeout(wait=45)).iloc[-1]["signal"]      # beyond 40 days


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


# --- base breakout v2 (W5): dry-up and follow-through ------------------------

def _dryup_breakout(before_vol):
    """60 days at volume 100k, then 10 days at `before_vol`, a 4x breakout and two more closes above."""
    close = np.r_[flat(70), 105.0, 106.0, 106.5]
    vol = np.r_[np.full(60, 100_000), np.full(10, before_vol), 400_000, 150_000, 150_000]
    return make_df(close, vol)


def test_dryup_filter_keeps_only_breakouts_after_quiet_volume():
    params = {"base_days": 40, "max_dryup_ratio": 0.8, "dryup_days": 10, "dryup_baseline_days": 50, "min_volume_x": 2}
    quiet = BaseBreakout(params).compute(_dryup_breakout(50_000))
    busy = BaseBreakout(params).compute(_dryup_breakout(150_000))
    assert quiet.iloc[70]["signal"] and quiet.iloc[70]["dryup_ratio"] == pytest.approx(0.5)
    assert not busy["signal"].any()
    # off by default: the busy one fires too
    assert BaseBreakout({"base_days": 40}).compute(_dryup_breakout(150_000)).iloc[70]["signal"]


def test_follow_through_delays_the_signal_until_confirmed():
    out = BaseBreakout({"base_days": 40, "follow_through_days": 3, "follow_through_closes": 2}).compute(
        _dryup_breakout(100_000))
    assert not out.iloc[70]["signal"] and not out.iloc[71]["signal"]   # breakout day, first close above
    row = out.iloc[72]                                                  # second close above: confirmed
    assert row["signal"] and row["days_since"] == 0 and row["lag"] == 2
    assert "Confirmed" in BaseBreakout({"follow_through_days": 3}).reasons(row)[-1]


def test_follow_through_rejects_a_breakout_that_falls_back():
    close = np.r_[flat(70), 105.0, 99.0, 99.5, 100.0]
    vol = np.r_[np.full(70, 100_000), 400_000, 150_000, 150_000, 150_000]
    assert not BaseBreakout({"base_days": 40, "follow_through_days": 3}).compute(make_df(close, vol))["signal"].any()


def test_v2_options_off_reproduce_the_original_breakout():
    """With dry-up and follow-through off, signals, days_since and scores equal the pre-W5 logic."""
    from dse_screener.strategies.base_breakout import breakout_days

    rng = np.random.default_rng(7)
    close, vol, level = [], [], 100.0
    for _ in range(8):                                   # 8 cycles: quiet base, then a jump on volume
        close += list(level + rng.normal(0, 0.5, 30))
        vol += list(rng.lognormal(11, 0.3, 30))
        level *= 1.06
        close += [level, level * 1.01, level * 0.97]
        vol += [vol[-1] * 4, vol[-1] * 2, vol[-1]]
    df = make_df(close, vol)
    p = {"base_days": 25, "max_base_range_pct": 10, "max_days_since": 2}
    new = BaseBreakout(p).compute(df)
    b = breakout_days(df, 25, 10, 1.0, 2.0)
    pp = BaseBreakout(p).p
    day_score = (50 * np.clip((b["volume_x"] - 2) / 3, 0, 1) + 30 * (1 - np.clip((b["base_range_pct"] - 5) / 5, 0, 1))
                 + 20 * np.clip((b["breakout_pct"] - 1) / 4, 0, 1))
    sig, since, score = pd.Series(False, index=df.index), pd.Series(np.nan, index=df.index), pd.Series(0.0, index=df.index)
    for k in range(2, -1, -1):
        hit = b["is_breakout"].shift(k, fill_value=False) & (df["close"] >= b["base_high"].shift(k))
        sig[hit], since[hit] = True, k
        score[hit] = (day_score.shift(k)[hit] - pp.recency_penalty * k).clip(lower=0)
    assert sig.sum() >= 8
    assert (new["signal"] == sig).all()
    assert np.allclose(new.loc[sig, "days_since"], since[sig]) and np.allclose(new.loc[sig, "score"], score[sig])
