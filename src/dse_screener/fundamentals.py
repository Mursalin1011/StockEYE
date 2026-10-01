"""Refresh company fundamentals + news, and rebuild corporate actions from them."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pandas as pd

from .corporate_actions import build_corporate_actions, extract_dividend_events, reconcile_with_history
from .db import Database
from .sources.dse_company import DseCompanySource
from .sources.dse_news import DseNewsSource

log = logging.getLogger(__name__)


@dataclass
class FundamentalsReport:
    companies: int = 0
    news_added: int = 0
    errors: list[str] = field(default_factory=list)


def refresh_fundamentals(
    db: Database,
    company_src: DseCompanySource,
    news_src: DseNewsSource,
    codes: list[str],
    company_pages: bool = True,
    news: bool = True,
) -> FundamentalsReport:
    report = FundamentalsReport()
    for i, code in enumerate(codes, 1):
        try:
            if company_pages:
                db.save_company(company_src.fetch(code))
                report.companies += 1
            added = db.upsert_news(news_src.fetch(code)) if news else 0
            report.news_added += added
            log.info("[%d/%d] %s: %s%d new news items", i, len(codes), code,
                     "profile ok, " if company_pages else "", added)
        except Exception as exc:  # one company failing shouldn't stop the rest
            log.error("[%d/%d] %s failed: %s", i, len(codes), code, exc)
            report.errors.append(f"{code}: {exc}")
    return report


NOT_LISTED_SHARES = re.compile(r"^TB\d|BOND|SUKUK|GSB|^ZCB")   # T-bills and bonds: no company page needed


def discover_instruments(
    db: Database, company_src: DseCompanySource, news_src: DseNewsSource, news_for_equities: bool = True
) -> FundamentalsReport:
    """Fetch company pages for every traded instrument we don't know yet (new listings included),
    so instrument type (Equity / Mutual Fund) and category come from DSE itself. Then fetch news
    for the new equities, which the dividend/bonus adjustment needs."""
    traded = [r[0] for r in db.conn.execute("SELECT DISTINCT code FROM daily_prices")]
    known = set(db.load_companies()["code"])
    todo = sorted(c for c in traded if c not in known and not NOT_LISTED_SHARES.search(c))
    log.info("Discovering %d instruments", len(todo))
    report = refresh_fundamentals(db, company_src, news_src, todo, company_pages=True, news=False)
    if news_for_equities:
        comp = db.load_companies(todo)
        equities = comp.loc[comp["instrument_type"] == "Equity", "code"].tolist()
        log.info("Fetching news for %d new equities", len(equities))
        news = refresh_fundamentals(db, company_src, news_src, equities, company_pages=False, news=True)
        report.news_added, report.errors = news.news_added, report.errors + news.errors
        rebuild_corporate_actions(db, equities)
    return report


def rebuild_corporate_actions(db: Database, codes: list[str]) -> pd.DataFrame:
    events = extract_dividend_events(db.load_news(codes))
    events = reconcile_with_history(events, db.load_table("dividend_history", codes))
    companies = db.load_companies(codes)
    face_values = dict(zip(companies["code"], companies["face_value"]))
    actions = build_corporate_actions(events, db.load_prices(codes), face_values)
    db.replace_corporate_actions(actions, codes)
    return actions
