import pandas as pd
import pytest

from dse_screener.adjust import apply_adjustments
from dse_screener.corporate_actions import build_corporate_actions


def _prices():
    # EBL-like: 17.5% cash + 17.5% stock, record date 2025-04-23 (suspended), resumes 2025-04-24.
    return pd.DataFrame(
        {
            "code": ["EBL"] * 3 + ["GP"] * 2,
            "date": pd.to_datetime(["2025-04-21", "2025-04-22", "2025-04-24", "2025-04-22", "2025-04-24"]),
            "open": [26.8, 27.0, 21.3, 300.0, 301.0],
            "high": [27.1, 27.2, 21.6, 302.0, 303.0],
            "low": [26.7, 26.9, 20.8, 299.0, 300.0],
            "close": [27.0, 27.0, 21.4, 301.0, 302.0],
            "ltp": [27.0, 27.0, 21.4, 301.0, 302.0],
            "ycp": [26.9, 27.0, 27.0, 300.0, 301.0],
            "trades": [10, 10, 10, 5, 5],
            "value_mn": [1.0, 1.0, 1.0, 1.0, 1.0],
            "volume": [1000, 2000, 3000, 500, 500],
        }
    )


def _events():
    return pd.DataFrame(
        [{"code": "EBL", "record_date": pd.Timestamp("2025-04-23").date(), "fiscal_year": 2024, "cash_pct": 17.5,
          "stock_pct": 17.5, "news_date": pd.Timestamp("2025-03-25").date(), "title": "EBL: Dividend Declaration",
          "revised": False}]
    )


def test_build_action_matches_dse_reference_price():
    act = build_corporate_actions(_events(), _prices(), {"EBL": 10.0}).iloc[0]
    assert act["ex_date"] == "2025-04-24"
    assert act["ref_close"] == 27.0
    # (27.0 - 1.75) / 1.175 = 21.49; EBL actually opened at 21.3
    assert act["ref_close"] * act["price_factor"] == pytest.approx(21.489, abs=0.01)
    assert act["volume_factor"] == pytest.approx(1.175)


def test_apply_back_adjusts_prices_and_volume():
    prices = _prices()
    actions = build_corporate_actions(_events(), prices, {"EBL": 10.0})
    out = apply_adjustments(prices, actions).set_index(["code", "date"])

    before = out.loc[("EBL", pd.Timestamp("2025-04-22"))]
    assert before["close"] == pytest.approx(21.489, abs=0.01)
    assert before["volume"] == 2350                        # 2000 * 1.175
    after = out.loc[("EBL", pd.Timestamp("2025-04-24"))]
    assert after["close"] == 21.4 and after["price_adj"] == 1.0
    assert after["ycp"] == pytest.approx(21.489, abs=0.01)  # previous adjusted close
    assert (out.loc["GP"]["price_adj"] == 1.0).all()       # other stocks untouched


def test_bonus_only_mode_ignores_cash():
    prices = _prices()
    actions = build_corporate_actions(_events(), prices, {"EBL": 10.0})
    out = apply_adjustments(prices, actions, include_cash=False).set_index(["code", "date"])
    assert out.loc[("EBL", pd.Timestamp("2025-04-22"))]["close"] == pytest.approx(27.0 / 1.175)


def test_future_record_date_is_kept_but_not_applied():
    events = _events().assign(record_date=pd.Timestamp("2025-04-30").date())
    actions = build_corporate_actions(events, _prices(), {"EBL": 10.0})
    assert actions.iloc[0]["ex_date"] is None
    out = apply_adjustments(_prices(), actions)
    assert (out["price_adj"] == 1.0).all()
