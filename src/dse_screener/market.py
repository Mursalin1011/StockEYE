"""DSE's official market totals (block trades included) -> market_daily.

daily_prices comes from the day-end archive, which leaves out block trades, so its sum
understates turnover. The summary line uses these totals instead.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from .db import Database
from .ingest import date_chunks
from .sources import DseMarketStatsSource, DseMarketSummarySource

log = logging.getLogger(__name__)


def backfill(db: Database, source: DseMarketSummarySource, start: date, end: date, chunk_days: int = 31) -> int:
    """Official totals for every trading day in [start, end] (the API keeps ~2 years)."""
    rows = 0
    for chunk_start, chunk_end in date_chunks(start, end, chunk_days):
        df = source.fetch_range(chunk_start, chunk_end)
        rows += db.upsert_market_days(df)
        log.info("%s..%s: %d days of official totals", chunk_start, chunk_end, len(df))
    return rows


def refresh_day(db: Database, summary: DseMarketSummarySource, stats: DseMarketStatsSource, day: date) -> bool:
    """The day's official totals from both sources: the summary archive (last 10 days, so a missed
    day heals itself) and the statistics page (block trades and breadth, latest day only).
    True once `day` is stored. Failures are only logged."""
    stored = False
    try:
        df = summary.fetch_range(day - timedelta(days=10), day)
        db.upsert_market_days(df)
        stored = day in set(df["date"])
    except Exception:  # noqa: BLE001
        log.exception("DSE market summary fetch failed")
    try:
        latest = stats.fetch_latest()
        if latest and latest["date"] == day:
            db.upsert_market_day(latest)
            stored = True
    except Exception:  # noqa: BLE001
        log.exception("DSE market statistics fetch failed")
    return stored
