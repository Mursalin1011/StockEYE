"""The 3pm job: wait for today's data -> refresh news -> screen every profile -> deliver."""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from . import engine, fundamentals, ingest, report
from .config import Settings, list_profiles, load_profile, load_universe
from .db import Database
from .sources import DseArchiveSource, DseCompanySource, DseNewsSource, PriceSource
from .sources.http import PoliteClient

log = logging.getLogger(__name__)


@dataclass
class DailyOutcome:
    status: str                    # not_trading_day | no_data | sent
    day: date
    message: str | None = None
    picks: dict[str, list[str]] = field(default_factory=dict)


def run_daily(
    settings: Settings,
    db: Database,
    deliver: Callable[[str], object],
    day: date | None = None,
    wait: bool = True,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = _time.sleep,
    archive: PriceSource | None = None,
    refresh: Callable[[list[str], date], None] | None = None,
) -> DailyOutcome:
    """`wait=False` is for re-running a past day: no waiting, no retries.
    clock/sleep/archive/refresh are injectable for tests."""
    cfg = settings.daily
    clock = clock or (lambda: datetime.now(settings.tz))
    day = day or clock().date()
    if not cfg.is_trading_weekday(day):
        log.info("%s is not a trading weekday, nothing to do", day)
        return DailyOutcome("not_trading_day", day)

    client = PoliteClient(settings.http, settings.resolve(settings.paths.raw))
    archive = archive or DseArchiveSource(client, settings.sources.dse_archive.base_url)
    refresh = refresh or (lambda codes, d: _refresh(settings, db, client, codes, d))

    if wait:
        _sleep_until(clock, sleep, cfg.not_before, "market close + publishing")
    while True:
        rows, complete = ingest.ingest_day(db, archive, settings, day)
        if complete:
            log.info("%s: %d rows, data complete", day, rows)
            break
        if not wait or clock().time() >= cfg.give_up_at:
            msg = report.build_notice(
                f"DSE Screener · {day:%a %d %b %Y}",
                f"No day-end data from DSE (got {rows} rows). Holiday or outage? Nothing screened today.",
            )
            deliver(msg)
            return DailyOutcome("no_data", day, msg)
        log.info("%s: %d rows so far, retrying in %g min", day, rows, cfg.retry_every_min)
        sleep(cfg.retry_every_min * 60)

    profiles = [load_profile(name) for name in list_profiles(settings)]
    codes = sorted({c for p in profiles for c in load_universe(p.universe).codes})
    refresh(codes, day)

    results = []
    for profile in profiles:
        res = engine.run_profile(db, settings, profile, day)
        db.save_screen(res, profile.model_dump_json(by_alias=True))
        results.append((profile, res))

    pick_codes = sorted({c for _, r in results for c in r.picks["code"]})
    text = report.build_daily_report(
        day, results, report.market_summary(db, day), report.recent_news(db, pick_codes, day, settings.report),
        settings.report,
    )
    deliver(text)
    return DailyOutcome("sent", day, text, {p.name: r.picks["code"].tolist() for p, r in results})


def _refresh(settings: Settings, db: Database, client: PoliteClient, codes: list[str], day: date) -> None:
    cfg = settings.daily
    companies = db.load_companies(codes)
    fetched = pd.to_datetime(companies.set_index("code")["fetched_at"], utc=True).dt.date
    stale_before = day - timedelta(days=cfg.refresh_company_pages_every_days)
    stale = [c for c in codes if c not in fetched.index or fetched[c] <= stale_before]
    company_src = DseCompanySource(client, settings.sources.dse_company.base_url)
    news_src = DseNewsSource(client, settings.sources.dse_news.base_url)
    if stale:
        log.info("Refreshing company pages for %d stocks", len(stale))
        fundamentals.refresh_fundamentals(db, company_src, news_src, stale, company_pages=True, news=False)
    if cfg.refresh_news:
        fundamentals.refresh_fundamentals(db, company_src, news_src, codes, company_pages=False, news=True)
    if stale or cfg.refresh_news:
        fundamentals.rebuild_corporate_actions(db, codes)


def _sleep_until(clock, sleep, target, why: str) -> None:
    while (now := clock()).time() < target:
        wait = (datetime.combine(now.date(), target, now.tzinfo) - now).total_seconds()
        log.info("Waiting %.0f min for %s (%s)", wait / 60, target.strftime("%H:%M"), why)
        sleep(min(wait, 600))
