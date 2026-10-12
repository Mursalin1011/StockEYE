from datetime import date, timedelta

import pandas as pd
import pytest

from dse_screener import bot, holdings
from dse_screener.config import Profile, load_settings
from dse_screener.db import Database
from dse_screener.engine import SIGNAL_COLUMNS, WATCH_COLUMNS, ScreenResult
from dse_screener.holdings import CommandError, parse
from dse_screener.report import to_plain

TODAY = date(2026, 10, 8)        # a Thursday
DAYS = pd.bdate_range(end=TODAY, periods=60)


def _prices(code: str, closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    days = DAYS[-n:]
    volumes = volumes or [1000] * n
    return pd.DataFrame({
        "code": code, "date": [d.date() for d in days], "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes, "ltp": closes,
        "ycp": [closes[0]] + closes[:-1], "trades": 10, "value_mn": 1.0, "volume": volumes,
    })


@pytest.fixture
def env(tmp_path):
    settings = load_settings()
    db = Database(tmp_path / "test.sqlite")
    yield settings, db
    db.close()


# --- parsing ----------------------------------------------------------------------------------------

def test_parse_buy_with_everything():
    c = parse("/bought ptl 53.7 500 5/10 stop 48", TODAY)
    assert (c.kind, c.code, c.price, c.qty, c.day, c.stop) == ("buy", "PTL", 53.7, 500, date(2026, 10, 5), 48)


def test_parse_variants():
    assert parse("/bought@StockEyeBot PTL 53.7", TODAY).day == TODAY            # group-style, default today
    assert parse("bought PTL ৳1,053.5 2026-09-30", TODAY).price == 1053.5      # no slash, taka sign, ISO date
    assert parse("/sold PTL 60 yesterday", TODAY).day == date(2026, 10, 7)
    assert parse("/bought PTL 50 20/12", TODAY).day == date(2025, 12, 20)       # no year, in the future = last year
    assert parse("/bought PTL 50 05.10.2026", TODAY).day == date(2026, 10, 5)
    assert parse("/bought PTL 50 5-10-26", TODAY).day == date(2026, 10, 5)
    assert parse("/stop PTL off", TODAY).price is None
    assert parse("/holdings", TODAY).kind == "list"


@pytest.mark.parametrize("text, msg", [
    ("/bought PTL", "Usage"), ("/bought PTL abc", "isn't a price"), ("/bought PTL 50 1.5", "whole number"),
    ("/bought PTL 50 9/10", "future"), ("/sell PTL 50 xyz", "couldn't read"), ("/foo", "don't know"),
    ("/bought PTL 50 31/02", "valid date"),
])
def test_parse_errors(text, msg):
    with pytest.raises(CommandError, match=msg):
        parse(text, TODAY)


# --- positions --------------------------------------------------------------------------------------

def _ledger(rows):
    df = pd.DataFrame(rows, columns=["code", "action", "date", "price", "qty"])
    df["id"] = range(1, len(df) + 1)
    df["date"] = pd.to_datetime(df["date"])
    return df


NO_ACTIONS = pd.DataFrame(columns=["code", "ex_date", "price_factor", "bonus_factor", "volume_factor"])


def test_average_cost_partial_sell_and_close():
    t = _ledger([("PTL", "buy", "2026-09-01", 50, 100), ("PTL", "buy", "2026-09-10", 60, 100),
                 ("PTL", "sell", "2026-09-20", 70, 50)])
    opened, closed = holdings.build_positions(t, NO_ACTIONS, TODAY)
    p = opened["PTL"]
    assert p.cost == pytest.approx(55) and p.shares == 150 and p.paid == 11000   # sells keep the average cost
    t = _ledger([*t[["code", "action", "date", "price", "qty"]].itertuples(index=False),
                 ("PTL", "sell", "2026-09-25", 66, None)])
    opened, closed = holdings.build_positions(t, NO_ACTIONS, TODAY)
    assert not opened and closed[0].realized_pct == pytest.approx(20)


def test_bonus_after_the_buy_adjusts_cost_and_shares():
    acts = pd.DataFrame({"code": ["PTL"], "ex_date": [pd.Timestamp("2026-09-15")], "price_factor": [1 / 1.1],
                         "bonus_factor": [1 / 1.1], "volume_factor": [1.1]})
    t = _ledger([("PTL", "buy", "2026-09-01", 55, 100), ("PTL", "stop", "2026-09-01", 50, None)])
    p = holdings.build_positions(t, acts, TODAY)[0]["PTL"]
    assert p.cost == pytest.approx(50) and p.shares == pytest.approx(110) and p.stop == pytest.approx(50 / 1.1)
    # a buy on the ex-date itself is already at the new price
    t = _ledger([("PTL", "buy", "2026-09-15", 50, 100)])
    assert holdings.build_positions(t, acts, TODAY)[0]["PTL"].cost == pytest.approx(50)


# --- commands against a database --------------------------------------------------------------------

def test_apply_buy_sell_undo(env):
    settings, db = env
    db.upsert_prices(_prices("PTL", [50.0] * 60), "test")
    run = lambda text: to_plain(holdings.apply(db, settings, parse(text, TODAY)))  # noqa: E731
    out = run("/bought PTL 50 100 stop 46")
    assert "Bought PTL 100 @ 50.00" in out and "stop 46.00" in out
    assert "Typo" not in out
    assert "75.0" in run("/bought PTL 75 100")                                   # far from the day's range: flagged
    assert "Removed" in run("/undo")
    assert "Position closed: +10.0%" in run("/sold PTL 55")
    assert "Nothing to undo" not in run("/undo")
    assert len(db.load_trades()) == 2                                             # buy + its stop


def test_apply_rejects_bad_input(env):
    settings, db = env
    db.upsert_prices(_prices("PTL", [50.0] * 5), "test")
    with pytest.raises(CommandError, match="Did you mean PTL"):
        holdings.apply(db, settings, parse("/bought PTI 50", TODAY))
    with pytest.raises(CommandError, match="no open PTL"):
        holdings.apply(db, settings, parse("/sold PTL 50", TODAY))
    holdings.apply(db, settings, parse("/bought PTL 50 100", TODAY))
    with pytest.raises(CommandError, match="can't sell 200"):
        holdings.apply(db, settings, parse("/sold PTL 50 200", TODAY))
    with pytest.raises(CommandError, match="share counts"):
        holdings.apply(db, settings, parse("/bought PTL 50", TODAY))


def test_undo_removes_a_buy_and_its_stop(env):
    settings, db = env
    db.upsert_prices(_prices("PTL", [50.0] * 5), "test")
    holdings.apply(db, settings, parse("/bought PTL 50 stop 45", TODAY), source="telegram", source_ref="tg:1")
    assert len(db.load_trades()) == 2
    holdings.apply(db, settings, parse("/undo", TODAY))
    assert db.load_trades().empty


# --- the daily check --------------------------------------------------------------------------------

def _result(profile: str, signals=(), watch=()) -> tuple[Profile, ScreenResult]:
    sig = pd.DataFrame([{"code": c, "strategy": s, "title": t, "role": "primary", "score": 70.0, "weighted": 70.0,
                         "reasons": [], "metrics": {}} for c, s, t in signals], columns=SIGNAL_COLUMNS)
    w = pd.DataFrame([{"code": c, "strategy": s, "title": t, "reasons": ["needs 2x volume"], "metrics": {}}
                      for c, s, t in watch], columns=WATCH_COLUMNS)
    return Profile(name=profile), ScreenResult(profile, TODAY, 10, pd.DataFrame(), sig, pd.DataFrame(), watch=w)


def test_review_warnings(env):
    settings, db = env
    # rising for 55 days, then a heavy-volume slide below MA20 and the stop
    closes = [50 + i * 0.5 for i in range(55)] + [74.0, 72.0, 70.0, 66.0, 60.0]
    db.upsert_prices(_prices("AAA", closes, [1000] * 59 + [5000]), "test")
    db.upsert_prices(_prices("BBB", [100.0] * 60), "test")
    db.add_trade("AAA", "buy", DAYS[-20].date(), 70.0, 100)
    db.add_trade("AAA", "stop", DAYS[-20].date(), 62.0)
    db.add_trade("BBB", "buy", DAYS[-10].date(), 90.0)
    db.replace_corporate_actions(pd.DataFrame({
        "code": ["BBB"], "record_date": [(TODAY + timedelta(days=6)).isoformat()], "cash_pct": [10.0],
        "stock_pct": [0.0]}), ["BBB"])
    rv = holdings.review(db, settings, TODAY, [_result("swing", signals=[("BBB", "base_breakout", "Base breakout")])])
    a, b = rv.checks                                  # warnings sort first
    assert a.pos.code == "AAA" and a.pnl_pct == pytest.approx(-100 * 10 / 70) and a.pnl_amount == pytest.approx(-1000)
    text = " | ".join(a.warnings)
    assert "Closed at or below your stop 62.00" in text and "below MA20" in text and "Heavy selling" in text
    assert b.pos.code == "BBB" and b.pnl_pct == pytest.approx(100 / 9) and not b.warnings
    assert any("Record date" in n and "10% cash" in n for n in b.notes)
    assert any("Base breakout today (swing" in n for n in b.notes)
    out = to_plain(holdings.render(rv))
    assert "2 open · 1 need a look" in out and "AAA · 100 sh @ 70.00" in out and "BBB · 1 buy @ 90.00" in out
    assert "Value" not in out                          # BBB has no share count: no money total


def test_reentry_alert_after_a_sell(env):
    settings, db = env
    db.upsert_prices(_prices("PTL", [50.0] * 60), "test")
    db.add_trade("PTL", "buy", DAYS[-40].date(), 45.0)
    db.add_trade("PTL", "sell", DAYS[-20].date(), 54.0)
    quiet = holdings.review(db, settings, TODAY, [_result("swing")])
    assert holdings.render(quiet) is None
    rv = holdings.review(db, settings, TODAY, [_result("swing", watch=[("PTL", "second_breakout", "Second breakout")])])
    out = to_plain(holdings.render(rv))
    assert "PTL · you sold" in out and "(+20.0%)" in out and "Second breakout setting up (swing)" in out


# --- the bot ----------------------------------------------------------------------------------------

class FakeTelegram:
    chat_id = "42"

    def __init__(self, updates):
        self.pending, self.sent, self.offsets = updates, [], []

    def updates(self, offset=None, wait_s=0):
        self.offsets.append(offset)
        return [u for u in self.pending if offset is None or u["update_id"] >= offset]

    def send(self, text):
        self.sent.append(text)


def _msg(uid, text, chat=42):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_bot_handles_own_chat_only_and_never_twice(env):
    settings, db = env
    db.upsert_prices(_prices("PTL", [50.0] * 5), "test")
    tg = FakeTelegram([_msg(7, "/bought PTL 50 100"), _msg(8, "/bought PTL 50 100", chat=99), _msg(9, "/sold XYZ 1")])
    assert bot.poll_once(db, settings, tg) == 2
    sent = [to_plain(t) for t in tg.sent]
    assert "Bought PTL" in sent[0] and "No DSE stock 'XYZ'" in sent[1] and len(sent) == 2
    assert len(db.load_trades()) == 1
    tg.sent.clear()
    assert bot.poll_once(db, settings, tg) == 0 and tg.offsets[-1] == 10          # offset confirms what was read
    assert db.add_trade("PTL", "buy", TODAY, 50.0, 100, source="telegram", source_ref="tg:7") is None


# --- dashboard API ----------------------------------------------------------------------------------

def test_api_add_list_delete_and_undo(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from dse_screener.api import app as api

    path = tmp_path / "api.sqlite"
    seed = Database(path)
    seed.upsert_prices(_prices("PTL", [50.0] * 60), "test")
    seed.close()

    def temp_db():
        db = Database(path, check_same_thread=False)
        try:
            yield db
        finally:
            db.close()

    api.app.dependency_overrides[api.get_db] = temp_db
    try:
        client = TestClient(api.app)
        res = client.post("/api/holdings/trades", json={"action": "buy", "code": "ptl", "price": 50, "qty": 100,
                                                       "date": TODAY.isoformat(), "stop": 46})
        assert res.status_code == 200 and "Bought PTL 100 @ 50.00" in res.json()["reply"]
        assert "/undo" not in res.json()["reply"]
        bad = client.post("/api/holdings/trades", json={"action": "sell", "code": "PTL", "price": 55, "qty": 500})
        assert bad.status_code == 400 and "can't sell 500" in bad.json()["detail"]
        assert client.post("/api/holdings/trades", json={"action": "buy", "code": "PTL"}).status_code == 400

        v = client.get("/api/holdings").json()
        (p,) = v["positions"]
        assert (p["code"], p["shares"], p["cost"], p["stop"], p["default_stop"]) == ("PTL", 100, 50, 46, False)
        assert v["totals"]["pnl"] == 0 and v["last_close"]["PTL"] == 50 and "PTL" in v["codes"]
        assert [r["action"] for r in v["ledger"]] == ["stop", "buy"]            # newest first
        assert all(r["source"] == "dashboard" for r in v["ledger"])

        stop_id = v["ledger"][0]["id"]
        assert client.delete(f"/api/holdings/trades/{stop_id}").json() == {"ok": True}
        assert client.delete(f"/api/holdings/trades/{stop_id}").status_code == 404
        assert client.get("/api/holdings").json()["positions"][0]["default_stop"] is True
        assert "Removed: PTL bought 100 @ 50.00" in client.post("/api/holdings/undo").json()["reply"]
        assert client.get("/api/holdings").json()["positions"] == []
    finally:
        api.app.dependency_overrides.clear()
