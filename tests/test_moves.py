import numpy as np
import pandas as pd
import pytest

from dse_screener.config import Profile
from dse_screener.moves import scan, to_payload


def _stock(code, n=200, at=None):
    """Flat base; with `at`, a high-volume breakout there and a +60% run-up."""
    close = np.full(n, 100.0)
    vol = np.full(n, 10_000.0)
    if at is not None:
        close[at:] = np.linspace(105, 170, n - at)
        vol[at:at + 3] = 50_000
    return pd.DataFrame({
        "code": code, "date": pd.bdate_range("2025-01-01", periods=n), "open": close, "high": close + 0.5,
        "low": close - 0.5, "close": close, "volume": vol, "value_mn": close * vol / 1e6,
    })


def _profile(name, min_volume_x=2.0):
    return Profile.model_validate({
        "name": name,
        "strategies": {"base_breakout": {"params": {"base_days": 25, "max_base_range_pct": 10,
                                                    "min_volume_x": min_volume_x, "max_days_since": 2}}},
        "backtest": {"cost_pct": 1.0, "winners": {"min_gain_pct": 50, "within_days": 60}},
    })


def test_scan_finds_the_move_and_the_strategy_that_caught_it():
    prices = pd.concat([_stock("AAA", at=120), _stock("BBB")], ignore_index=True)
    metrics = pd.DataFrame(index=pd.Index(["AAA", "BBB"], name="code"))
    # the second profile's breakout needs more volume than the stock had, so it never fires
    res = scan([_profile("swing"), _profile("strict", min_volume_x=50)], prices, metrics)

    assert list(res.moves["code"]) == ["AAA"]
    move = res.moves.iloc[0]
    assert move["peak_gain_pct"] >= 50
    assert [c["key"] for c in move["caught_by"]] == ["swing:base_breakout"]
    catch = move["caught_by"][0]
    assert -20 <= catch["days_from_start"] <= 60 and catch["gain_left_pct"] > 0

    sig = res.signals
    assert set(sig["code"]) == {"AAA"} and set(sig["profile"]) == {"swing"}
    first = sig.iloc[0]
    assert first["date"] == prices.loc[120, "date"]
    assert first["quality"]                                    # no quality rules in these profiles
    assert first["ret"] == pytest.approx((prices.loc[140, "close"] / prices.loc[121, "open"] - 1) * 100 - 1.0)

    payload = to_payload(res, pd.DataFrame({"code": ["AAA"], "name": ["Aaa Ltd"], "sector": ["Tech"], "category": ["A"]}),
                         ["swing", "strict"])
    assert payload["stocks"]["AAA"]["name"] == "Aaa Ltd" and payload["stocks"]["AAA"]["quality"] == ["swing", "strict"]
    assert payload["moves"][0]["date"] == move["date"].strftime("%Y-%m-%d")
    assert isinstance(payload["signals"][0]["date"], str)
