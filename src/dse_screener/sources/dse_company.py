"""DSE company page (old.dsebd.org/displayCompany.php?name=CODE).

One page per company with: basic info (category, sector, face value, shares
outstanding), dividend/bonus history by year, monthly shareholding snapshots,
audited annual EPS/NAV, P/E, and loan status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup

from .http import PoliteClient


@dataclass
class CompanyProfile:
    code: str
    info: dict = field(default_factory=dict)              # one row for `companies`
    dividends: list[dict] = field(default_factory=list)   # {year, cash_pct, stock_pct}
    shareholding: list[dict] = field(default_factory=list)
    annual: list[dict] = field(default_factory=list)      # {year, eps, nav, profit_mn, pe, dividend_text, dividend_yield}


# Page label -> (column, parser)
_NUM = "num"
_TEXT = "text"
INFO_LABELS = {
    "Authorized Capital (mn)": ("authorized_mn", _NUM),
    "Paid-up Capital (mn)": ("paid_up_mn", _NUM),
    "Face/par Value": ("face_value", _NUM),
    "Total No. of Outstanding Securities": ("outstanding_shares", _NUM),
    "Sector": ("sector", _TEXT),
    "Type of Instrument": ("instrument_type", _TEXT),
    "Market Capitalization (mn)": ("market_cap_mn", _NUM),
    "Free Float Market Cap. (mn)": ("free_float_mcap_mn", _NUM),
    "Listing Year": ("listing_year", _NUM),
    "Market Category": ("category", _TEXT),
    "Year End": ("year_end", _TEXT),
    "Present Operational Status": ("operational_status", _TEXT),
    "Short-term loan (mn)": ("short_loan_mn", _NUM),
    "Long-term loan (mn)": ("long_loan_mn", _NUM),
}

_SHAREHOLDING_RE = re.compile(
    r"\[as on ([A-Za-z]{3} \d{1,2}, \d{4})[^\]]*\]\s*"
    r"Sponsor/Director:\s*([\d.]+)\s*Govt:\s*([\d.]+)\s*Institute:\s*([\d.]+)\s*"
    r"Foreign:\s*([\d.]+)\s*Public:\s*([\d.]+)"
)
_DIV_ENTRY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*\w{0,3}\s+(\d{4})")


class DseCompanySource:
    name = "dse_company"

    def __init__(self, client: PoliteClient, base_url: str):
        self.client = client
        self.base_url = base_url

    def fetch(self, code: str) -> CompanyProfile:
        html = self.client.get(self.base_url, {"name": code})
        self.client.save_raw(self.name, f"{code}_{date.today().isoformat()}", html)
        return parse_company_html(html, code)


def to_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_dividend_history(text: str) -> dict[int, float]:
    """'215% 2025, 330% 2024, 17.50 2020' -> {2025: 215.0, 2024: 330.0, 2020: 17.5}.

    Several entries for one year (interim + final) are summed.
    """
    out: dict[int, float] = {}
    for pct, year in _DIV_ENTRY_RE.findall(text or ""):
        out[int(year)] = out.get(int(year), 0.0) + float(pct)
    return out


def _first(values: list[float | None]) -> float | None:
    return next((v for v in values if v is not None), None)


def parse_company_html(html: str, code: str) -> CompanyProfile:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table#company")
    profile = CompanyProfile(code=code)
    info = profile.info
    info["code"] = code

    # Company name sits in a heading above the first table
    text_all = soup.get_text(" ", strip=True)
    if m := re.search(r"Company Name:\s*(.+?)\s+(?:-->|Trading Code:)", text_all):
        info["name"] = m.group(1).strip()
    if m := re.search(r"Last AGM held on:\s*(\d{2}-\d{2}-\d{4})", text_all):
        info["last_agm"] = datetime.strptime(m.group(1), "%d-%m-%Y").date().isoformat()

    cash_text = stock_text = ""
    for table in tables:
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            for i, label in enumerate(cells[:-1]):
                if label in INFO_LABELS:
                    col, kind = INFO_LABELS[label]
                    info.setdefault(col, to_float(cells[i + 1]) if kind == _NUM else cells[i + 1] or None)
                elif label == "Cash Dividend":
                    cash_text = cells[i + 1]
                elif label.startswith("Bonus Issue"):
                    stock_text = cells[i + 1]
            if cells and cells[0] == "Trailing P/E Ratio":
                info["trailing_pe"] = _first([to_float(c) for c in reversed(cells[1:])])
            if cells and cells[0].startswith("Current P/E Ratio using Basic") and "pe_unaudited" not in info:
                info["pe_unaudited"] = _first([to_float(c) for c in reversed(cells[1:])])

    # Dividend history by financial year
    cash, stock = parse_dividend_history(cash_text), parse_dividend_history(stock_text)
    profile.dividends = [
        {"year": y, "cash_pct": cash.get(y, 0.0), "stock_pct": stock.get(y, 0.0)}
        for y in sorted(set(cash) | set(stock))
    ]

    # Monthly shareholding snapshots
    for table in tables:
        txt = table.get_text(" ", strip=True)
        for m in _SHAREHOLDING_RE.finditer(txt):
            as_of = datetime.strptime(m.group(1), "%b %d, %Y").date().isoformat()
            vals = [float(v) for v in m.groups()[1:]]
            profile.shareholding.append(
                dict(zip(["as_of", "sponsor", "govt", "institute", "foreign", "public"], [as_of, *vals]))
            )

    # Audited annual performance: two tables whose rows start with a year
    annual: dict[int, dict] = {}
    for table in tables:
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not cells or not re.fullmatch(r"\d{4}", cells[0]):
                continue
            year, nums = int(cells[0]), [to_float(c) for c in cells[1:]]
            rec = annual.setdefault(year, {"year": year})
            if len(cells) == 13:
                # EPS basic orig/restated/diluted, EPS-continuing same, NAV orig/restated/diluted, PCO, profit, TCI
                rec["eps"] = _first([nums[1], nums[0], nums[4], nums[3]])
                rec["nav"] = _first([nums[7], nums[6]])
                rec["profit_mn"] = nums[10]
            elif len(cells) == 9:
                # Year-end P/E (same 6 variants), dividend %, dividend yield
                rec["pe"] = _first([nums[1], nums[0], nums[4], nums[3]])
                rec["dividend_text"] = cells[7] if cells[7] != "-" else None
                rec["dividend_yield"] = nums[7]
    profile.annual = [annual[y] for y in sorted(annual)]
    return profile
