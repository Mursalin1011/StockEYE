"""DSE news archive per company (old.dsebd.org/old_news.php?inst=CODE&criteria=3).

Covers ~2 years: dividend declarations with record dates, record-date suspension
and resumption notices, quarterly EPS/NAV/NOCFPS, director trades, credit ratings.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from .http import PoliteClient

NEWS_COLUMNS = ["code", "post_date", "title", "body"]
_FIELDS = {"Trading Code:": "code", "News Title:": "title", "News:": "body", "Post Date:": "post_date"}


class DseNewsSource:
    name = "dse_news"

    def __init__(self, client: PoliteClient, base_url: str):
        self.client = client
        self.base_url = base_url

    def fetch(self, code: str) -> pd.DataFrame:
        html = self.client.get(self.base_url, {"inst": code, "criteria": 3, "archive": "news"})
        self.client.save_raw(self.name, f"{code}_{date.today().isoformat()}", html)
        return parse_news_html(html)


def parse_news_html(html: str) -> pd.DataFrame:
    """Items are rows of <th>label</th><td>value</td>; 'Post Date' closes an item."""
    soup = BeautifulSoup(html, "lxml")
    items, cur = [], {}
    for row in soup.find_all("tr"):
        th, td = row.find("th"), row.find("td")
        if not th or not td:
            continue
        key = _FIELDS.get(th.get_text(strip=True))
        if not key:
            continue
        cur[key] = td.get_text(" ", strip=True)
        if key == "post_date":
            if "code" in cur and "title" in cur:
                items.append({k: cur.get(k, "") for k in NEWS_COLUMNS})
            cur = {}
    df = pd.DataFrame(items, columns=NEWS_COLUMNS)
    if not df.empty:
        df["post_date"] = pd.to_datetime(df["post_date"], errors="coerce").dt.date
        df = df.dropna(subset=["post_date"]).drop_duplicates().reset_index(drop=True)
    return df
