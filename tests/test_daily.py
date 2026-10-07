from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from dse_screener.config import load_settings
from dse_screener.daily import run_daily
from dse_screener.db import Database
from dse_screener.notify.telegram import split_message
from dse_screener.report import index_text, market_summary, pick_quotes, quote_text, to_plain

THURSDAY = date(2026, 10, 1)


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class FakeArchive:
    """Returns nothing for the first `empty_calls` calls, then a full day."""
    name = "fake"

    def __init__(self, empty_calls=0, rows=400):
        self.calls, self.empty_calls, self.rows = 0, empty_calls, rows

    def fetch_range(self, start, end, code=None):
        self.calls += 1
        if self.calls <= self.empty_calls:
            return pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "ltp", "ycp",
                                         "trades", "value_mn", "volume"])
        n = self.rows
        return pd.DataFrame({
            "code": [f"X{i}" for i in range(n)], "date": [start] * n,
            "open": 10.0, "high": 11.0, "low": 9.0, "close": [10.5 if i % 2 else 9.5 for i in range(n)],
            "ltp": 10.0, "ycp": 10.0, "trades": 5, "value_mn": 1.0, "volume": 100,
        })


@pytest.fixture
def env(tmp_path):
    settings = load_settings()
    settings.research.inbox, settings.research.store = tmp_path / "inbox", tmp_path / "research"
    db = Database(tmp_path / "test.sqlite")
    sent = []
    yield settings, db, sent
    db.close()


def _official(day=THURSDAY):
    return {"date": day, "trades": 2100, "volume": 50_000, "value_mn": 520.0, "block_trades": 3,
            "block_volume": 10_000, "block_value_mn": 120.0, "advances": 199, "declines": 201,
            "unchanged": 0, "issues_traded": 400}


def _run(env, clock, archive, day=THURSDAY, wait=True, official=lambda d: False):
    settings, db, sent = env
    return run_daily(settings, db, sent.append, day=day, wait=wait, clock=clock, sleep=clock.sleep,
                     archive=archive, refresh=lambda codes, d: None, official=official)


def _at(t: time, d=THURSDAY):
    return datetime.combine(d, t)


def test_skips_weekend(env):
    clock = FakeClock(_at(time(15, 0), date(2026, 10, 2)))       # Friday
    out = _run(env, clock, FakeArchive(), day=date(2026, 10, 2))
    assert out.status == "not_trading_day" and env[2] == []


def test_waits_for_close_then_retries_until_data(env):
    clock, archive = FakeClock(_at(time(14, 0))), FakeArchive(empty_calls=2)
    out = _run(env, clock, archive)
    assert out.status == "sent"
    assert archive.calls == 3                                   # 2 empty, then data
    assert clock.now.time() >= time(14, 55)                     # waited to 14:45, then 2 x 5 min
    assert len(env[2]) == 1 and "DSE Screener" in env[2][0]
    # no official totals: 400 rows x 1 mn from the archive, flagged as missing block trades
    assert "Turnover ৳400.0 mn (৳40 cr, excl. block trades)" in to_plain(env[2][0])


def test_turnover_uses_official_totals_with_block_trades(env):
    clock = FakeClock(_at(time(14, 50)))
    out = _run(env, clock, FakeArchive(), official=lambda d: env[1].upsert_market_day(_official(d)) or True)
    assert out.status == "sent"
    text = to_plain(env[2][0])
    assert "Turnover ৳520.0 mn (৳52 cr, block ৳120.0 mn)" in text   # not the archive's 400 mn
    assert "▲ 199  ▼ 201" in text


def test_history_totals_give_block_as_the_gap(env):
    # Summary archive only (no block split, no breadth): block = official - archive sum
    _, db, _ = env
    _run(env, FakeClock(_at(time(14, 50))), FakeArchive(), official=lambda d: False)
    db.upsert_market_days(pd.DataFrame([{"date": THURSDAY, "trades": 2010, "volume": 41_000, "value_mn": 455.5}]))
    m = market_summary(db, THURSDAY)
    assert (m["turnover_mn"], m["block_mn"]) == (455.5, 55.5)
    assert (m["advances"], m["declines"]) == (200, 200)            # from the archive rows


def test_waits_for_official_totals_then_falls_back(env):
    calls = []
    out = _run(env, FakeClock(_at(time(14, 50))), FakeArchive(), official=lambda d: calls.append(d) or False)
    assert out.status == "sent" and calls == [THURSDAY] * 3
    assert "excl. block trades" in to_plain(env[2][0])


def test_gives_up_and_notifies_on_holiday(env):
    clock, archive = FakeClock(_at(time(14, 50))), FakeArchive(empty_calls=10_000)
    out = _run(env, clock, archive)
    assert out.status == "no_data"
    assert clock.now.time() >= time(16, 30)
    assert "Holiday or outage" in env[2][0]


def test_past_day_does_not_wait(env):
    clock, archive = FakeClock(_at(time(9, 0))), FakeArchive(empty_calls=1)
    out = _run(env, clock, archive, wait=False)
    assert out.status == "no_data" and clock.slept == [] and archive.calls == 1


def test_split_message_keeps_blocks_together():
    blocks = [f"<b>{i}. CODE</b>\n" + "line\n" * 30 for i in range(40)]
    parts = split_message("\n\n".join(blocks), limit=1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts)
    assert all(p.count("<b>") == p.count("</b>") for p in parts)
    assert "".join(p.replace("\n", "") for p in parts) == "".join(b.replace("\n", "") for b in blocks)


def test_index_line_with_change_from_previous_day(env):
    _, db, _ = env
    _run(env, FakeClock(_at(time(14, 50))), FakeArchive(), official=lambda d: False)
    assert "DSEX" not in to_plain(env[2][0])                   # no index data stored: line left out
    db.upsert_market_days(pd.DataFrame([
        {"date": THURSDAY - timedelta(days=3), "value_mn": 500.0, "dsex": 5000.0, "ds30": 2000.0},
        {"date": THURSDAY, "value_mn": 520.0, "dsex": 5050.0, "ds30": 1990.0},
    ]))
    m = market_summary(db, THURSDAY)
    assert index_text(m) == "DSEX 5,050.0 (+50.0, +1.00%) · DS30 1,990.0 (-10.0, -0.50%)"


def test_pick_quotes_show_ycp_open_close_and_change(env):
    _, db, _ = env
    _run(env, FakeClock(_at(time(14, 50))), FakeArchive(), official=lambda d: False)
    q = pick_quotes(db, ["X1", "X2", "NOPE"], THURSDAY)
    assert set(q) == {"X1", "X2"}                                   # no row, no line
    assert quote_text(q["X1"]) == "YCP 10.0 · Open 10.0 · Close 10.5 (+5.00%)"
    assert quote_text(q["X2"]) == "YCP 10.0 · Open 10.0 · Close 9.5 (-5.00%)"
    assert quote_text({"ycp": 10.0, "open": None, "close": None, "pct": None}) == "YCP 10.0 · Open – · Close –"
