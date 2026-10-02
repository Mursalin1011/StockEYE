"""Smoke tests for the web API against the local database (skipped if there is none)."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from dse_screener.config import load_settings  # noqa: E402

if not load_settings().resolve(load_settings().paths.db).exists():
    pytest.skip("no local database", allow_module_level=True)

from dse_screener.api.app import app  # noqa: E402

client = TestClient(app)


def test_meta_and_runs():
    meta = client.get("/api/meta").json()
    assert {"swing", "position"} <= {p["name"] for p in meta["profiles"]}
    assert "quiet_accumulation" in meta["strategies"]
    assert isinstance(client.get("/api/runs").json(), list)


def test_stock_list_and_detail():
    rows = client.get("/api/stocks").json()
    assert len(rows) >= 20 and {"code", "close", "pass_swing"} <= set(rows[0])
    d = client.get("/api/stocks/GP").json()
    assert d["company"]["code"] == "GP" and d["news"] and d["annual"]


def test_chart_has_bars_indicators_and_valid_markers():
    c = client.get("/api/stocks/SQURPHARMA/chart?profile=swing&days=250").json()
    assert len(c["bars"]) == 250 == len(c["indicators"])
    assert all(b["open"] is not None and b["high"] >= b["low"] for b in c["bars"])
    times = {b["time"] for b in c["bars"]}
    assert all(m["time"] in times for m in c["markers"])          # markers fall on chart bars
    rsi = [r["rsi"] for r in c["indicators"] if r["rsi"] is not None]
    assert rsi and all(0 <= v <= 100 for v in rsi)


def test_unknown_things_are_404():
    assert client.get("/api/stocks/NOPE").status_code == 404
    assert client.get("/api/quality/nope").status_code == 404
    assert client.get("/api/screens/1999-01-01").status_code == 404


def test_quality_view():
    q = client.get("/api/quality/swing").json()
    assert q["rows"] and "category" in q["rules"]


def test_casestudy_reproduces_the_ptl_case():
    """docs/05: swing base breakout on 24 Feb 2026, entry 53.7 (25 Feb open), shortlisted 25 Feb at score 82."""
    cs = client.get("/api/casestudy/PTL?profile=swing&start=2025-11-01&end=2026-10-01").json()
    bb = [s for s in cs["signals"] if s["strategy"] == "base_breakout" and s["status"] == "signal"]
    feb = next(s for s in bb if s["date"] == "2026-02-24")
    assert feb["entry"] == pytest.approx(53.7, abs=0.05)
    assert feb["cut_date"] == "2026-02-25" and feb["best_score"] == pytest.approx(82.4, abs=0.1)
    times = {b["time"] for b in cs["chart"]["bars"]}
    assert cs["chart"]["markers"] and all(m["time"] in times for m in cs["chart"]["markers"])
    assert cs["quality_passed"] is True
    assert client.get("/api/casestudy/NOPE").status_code == 404
