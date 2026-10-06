"""DSE's official market totals.

The day-end archive lists only public-market trades per instrument, so summing it misses
block trades: on 2026-10-06 the archive summed to 5,005 mn while DSE's total was 5,642 mn,
the gap being 82 block trades worth 637 mn. Two DSE sources have the official numbers:

- market summary archive (www.dse.com.bd data archives, JSON): totals, DSEX, DS30 and market
  cap per trading day for the last ~2 years. No block split or breadth.
- market statistics (old.dsebd.org/market-statistics.php): totals, block trades and breadth,
  but only for the latest trading day.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from .http import PoliteClient

SUMMARY_FIELDS = {          # API field -> market_daily column
    "totalTrade": "trades",
    "totalVolume": "volume",
    "totalValue": "value_mn",
    "dsex": "dsex",
    "ds30": "ds30",
    "marketCap": "market_cap_mn",   # DSE gives it in mn already
}


class DseMarketSummarySource:
    name = "dse_market_summary"

    def __init__(self, client: PoliteClient, base_url: str):
        self.client = client
        self.base_url = base_url

    def fetch_range(self, start: date, end: date) -> pd.DataFrame:
        """One row per trading day in [start, end]. The API answers at most 400 rows and ignores
        dates outside its ~2-year window (returning other days instead), so callers ask for short
        ranges and the rows are filtered here."""
        text = self.client.get(self.base_url, {"from": start.isoformat(), "to": end.isoformat()})
        self.client.save_raw(self.name, f"{start.isoformat()}_{end.isoformat()}", text)
        return parse_market_summary(text, start, end)


def parse_market_summary(text: str, start: date, end: date) -> pd.DataFrame:
    df = pd.DataFrame(json.loads(text).get("rows") or [])
    if df.empty:
        return pd.DataFrame(columns=["date", *SUMMARY_FIELDS.values()])
    df = df.rename(columns=SUMMARY_FIELDS)[["date", *SUMMARY_FIELDS.values()]]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


class DseMarketStatsSource:
    name = "dse_market"

    def __init__(self, client: PoliteClient, base_url: str):
        self.client = client
        self.base_url = base_url

    def fetch_latest(self) -> dict | None:
        """Totals for the latest trading day DSE has published (check `date`), None if unreadable."""
        html = self.client.get(self.base_url)
        stats = parse_market_stats(html)
        if stats:
            self.client.save_raw(self.name, stats["date"].isoformat(), html)
        return stats


def _int(s: str) -> int:
    return int(float(s.replace(",", "")))


def parse_market_stats(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    pre = soup.find("pre")
    text = pre.get_text() if pre else soup.get_text("\n")

    day = re.search(r"TODAY'S SHARE MARKET\s*:\s*(\d{4}-\d{2}-\d{2})", text)
    totals = re.search(r"NO\. OF TRADES\s*:\s*([\d,]+).*?VOLUME\(Nos\.\)\s*:\s*([\d,]+)"
                       r".*?VALUE\(Tk\)\s*:\s*([\d,.]+)", text, re.S)
    if not day or not totals:
        return None

    # The first breadth block is "All Category"; later ones are per category
    breadth = re.search(r"All Category\s*ISSUES ADVANCED\s*:\s*(\d+)\s*ISSUES DECLINED\s*:\s*(\d+)"
                        r"\s*ISSUES UNCHANGED\s*:\s*(\d+)\s*TOTAL ISSUES TRADED\s*:\s*(\d+)", text)
    # Block section ends with a dashed rule, then: trades, quantity, value (mn)
    block = re.search(r"-{4,}\s+-{4,}\s+-{4,}\s*\n\s*(\d+)\s+(\d+)\s+([\d.]+)", text)
    no_block = block is None and "PRICES IN BLOCK TRANSACTIONS" not in text
    return {
        "date": date.fromisoformat(day.group(1)),
        "trades": _int(totals.group(1)),
        "volume": _int(totals.group(2)),
        "value_mn": float(totals.group(3).replace(",", "")) / 1e6,
        "block_trades": int(block.group(1)) if block else (0 if no_block else None),
        "block_volume": int(block.group(2)) if block else (0 if no_block else None),
        "block_value_mn": float(block.group(3)) if block else (0.0 if no_block else None),
        "advances": int(breadth.group(1)) if breadth else None,
        "declines": int(breadth.group(2)) if breadth else None,
        "unchanged": int(breadth.group(3)) if breadth else None,
        "issues_traded": int(breadth.group(4)) if breadth else None,
    }
