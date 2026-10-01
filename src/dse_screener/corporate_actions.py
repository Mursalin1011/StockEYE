"""Dividend events from DSE news -> corporate actions with exact adjustment factors.

DSE resets a stock's reference price after the record date:

    new_ref = (last_close - cash_per_share) / (1 + bonus_ratio)

e.g. EBL FY2024 (17.5% cash, 17.5% stock, face 10): (27.0 - 1.75) / 1.175 = 21.49,
and EBL opened at 21.3 on the ex-date. Prices before the ex-date are scaled by
new_ref / last_close; volumes before it by (1 + bonus_ratio).
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

_PCT = r"(\d+(?:\.\d+)?)\s*%"
_KIND = r"(?:final\s+|interim\s+)?"
# Order matters: the first pattern that matches wins. Real wordings, in order:
#   "17.50% Cash Dividend", "12.50% Cash and 12.50% Stock Dividend", "105% Final Cash Dividend"
#   "Cash Dividend @ 25.00%", "Final Cash Dividend 150% i.e. BDT. 15"
#   "Interim Cash Dividend for the year 2025 at the rate of 110% of the paid-up capital"
CASH_PATTERNS = [
    re.compile(_PCT + r"\s*" + _KIND + r"cash\b", re.I),
    re.compile(r"cash\s+dividend\s*(?:@|of)?\s*" + _PCT, re.I),
    re.compile(r"cash\s+dividend[^.%]{0,60}?at\s+the\s+rate\s+of\s+" + _PCT, re.I),
]
STOCK_PATTERNS = [
    re.compile(_PCT + r"\s*" + _KIND + r"(?:stock|bonus)\b", re.I),
    re.compile(r"(?:stock\s+dividend|bonus\s+shares?)\s*(?:@|of)?\s*" + _PCT, re.I),
    re.compile(r"(?:stock\s+dividend|bonus\s+shares?)[^.%]{0,60}?at\s+the\s+rate\s+of\s+" + _PCT, re.I),
]
# A declaration without a record date (e.g. GP interim) is linked to the next
# "record date" notice for the same company within this many days.
LINK_NOTICE_DAYS = 60
RECORD_DATE_RE = re.compile(
    r"record\s+date\s*(?:is|:|-|will\s+be)?\s*:?\s*(?:i\.e\.,?\s*)?([0-9A-Za-z ,./\-]{5,20}?\d{4})", re.I
)
DATE_FORMATS = [
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%d %B, %Y",
    "%d-%b-%Y", "%d-%B-%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y",
]

EVENT_COLUMNS = ["code", "record_date", "fiscal_year", "cash_pct", "stock_pct", "news_date", "title", "revised"]

# "for the year ended December 31, 2025", "for the year ended June 30, 2025", "for the year 2026"
FISCAL_YEAR_RE = re.compile(
    r"for\s+the\s+(?:(?:financial\s+)?year|half\s+year|six[- ]month\s+period|period)"
    r"(?:\s+ended(?:\s+on)?)?\s+[A-Za-z0-9 ,.\-]{0,20}?(\d{4})",
    re.I,
)


def parse_loose_date(s: str) -> date | None:
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s.strip(" .,;"), flags=re.I)
    s = re.sub(r"\s+", " ", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _first_pct(patterns: list[re.Pattern], text: str) -> float:
    for p in patterns:
        if m := p.search(text):
            return float(m.group(1))
    return 0.0


def extract_dividend_events(news: pd.DataFrame) -> pd.DataFrame:
    """One row per (code, record_date) where a cash or stock dividend was declared."""
    declared, notices = [], []   # declarations (have %), record-date notices (date only)
    for n in news.sort_values("post_date").itertuples(index=False):
        body = n.body or ""
        if body.lstrip().startswith("(Cont"):
            continue
        m = RECORD_DATE_RE.search(body)
        record_date = parse_loose_date(m.group(1)) if m else None
        is_dividend = "dividend" in body.lower()
        cash = _first_pct(CASH_PATTERNS, body) if is_dividend else 0.0
        stock = _first_pct(STOCK_PATTERNS, body) if is_dividend else 0.0
        post = pd.Timestamp(n.post_date).date()
        if cash or stock:
            fy = FISCAL_YEAR_RE.search(body)
            declared.append({"code": n.code, "record_date": record_date,
                             "fiscal_year": int(fy.group(1)) if fy else None, "cash_pct": cash,
                             "stock_pct": stock, "news_date": post, "title": n.title, "revised": False})
        elif record_date:
            # e.g. "remain suspended on record date i.e., 12-Aug-2026" (no word "dividend")
            notices.append({"code": n.code, "record_date": record_date, "news_date": post})

    for d in declared:
        if d["record_date"] is None:
            d["record_date"] = next(
                (x["record_date"] for x in notices
                 if x["code"] == d["code"] and 0 <= (x["news_date"] - d["news_date"]).days <= LINK_NOTICE_DAYS
                 and x["record_date"] >= d["news_date"]),
                None,
            )
    df = pd.DataFrame([d for d in declared if d["record_date"]], columns=EVENT_COLUMNS)
    # Same event can appear in several news items (declaration, AGM result): keep the earliest.
    return df.sort_values("news_date").drop_duplicates(["code", "record_date"]).reset_index(drop=True)


def reconcile_with_history(events: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Prefer the company page's final approved dividend over the Board's recommendation.

    The AGM can change it after the record date (PUBALIBANK FY2025: recommended
    15% + 15%, approved 10% cash + 20% stock). Applied only when the *stock* part
    differs and the fiscal year has a single event: the page shows the year's total
    cash, so a cash-only difference usually means an interim dividend we didn't see
    (GP FY2024: 160% interim before our news window + 170% final = 330%).
    """
    if events.empty or history.empty:
        return events
    out = events.copy()
    hist = history.set_index(["code", "year"])
    counts = out.groupby(["code", "fiscal_year"]).size()
    for i, ev in out.iterrows():
        key = (ev["code"], ev["fiscal_year"])
        if pd.isna(ev["fiscal_year"]) or counts.get(key, 0) != 1 or key not in hist.index:
            continue
        final = hist.loc[key]
        if final["stock_pct"] != ev["stock_pct"]:
            out.loc[i, ["cash_pct", "stock_pct", "revised"]] = [final["cash_pct"], final["stock_pct"], True]
    return out


def build_corporate_actions(
    events: pd.DataFrame, prices: pd.DataFrame, face_values: dict[str, float]
) -> pd.DataFrame:
    """Attach ex-date and factors to each event using stored prices.

    Events whose record date is still ahead keep ex_date = None (useful as
    "upcoming record dates"); they are ignored by adjustment until it passes.
    """
    rows = []
    by_code = {c: g.sort_values("date") for c, g in prices.groupby("code")}
    for ev in events.itertuples(index=False):
        p = by_code.get(ev.code)
        rec = pd.Timestamp(ev.record_date)
        if p is None or p.empty or rec < p["date"].iloc[0]:
            continue  # nothing stored before this event, nothing to adjust
        before, after = p[p["date"] <= rec], p[p["date"] > rec]
        ref = float(before["close"].dropna().iloc[-1])
        first_trade = after["open"].dropna()
        face = face_values.get(ev.code) or 10.0
        bonus = ev.stock_pct / 100
        new_ref = (ref - ev.cash_pct / 100 * face) / (1 + bonus)
        rows.append(
            {
                "code": ev.code,
                "record_date": rec.date().isoformat(),
                "ex_date": after["date"].iloc[0].date().isoformat() if not after.empty else None,
                "cash_pct": ev.cash_pct,
                "stock_pct": ev.stock_pct,
                "face_value": face,
                "ref_close": ref,
                "price_factor": new_ref / ref,
                "bonus_factor": 1 / (1 + bonus),
                "volume_factor": 1 + bonus,
                "ex_open": float(first_trade.iloc[0]) if not first_trade.empty else None,
                "fiscal_year": ev.fiscal_year,
                "revised": bool(ev.revised),
                "news_date": ev.news_date.isoformat(),
            }
        )
    return pd.DataFrame(rows)
