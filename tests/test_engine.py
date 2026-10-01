import numpy as np
import pandas as pd
import pytest

from dse_screener.config import Profile
from dse_screener.engine import evaluate_profile


def _stock(code, vol_tail, trades_tail=500, n=150):
    close = 100 + 0.5 * np.sin(np.arange(n))
    vol = np.r_[np.full(n - 20, 100_000), np.full(20, vol_tail)]
    trades = np.r_[np.full(n - 20, 500), np.full(20, trades_tail)]
    return pd.DataFrame({
        "code": code, "date": pd.bdate_range("2025-01-01", periods=n), "close": close,
        "volume": vol, "trades": trades, "value_mn": close * vol / 1e6,
    })


PROFILE = {
    "name": "test",
    "strategies": {
        "quiet_accumulation": {"weight": 1.0},
        "big_hands": {"weight": 0.7, "role": "confirm", "params": {"min_avg_trades": 10}},
    },
    "ranking": {
        "min_score": 0, "confluence_bonus": 10,
        "boosts": [{"metric": "institute_change_pp", "when": {"min": 1}, "points": 5, "label": "institutions adding"}],
    },
}


@pytest.fixture
def prices():
    return pd.concat([
        _stock("ACC", vol_tail=300_000, trades_tail=1500),     # accumulation only (trade size unchanged)
        _stock("BOTH", vol_tail=300_000, trades_tail=150),     # accumulation + bigger trades
        _stock("HANDS", vol_tail=100_000, trades_tail=200),    # bigger trades only (confirm role)
        _stock("QUIET", vol_tail=100_000),                     # nothing
    ], ignore_index=True)


def _metrics(**overrides):
    m = pd.DataFrame({"institute_change_pp": [0.0] * 4}, index=pd.Index(["ACC", "BOTH", "HANDS", "QUIET"], name="code"))
    for code, v in overrides.items():
        m.loc[code, "institute_change_pp"] = v
    return m


def test_ranking_confluence_confirm_and_boost(prices):
    as_of = prices["date"].max().date()
    res = evaluate_profile(Profile.model_validate(PROFILE), prices, _metrics(BOTH=2.0), as_of)
    picks = res.picks.set_index("code")

    assert "HANDS" in set(res.signals["code"])      # it did fire...
    assert "HANDS" not in picks.index               # ...but a confirming strategy can't qualify alone
    assert "QUIET" not in picks.index
    assert list(picks.index) == ["BOTH", "ACC"]
    # BOTH = same accumulation score as ACC + 10 confluence + 5 boost
    assert picks.loc["BOTH", "final_score"] == pytest.approx(picks.loc["ACC", "final_score"] + 15, abs=0.2)
    assert any("institutions adding" in r for r in picks.loc["BOTH", "reasons"])


def test_quality_filter_excludes(prices):
    profile = Profile.model_validate({**PROFILE, "filters": {"quality": {"rules": {"institute_change_pp": {"min": 1}}}}})
    res = evaluate_profile(profile, prices, _metrics(BOTH=2.0), prices["date"].max().date())
    assert list(res.picks["code"]) == ["BOTH"]
    assert set(res.excluded["code"]) == {"ACC", "HANDS", "QUIET"}


def test_record_date_penalty(prices):
    as_of = prices["date"].max().date()
    actions = pd.DataFrame([{"code": "ACC", "record_date": (pd.Timestamp(as_of) - pd.Timedelta(days=10)).date()}])
    base = evaluate_profile(Profile.model_validate(PROFILE), prices, _metrics(), as_of).picks.set_index("code")
    res = evaluate_profile(Profile.model_validate(PROFILE), prices, _metrics(), as_of, actions).picks.set_index("code")
    assert res.loc["ACC", "final_score"] == pytest.approx(base.loc["ACC", "final_score"] - 20)
    assert any("dividend-driven" in r for r in res.loc["ACC", "reasons"])
    assert res.loc["BOTH", "final_score"] == base.loc["BOTH", "final_score"]


def test_as_of_uses_only_past_data(prices):
    early = prices["date"].iloc[100].date()        # before the volume surge
    res = evaluate_profile(Profile.model_validate(PROFILE), prices, _metrics(), early)
    assert res.picks.empty and res.as_of == early
