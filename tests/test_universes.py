from datetime import date, timedelta

import pandas as pd

from dse_screener import quality
from dse_screener.db import Database
from dse_screener.sources.dse_company import CompanyProfile
from dse_screener.universes import universe_codes


def _company(db, code, itype, status="Active", category="A"):
    db.save_company(CompanyProfile(code=code, info={"code": code, "instrument_type": itype,
                                                    "operational_status": status, "category": category}))


def test_all_equities_query_picks_active_equities_only(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    _company(db, "AAA", "Equity")
    _company(db, "BBB", "Equity", status="Non-operational")
    _company(db, "1JANATAMF", "Mutual Fund")
    _company(db, "CCC", "Equity", category="Z")
    assert universe_codes("all_equities", db) == ["AAA", "CCC"]   # category is the profile's job, not the universe's
    assert universe_codes("ds30", db)[:2] == ["ACMELAB", "BATBC"]  # fixed lists still work


def test_liquidity_counts_no_trade_days_as_zero(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    rows = []
    for i, d in enumerate(days):
        traded = i % 2 == 0                          # trades only every other day
        rows.append({"code": "AAA", "date": d, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "ltp": 10.0,
                     "ycp": 10.0, "trades": 5 if traded else 0, "value_mn": 4.0 if traded else 0.0,
                     "volume": 1000 if traded else 0})
    db.upsert_prices(pd.DataFrame(rows), "test")
    _company(db, "AAA", "Equity")
    m = quality.compute_quality_metrics(db, ["AAA"]).loc["AAA"]
    assert m["avg_value_mn_60"] == 2.0                # 30 days x 4 mn / 60 days
    assert m["traded_days_pct_60"] == 50.0
