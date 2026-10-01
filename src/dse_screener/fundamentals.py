"""Refresh company fundamentals + news, and rebuild corporate actions from them."""

from __future__ import annotations

import logging
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


def rebuild_corporate_actions(db: Database, codes: list[str]) -> pd.DataFrame:
    events = extract_dividend_events(db.load_news(codes))
    events = reconcile_with_history(events, db.load_table("dividend_history", codes))
    companies = db.load_companies(codes)
    face_values = dict(zip(companies["code"], companies["face_value"]))
    actions = build_corporate_actions(events, db.load_prices(codes), face_values)
    db.replace_corporate_actions(actions, codes)
    return actions
