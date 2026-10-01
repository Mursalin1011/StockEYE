"""DSE day-end archive (old.dsebd.org/day_end_archive.php).

One request returns every instrument for a date range. The archive keeps only a
rolling ~2-year window, so everything fetched is stored permanently.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from .base import PRICE_COLUMNS
from .http import PoliteClient

# DSE header -> normalized column
HEADER_MAP = {
    "DATE": "date",
    "TRADING CODE": "code",
    "LTP*": "ltp",
    "HIGH": "high",
    "LOW": "low",
    "OPENP*": "open",
    "CLOSEP*": "close",
    "YCP": "ycp",
    "TRADE": "trades",
    "VALUE (mn)": "value_mn",
    "VOLUME": "volume",
}


class DseArchiveSource:
    name = "dse_archive"

    def __init__(self, client: PoliteClient, base_url: str):
        self.client = client
        self.base_url = base_url

    def fetch_range(self, start: date, end: date, code: str | None = None) -> pd.DataFrame:
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "inst": code or "All Instrument",
            "archive": "data",
        }
        html = self.client.get(self.base_url, params)
        self.client.save_raw(self.name, f"{start.isoformat()}_{end.isoformat()}_{code or 'ALL'}", html)
        return parse_archive_html(html)


def parse_archive_html(html: str) -> pd.DataFrame:
    """Parse the archive results table into normalized columns."""
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in t.find_all("th")]
        if "TRADING CODE" in headers and "YCP" in headers:
            table = t
            break
    if table is None:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    body = table.find("tbody") or table
    records = [
        [td.get_text(strip=True) for td in tr.find_all("td")] for tr in body.find_all("tr")
    ]
    records = [r for r in records if len(r) == len(headers)]
    if not records:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    df = pd.DataFrame(records, columns=headers).rename(columns=HEADER_MAP)
    df = df[PRICE_COLUMNS]
    df["code"] = df["code"].str.strip()
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.date
    for col in ["open", "high", "low", "close", "ltp", "ycp", "value_mn"]:
        df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
    for col in ["trades", "volume"]:
        df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce").astype("Int64")
    return normalize_no_trade(df.drop_duplicates(["code", "date"]).reset_index(drop=True))


def normalize_no_trade(df: pd.DataFrame) -> pd.DataFrame:
    """On days without trades (suspension, record date, illiquid) DSE prints 0 for
    open/high/low and carries the close forward. Store those as missing, not 0."""
    no_trade = df["volume"].fillna(0) == 0
    df.loc[no_trade, ["open", "high", "low"]] = float("nan")
    df.loc[df["close"] == 0, ["close", "ltp"]] = float("nan")
    return df
