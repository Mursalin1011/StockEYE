import numpy as np
import pandas as pd
import pytest

from dse_screener.indicators import macd, rsi


def test_rsi_extremes_and_midpoint():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert rsi(down).iloc[-1] == pytest.approx(0.0, abs=1e-9)
    zigzag = pd.Series([10.0, 11.0] * 30)
    assert rsi(zigzag).iloc[-1] == pytest.approx(50.0, abs=5)
    assert rsi(up).iloc[:13].isna().all()          # needs `window` days of history


def test_rsi_matches_wilder_reference():
    # Classic Wilder example series (first 14 changes), RSI at day 15 ~ 70.5
    close = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03,
                       45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])
    assert rsi(close).iloc[14] == pytest.approx(70.5, abs=1.5)


def test_macd_crosses_after_trend_change():
    close = pd.Series(np.r_[np.linspace(100, 80, 60), np.linspace(80, 110, 60)])
    m = macd(close)
    assert m["hist"].iloc[55] < 0 < m["hist"].iloc[-1]   # bearish during the fall, bullish after the turn
    valid = m.dropna()
    assert np.allclose(valid["hist"], valid["macd"] - valid["signal"])
