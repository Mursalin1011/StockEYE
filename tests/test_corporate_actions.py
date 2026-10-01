from datetime import date

import pandas as pd
import pytest

from dse_screener.corporate_actions import extract_dividend_events, parse_loose_date, reconcile_with_history
from dse_screener.sources.dse_company import parse_dividend_history


def _news(*bodies):
    return pd.DataFrame(
        [{"code": "EBL", "post_date": date(2025, 3, 25), "title": "EBL: Dividend Declaration", "body": b}
         for b in bodies]
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("May 06, 2026", date(2026, 5, 6)),
        ("23-Apr-2025", date(2025, 4, 23)),
        ("25.08.2025", date(2025, 8, 25)),
        ("June 5th, 2025.", date(2025, 6, 5)),
        ("nonsense", None),
    ],
)
def test_parse_loose_date(text, expected):
    assert parse_loose_date(text) == expected


def test_extracts_both_declaration_styles():
    # Real wording from DSE news (2026 and 2025 EBL declarations)
    news = _news(
        "The Board of Directors has recommended Cash Dividend @ 25.00% and Stock Dividend @ 3.00% "
        "for the year ended December 31, 2025. Date of AGM: June 11, 2026. Record Date: May 06, 2026.",
        "The Board of Directors has recommended 17.50% Cash Dividend and 17.50% stock dividend for the "
        "year ended December 31, 2024. Date of AGM: 21-May-2025. Record Date: 23-Apr-2025.",
    )
    ev = extract_dividend_events(news).set_index("record_date")
    assert ev.loc[date(2026, 5, 6), ["cash_pct", "stock_pct"]].tolist() == [25.0, 3.0]
    assert ev.loc[date(2025, 4, 23), ["cash_pct", "stock_pct"]].tolist() == [17.5, 17.5]


def test_interim_cash_dividend():
    ev = extract_dividend_events(
        _news("The Board has declared 140% interim cash dividend for the half year ended June 30, 2025. "
              "Record date: 25.08.2025.")
    )
    assert ev.iloc[0][["cash_pct", "stock_pct"]].tolist() == [140.0, 0.0]


@pytest.mark.parametrize(
    "body, cash, stock",
    [
        # PUBALIBANK / BRACBANK 2025: "Cash and ... Stock Dividend"
        ("The Board of Directors has recommended 12.50% Cash and 12.50% Stock Dividend for the year ended "
         "December 31, 2024. Date of AGM: 18.06.2025. Record Date: 22.05.2025.", 12.5, 12.5),
        # BATBC 2025: percentage after the words
        ("The Board of Directors has declared Final Cash Dividend 150% i.e. BDT. 15 per share (i.e. Total "
         "Dividend 300% i.e. BDT 30 per share including Interim Cash Dividend 150% i.e. 15 per share which "
         "was already paid in December 2024). Record Date: 26.02.2025.", 150.0, 0.0),
        # GP final: the first % is this declaration, later ones are year totals
        ("The Board of Directors has recommended 105% Final Cash Dividend for the year ended December 31, "
         "2025 (i.e., total 215% Cash Dividend for the year 2025). Record Date: 03.03.2026.", 105.0, 0.0),
    ],
)
def test_real_wordings(body, cash, stock):
    ev = extract_dividend_events(_news(body))
    assert ev.iloc[0][["cash_pct", "stock_pct"]].tolist() == [cash, stock]


def test_interim_declaration_linked_to_later_record_date_notice():
    # GP 2025: declaration has no record date; it comes in a suspension notice weeks later.
    news = pd.DataFrame([
        {"code": "GP", "post_date": date(2025, 7, 17), "title": "GP: Declaration of Interim Dividend",
         "body": "The Board of Directors of the company has declared Interim Cash Dividend for the year 2025 "
                 "at the rate of 110% of the paid-up capital of the Company (BDT 11.00 per share)."},
        {"code": "GP", "post_date": date(2025, 8, 12), "title": "GP: Suspension for Record Date",
         "body": "Trading of the shares of the company will remain suspended on record date i.e., "
                 "13.08.2025 for entitlement of interim dividend."},
    ])
    ev = extract_dividend_events(news).iloc[0]
    assert ev["record_date"] == date(2025, 8, 13) and ev["cash_pct"] == 110.0


def test_record_date_notice_without_word_dividend_is_linked():
    # GP 2026: "remain suspended on record date i.e., 12-Aug-2026." (no "dividend")
    news = pd.DataFrame([
        {"code": "GP", "post_date": date(2026, 7, 15), "title": "GP: Declaration of Interim Dividend",
         "body": "The Board of Directors of the company has declared Interim Cash Dividend for the year 2026 "
                 "at the rate of 105% of the paid-up capital of the Company."},
        {"code": "GP", "post_date": date(2026, 8, 11), "title": "GP: Suspension for Record Date",
         "body": "Trading of the shares of the company will remain suspended on record date i.e., 12-Aug-2026."},
    ])
    ev = extract_dividend_events(news).iloc[0]
    assert ev["record_date"] == date(2026, 8, 12) and ev["fiscal_year"] == 2026


def test_agm_revision_taken_from_company_history():
    # PUBALIBANK FY2025: Board recommended 15% + 15%, AGM approved 10% cash + 20% stock
    ev = extract_dividend_events(pd.DataFrame([
        {"code": "PUBALIBANK", "post_date": date(2026, 4, 30), "title": "PUBALIBANK: Dividend Declaration",
         "body": "The Board of Directors has recommended 15% Cash and 15% Stock Dividend for the year ended "
                 "December 31, 2025. Record Date: 20.05.2026."},
    ]))
    history = pd.DataFrame([{"code": "PUBALIBANK", "year": 2025, "cash_pct": 10.0, "stock_pct": 20.0}])
    out = reconcile_with_history(ev, history).iloc[0]
    assert (out["cash_pct"], out["stock_pct"], out["revised"]) == (10.0, 20.0, True)


def test_reconcile_leaves_interim_years_alone():
    # GP: interim + final in one fiscal year; page shows the year's total, so don't overwrite
    ev = pd.DataFrame([
        {"code": "GP", "record_date": date(2025, 8, 13), "fiscal_year": 2025, "cash_pct": 110.0,
         "stock_pct": 0.0, "news_date": date(2025, 7, 17), "title": "", "revised": False},
        {"code": "GP", "record_date": date(2026, 3, 3), "fiscal_year": 2025, "cash_pct": 105.0,
         "stock_pct": 0.0, "news_date": date(2026, 2, 3), "title": "", "revised": False},
    ])
    history = pd.DataFrame([{"code": "GP", "year": 2025, "cash_pct": 215.0, "stock_pct": 0.0}])
    out = reconcile_with_history(ev, history)
    assert out["cash_pct"].tolist() == [110.0, 105.0] and not out["revised"].any()

    # Only the final is in our news window (interim was earlier): still don't overwrite cash
    out = reconcile_with_history(ev.iloc[[1]].reset_index(drop=True), history)
    assert out.iloc[0]["cash_pct"] == 105.0 and not out.iloc[0]["revised"]


def test_ignores_news_without_dividend_or_record_date():
    ev = extract_dividend_events(
        _news("Trading of the shares will remain suspended on record date i.e., 06.05.2026.",
              "The Board has recommended no dividend for the year. Record Date: May 06, 2026.")
    )
    assert ev.empty


def test_parse_dividend_history():
    assert parse_dividend_history("215% 2025, 330% 2024, 17.50 2020,200% 2005") == {
        2025: 215.0, 2024: 330.0, 2020: 17.5, 2005: 200.0
    }
    assert parse_dividend_history("-") == {}
