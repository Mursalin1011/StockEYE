import pandas as pd
import pytest

pytest.importorskip("plotly")

from dse_screener.dashboard.charts import price_volume_chart, strategy_color  # noqa: E402


def test_markers_align_on_a_sliced_window():
    # The dashboard slices the last N days; signals keep the original index (regression test)
    prices = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=10), "close": range(10, 20), "volume": [100] * 10,
    }).iloc[5:]
    sig = pd.Series([False, False, True, True, False], index=prices.index)
    fig = price_volume_chart(prices, {"quiet_accumulation": sig}, {"quiet_accumulation": "Quiet accumulation"})
    markers = [t for t in fig.data if t.name == "Quiet accumulation"]
    assert len(markers) == 1 and list(markers[0].y) == [17]     # first day of the run only


def test_strategy_colors_are_fixed_and_mode_specific():
    assert strategy_color("quiet_accumulation", "light") == "#2a78d6"
    assert strategy_color("quiet_accumulation", "dark") == "#3987e5"
    assert strategy_color("base_breakout") != strategy_color("big_hands")
