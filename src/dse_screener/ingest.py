"""Pull end-of-day data from a source into the database."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Settings
from .db import Database
from .sources.base import PriceSource

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    rows: int = 0
    chunks_ok: int = 0
    chunks_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - years, day=28)


def date_chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    chunks, cur = [], start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def backfill(
    db: Database,
    source: PriceSource,
    settings: Settings,
    start: date | None = None,
    end: date | None = None,
    resume: bool = True,
) -> IngestReport:
    """Download history in chunks, oldest first (the oldest data disappears first)."""
    end = end or settings.today()
    start = start or years_before(end, settings.ingest.backfill_years)
    done = db.completed_chunks(source.name) if resume else set()
    report = IngestReport()

    for chunk_start, chunk_end in date_chunks(start, end, settings.ingest.chunk_days):
        # Always refetch the most recent chunk: it may have been partial last time.
        if (chunk_start.isoformat(), chunk_end.isoformat()) in done and chunk_end < end:
            report.chunks_skipped += 1
            continue
        try:
            df = source.fetch_range(chunk_start, chunk_end)
        except Exception as exc:  # keep going; one bad chunk shouldn't stop the backfill
            msg = f"{chunk_start}..{chunk_end}: {exc}"
            log.error("Backfill chunk failed: %s", msg)
            db.log_ingest(source.name, chunk_start, chunk_end, 0, "error", str(exc))
            report.errors.append(msg)
            continue
        n = db.upsert_prices(df, source.name)
        db.log_ingest(source.name, chunk_start, chunk_end, n, "ok" if n else "empty")
        report.rows += n
        report.chunks_ok += 1
        log.info("%s..%s: %d rows, %d trading days", chunk_start, chunk_end, n, df["date"].nunique())
    return report


def ingest_day(db: Database, source: PriceSource, settings: Settings, day: date) -> tuple[int, bool]:
    """Fetch one trading day. Returns (rows, complete)."""
    df = source.fetch_range(day, day)
    n = db.upsert_prices(df, source.name)
    complete = n >= settings.ingest.min_rows_per_day
    status = "ok" if complete else ("empty" if n == 0 else "incomplete")
    db.log_ingest(source.name, day, day, n, status)
    return n, complete
