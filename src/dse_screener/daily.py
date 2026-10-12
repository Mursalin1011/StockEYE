"""The 3pm job: wait for today's data -> refresh news -> screen every profile -> deliver -> rebuild big moves."""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from . import engine, fundamentals, holdings, ingest, market, moves, quality, report, rules
from .config import Settings, list_profiles, load_profile
from .universes import universe_codes
from .db import Database
from .sources import (DseArchiveSource, DseCompanySource, DseMarketStatsSource, DseMarketSummarySource,
                      DseNewsSource, PriceSource)
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
    official: Callable[[date], bool] | None = None,
    inbox: Callable[[], object] | None = None,
) -> DailyOutcome:
    """`wait=False` is for re-running a past day: no waiting, no retries.
    `inbox` reads your Telegram commands (/bought, /sold) first, so the positions section is current.
    clock/sleep/archive/refresh/official are injectable for tests."""
    cfg = settings.daily
    clock = clock or (lambda: datetime.now(settings.tz))
    day = day or clock().date()
    if not cfg.is_trading_weekday(day):
        log.info("%s is not a trading weekday, nothing to do", day)
        return DailyOutcome("not_trading_day", day)

    client = PoliteClient(settings.http, settings.resolve(settings.paths.raw))
    archive = archive or DseArchiveSource(client, settings.sources.dse_archive.base_url)
    refresh = refresh or (lambda codes, d: _refresh(settings, db, client, codes, d))
    official = official or (lambda d: market.refresh_day(
        db, DseMarketSummarySource(client, settings.sources.dse_market_summary.base_url),
        DseMarketStatsSource(client, settings.sources.dse_market.base_url), d))

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
    codes = sorted({c for p in profiles for c in universe_codes(p.universe, db)})
    refresh(codes, day)

    results = []
    for profile in profiles:
        res = engine.run_profile(db, settings, profile, day)
        db.save_screen(res, profile.model_dump_json(by_alias=True))
        results.append((profile, res))

    _research_housekeeping(settings, db)
    _save_official_totals(official, day, retries=2 if wait else 0, sleep=sleep, pause_s=cfg.retry_every_min * 60)
    pick_codes = sorted({c for _, r in results for c in r.picks["code"]})
    text = report.build_daily_report(
        day, results, report.market_summary(db, day), report.recent_news(db, pick_codes, day, settings.report),
        settings.report, report.pick_quotes(db, pick_codes, day), _positions(settings, db, day, results, inbox),
    )
    deliver(text)
    _rebuild_moves(settings, db)
    return DailyOutcome("sent", day, text, {p.name: r.picks["code"].tolist() for p, r in results})


def _positions(settings: Settings, db: Database, day: date, results, inbox) -> str | None:
    """The "your positions" section. Never blocks the summary: failures are only logged."""
    if inbox:
        try:
            inbox()
        except Exception:  # noqa: BLE001
            log.exception("Reading Telegram commands failed (summary continues)")
    try:
        return holdings.render(holdings.review(db, settings, day, results))
    except Exception:  # noqa: BLE001
        log.exception("Holdings check failed (summary continues without it)")
        return "<b>▸ 💼 YOUR POSITIONS</b>\n⚠️ The check failed today, see the log."


def _refresh(settings: Settings, db: Database, client: PoliteClient, codes: list[str], day: date) -> None:
    """Keep company data and news fresh without making the 3pm job slow:
    - new listings: company page + news (usually none)
    - company pages: the stalest N per day, so every stock is refreshed about weekly
    - news: daily, only for stocks that pass at least one profile's quality filter (the ones that
      can become picks, and whose dividend/bonus adjustment must be current)"""
    cfg = settings.daily
    company_src = DseCompanySource(client, settings.sources.dse_company.base_url)
    news_src = DseNewsSource(client, settings.sources.dse_news.base_url)
    fundamentals.discover_instruments(db, company_src, news_src)
    held = holdings.tracked_codes(db, settings, day)      # your positions, even if they fail the quality filter
    codes = sorted(set(codes) | set(_all_universe_codes(settings, db)) | set(held))

    companies = db.load_companies(codes)
    fetched = pd.to_datetime(companies.set_index("code")["fetched_at"], utc=True).dt.date
    stale_before = day - timedelta(days=cfg.refresh_company_pages_every_days)
    stale = sorted((c for c in codes if c not in fetched.index or fetched[c] <= stale_before),
                   key=lambda c: fetched.get(c, date.min))[: cfg.company_pages_per_day]
    if stale:
        log.info("Refreshing company pages for %d stocks (stalest first)", len(stale))
        fundamentals.refresh_fundamentals(db, company_src, news_src, stale, company_pages=True, news=False)

    news_codes = sorted(set(_screenable(settings, db, codes)) | set(held))
    if cfg.refresh_news and news_codes:
        log.info("Refreshing news for %d quality-passing stocks", len(news_codes))
        fundamentals.refresh_fundamentals(db, company_src, news_src, news_codes, company_pages=False, news=True)
    fundamentals.rebuild_corporate_actions(db, codes)


def _save_official_totals(fetch: Callable[[date], bool], day: date, retries: int,
                          sleep: Callable[[float], None], pause_s: float) -> None:
    """Store DSE's official day totals (block trades included) for the summary's turnover line.
    Never blocks the summary: without them the turnover falls back to the archive sum,
    labelled as excluding block trades."""
    for attempt in range(retries + 1):
        if fetch(day):
            return
        if attempt < retries:
            log.info("%s: DSE official totals not published yet, retrying", day)
            sleep(pause_s)
    log.warning("%s: no official market totals from DSE, turnover will exclude block trades", day)


def _research_housekeeping(settings: Settings, db: Database) -> None:
    """Import PDFs dropped in the research inbox and score AI calls whose horizon has passed.
    Never blocks the daily summary: research is optional (needs pypdf) and failures are only logged."""
    try:
        from .research import documents, ledger

        added = [r for r in documents.scan_inbox(db, settings) if r.created]
        scored = ledger.score_calls(db, settings)
        if added or scored:
            log.info("Research: %d new document(s) imported, %d AI call(s) scored", len(added), scored)
    except Exception:  # noqa: BLE001
        log.exception("Research housekeeping failed (daily summary continues)")


def _rebuild_moves(settings: Settings, db: Database) -> None:
    """Refresh the dashboard's Big moves page with today's prices (takes about a minute, after the summary is out).
    Failures are only logged: the API rebuilds it on the next visit anyway."""
    try:
        moves.latest(db, settings)
    except Exception:  # noqa: BLE001
        log.exception("Big moves scan failed (the dashboard rebuilds it on the next visit)")


def _all_universe_codes(settings: Settings, db: Database) -> list[str]:
    return sorted({c for n in list_profiles(settings) for c in universe_codes(load_profile(n).universe, db)})


def _screenable(settings: Settings, db: Database, codes: list[str]) -> list[str]:
    """Codes that pass the quality filter of at least one profile (from stored data)."""
    metrics = quality.compute_quality_metrics(db, codes)
    keep: set[str] = set()
    for name in list_profiles(settings):
        qf = load_profile(name).filters.get("quality")
        res = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})
        keep |= set(res.index[res["passed"]])
    return sorted(keep)


def _sleep_until(clock, sleep, target, why: str) -> None:
    while (now := clock()).time() < target:
        wait = (datetime.combine(now.date(), target, now.tzinfo) - now).total_seconds()
        log.info("Waiting %.0f min for %s (%s)", wait / 60, target.strftime("%H:%M"), why)
        sleep(min(wait, 600))
