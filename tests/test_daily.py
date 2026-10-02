from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from dse_screener.config import load_settings
from dse_screener.daily import run_daily
from dse_screener.db import Database
from dse_screener.notify.telegram import split_message
from dse_screener.report import to_plain

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


def _run(env, clock, archive, day=THURSDAY, wait=True):
    settings, db, sent = env
    return run_daily(settings, db, sent.append, day=day, wait=wait, clock=clock, sleep=clock.sleep,
                     archive=archive, refresh=lambda codes, d: None)


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
    assert "Turnover ৳40 cr" in to_plain(env[2][0])            # 400 rows x 1 mn = 400 mn = 40 crore


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
