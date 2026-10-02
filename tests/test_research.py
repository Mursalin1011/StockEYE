import io
import json
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pypdf")
from pypdf import PdfWriter  # noqa: E402

from dse_screener.config import load_settings  # noqa: E402
from dse_screener.db import Database  # noqa: E402
from dse_screener.research import documents, ledger, render, review  # noqa: E402
from dse_screener.research.documents import SourceRule  # noqa: E402

COMPANIES = pd.DataFrame({
    "code": ["ONEBANKPLC", "IBNSINA", "PTL", "BBS", "GP"],
    "name": ["One Bank PLC", "The IBN SINA  Pharmaceutical Industry PLC", "Paramount Textile PLC.",
             "Bangladesh Building Systems Ltd.", "Grameenphone Ltd."],
})


def _pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path):
    settings = load_settings()
    settings.research.store = tmp_path / "store"
    settings.research.inbox = tmp_path / "inbox"
    db = Database(tmp_path / "t.sqlite")
    yield settings, db
    db.close()


# --- documents ---------------------------------------------------------------

def test_published_date_from_name_or_upload_stamp():
    assert documents.published_date("SSL-Newsflash-October-1-2026-1790826012847.pdf") == date(2026, 10, 1)
    assert documents.published_date("SSL-Daily-Market-Review-September-30-2026-17907.pdf") == date(2026, 9, 30)
    # no date in the name: the 13-digit upload stamp (ms since 1970)
    assert documents.published_date("FINAL-Monetary-Policy-Review-Q2-FY27-1790850326226.pdf") == date(2026, 10, 1)
    assert documents.published_date("notes.pdf", fallback=date(2026, 1, 2)) == date(2026, 1, 2)


def test_classify_first_matching_rule_wins():
    rules = [SourceRule(name="NF", doc_type="newsflash", match="Newsflash"),
             SourceRule(name="Any SSL", doc_type="other", match="market-reports/")]
    assert documents.classify("https://x/market-reports/SSL-Newsflash-October-1-2026.pdf", rules).name == "NF"
    assert documents.classify("https://x/market-reports/Other.pdf", rules).name == "Any SSL"
    assert documents.classify("random.pdf", rules) is None


def test_mentioned_codes_finds_codes_and_company_names():
    text = ("PTL 85.7 6.06%\nONE Bank PLC has received approval... IBN Sina Pharma's profit jumps\n"
            "Source: BBS, BB, IMF. GPS and GP-style words")
    found = documents.mentioned_codes(text, COMPANIES, ignore=["BBS"])
    # PTL as a code, One Bank by name, Ibn Sina by its distinctive first words; BBS ignored as a bare token
    assert found == ["IBNSINA", "ONEBANKPLC", "PTL"]


def test_add_document_dedupes_by_content_and_rejects_non_pdfs(env):
    settings, db = env
    data = _pdf()
    a = documents.add_document(db, settings, data, "SSL-Newsflash-October-1-2026-1.pdf")
    b = documents.add_document(db, settings, data, "renamed.pdf")
    assert a.created and not b.created and a.doc_id == b.doc_id
    assert a.doc_type == "newsflash" and a.published == "2026-10-01"
    with pytest.raises(ValueError):
        documents.add_document(db, settings, b"<html>", "x.pdf")
    docs = documents.load_docs(db)
    assert len(docs) == 1 and not docs["reviewed"].iloc[0]


def test_scan_inbox_imports_pdfs(env):
    settings, db = env
    settings.research.inbox.mkdir(parents=True)
    (settings.research.inbox / "a.pdf").write_bytes(_pdf())
    (settings.research.inbox / "b.txt").write_text("not a pdf")
    res = documents.scan_inbox(db, settings)
    assert [r.filename for r in res] == ["a.pdf"]


# --- review ------------------------------------------------------------------

def _answer(codes=("PTL",)) -> dict:
    return {
        "headline": "Policy rate held; liquidity easing.",
        "market_view": {"stance": "neutral", "confidence": 55, "horizon_days": 20, "summary": "s",
                        "drivers": ["d"], "risks": ["r"]},
        "macro": [{"topic": "MPS", "summary": "held at 9.5%", "impact": "mixed", "sectors": ["Bank"], "source": "MPR p2"}],
        "sectors": [{"sector": "Textile", "stance": "bullish", "confidence": 58, "rationale": "x"}],
        "calls": [{"code": c, "company": c, "stance": "bullish", "horizon_days": 20, "confidence": 62, "thesis": "t",
                   "evidence": ["e (Market review p1)"], "invalidation": "close below 75", "stockeye_view": "silent",
                   "stockeye_note": "", "priced_in": "partly"} for c in codes],
        "watch": [{"code": "PTL", "what_to_watch": "block trades"}],
        "noise": ["Farmers card pilot"], "data_gaps": [], "sources_used": [{"document": "MPR", "key_points": ["k"]}],
    }


class FakeClient:
    def __init__(self, answer: dict, stop_reason="end_turn"):
        self.answer, self.stop_reason, self.requests = answer, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append(kw)
        msg = SimpleNamespace(
            stop_reason=self.stop_reason, stop_details=None, model=kw["model"],
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(self.answer))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=500))
        return _Ctx(msg)


class _Ctx:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def _seed_market(db, codes=("PTL", "GP", "AAA"), days=80):
    dates = pd.bdate_range("2026-06-01", periods=days)
    rows = []
    for k, code in enumerate(codes):
        close = 100 * (1 + 0.002 * (k + 1)) ** np.arange(days)
        rows.append(pd.DataFrame({"code": code, "date": dates.date, "open": close, "high": close, "low": close,
                                  "close": close, "ltp": close, "ycp": close, "trades": 10, "value_mn": 5.0,
                                  "volume": 1000}))
    db.upsert_prices(pd.concat(rows), "test")
    with db.conn:
        db.conn.executemany("INSERT INTO companies (code, name, instrument_type, fetched_at) VALUES (?, ?, 'Equity', 'x')",
                            [(c, c) for c in codes])
    return dates


def test_review_sends_pdfs_guide_and_context_and_stores_calls(env):
    settings, db = env
    _seed_market(db)
    doc = documents.add_document(db, settings, _pdf(), f"SSL-Newsflash-{date.today():%B-%d-%Y}-1.pdf")
    client = FakeClient(_answer(codes=("PTL", "NOPE")))
    run = review.run_review(db, settings, client=client)
    req = client.requests[0]
    assert req["model"] == settings.research.model and req["fallbacks"] == "default"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "standing instructions" in req["system"][0]["text"]          # ANALYST.md
    assert req["system"][-1]["cache_control"] == {"type": "ephemeral"}
    content = req["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert '"as_of":' in content[-1]["text"]                              # StockEYE context
    # unknown codes are dropped and noted; the rest go to the ledger
    assert [c.code for c in run.review.calls] == ["PTL"]
    assert any("NOPE" in g for g in run.review.data_gaps)
    calls = ledger.load_calls(db)
    assert calls[["code", "stance", "horizon_days"]].values.tolist() == [["PTL", "bullish", 20]]
    assert documents.load_docs(db, [doc.doc_id])["reviewed"].iloc[0]
    # nothing new to review now
    with pytest.raises(ValueError):
        review.run_review(db, settings, client=client)


def test_review_refusal_and_truncation_raise(env):
    settings, db = env
    _seed_market(db)
    d = documents.add_document(db, settings, _pdf(), "x.pdf")
    for reason in ("refusal", "max_tokens"):
        with pytest.raises(RuntimeError):
            review.run_review(db, settings, [d.doc_id], client=FakeClient(_answer(), stop_reason=reason))
    assert review.load_reviews(db).empty


def test_dry_run_writes_request_without_pdf_bytes(env):
    settings, db = env
    _seed_market(db)
    d = documents.add_document(db, settings, _pdf(), "x.pdf")
    run = review.run_review(db, settings, [d.doc_id], dry_run=True)
    req = json.loads(run.request_file.read_text(encoding="utf-8"))
    assert req["messages"][0]["content"][0]["source"]["data"] == "<omitted>"
    assert review.load_reviews(db).empty


def test_render_telegram_lists_calls_and_disclaimer():
    r = review.Review.model_validate(_answer())
    html = render.telegram_html(r, "2026-10-01", ["SSL Newsflash"])
    assert "PTL" in html and "not investment advice" in html and "wrong if" in html


# --- ledger ------------------------------------------------------------------

def test_score_calls_against_the_basket(env):
    settings, db = env
    dates = _seed_market(db)          # PTL grows slowest of the three, AAA fastest
    as_of = dates[30].strftime("%Y-%m-%d")      # 30 + 60 days > 80 stored days
    ledger.save_calls(db, 1, as_of, [
        {"code": "PTL", "stance": "bearish", "horizon_days": 20, "confidence": 60, "thesis": "lags"},
        {"code": "AAA", "stance": "bullish", "horizon_days": 5, "confidence": 70, "thesis": "leads"},
        {"code": "GP", "stance": "neutral", "horizon_days": 5, "confidence": 50, "thesis": "-"},
        {"code": "GP", "stance": "bullish", "horizon_days": 60, "confidence": 55, "thesis": "too far"},
    ])
    n = ledger.score_calls(db, settings, basket=["PTL", "GP", "AAA"])
    calls = ledger.load_calls(db).set_index(["code", "stance"])
    assert n == 2                                   # neutral not scored; 60 days not over yet
    assert calls.loc[("PTL", "bearish"), "correct"] == 1 and calls.loc[("AAA", "bullish"), "correct"] == 1
    tr = ledger.track_record(db)
    assert tr["calls_scored"] == 2 and tr["hit_rate_pct"] == 100.0


# --- evening job -------------------------------------------------------------

def test_evening_is_quiet_without_new_documents(env):
    from dse_screener.research.evening import run_evening

    settings, db = env
    sent = []
    assert run_evening(db, settings, sent.append, client=FakeClient(_answer())) == "nothing_new"
    assert sent == []


def test_evening_reviews_new_inbox_documents_and_sends(env):
    from dse_screener.research.evening import run_evening

    settings, db = env
    _seed_market(db)
    settings.research.inbox.mkdir(parents=True)
    (settings.research.inbox / f"SSL-Newsflash-{date.today():%B-%d-%Y}-1.pdf").write_bytes(_pdf())
    sent = []
    assert run_evening(db, settings, sent.append, client=FakeClient(_answer())) == "sent"
    assert len(sent) == 1 and "AI review" in sent[0] and "PTL" in sent[0]
    # the same file again: already reviewed, nothing sent
    assert run_evening(db, settings, sent.append, client=FakeClient(_answer())) == "nothing_new"
    assert len(sent) == 1


def test_evening_without_key_says_documents_are_waiting(env, monkeypatch):
    from dse_screener.research.evening import run_evening

    settings, db = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    settings.anthropic.api_key = ""
    documents.add_document(db, settings, _pdf(), f"SSL-Newsflash-{date.today():%B-%d-%Y}-1.pdf")
    sent = []
    assert run_evening(db, settings, sent.append) == "no_key"
    assert "API key" in sent[0]
