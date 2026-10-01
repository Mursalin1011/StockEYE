"""Daily summary message (Telegram HTML) from screen results."""

from __future__ import annotations

import html
import re
from datetime import date, timedelta

import pandas as pd

from .config import Profile, ReportConfig
from .db import Database
from .engine import ScreenResult

DISCLAIMER = "Screening output from your own rules. Not investment advice."


def market_summary(db: Database, as_of: date) -> dict:
    """Turnover and breadth for the day across all instruments (raw prices)."""
    day = db.load_prices(start=as_of, end=as_of)
    traded = day[day["volume"].fillna(0) > 0]
    chg = traded["close"] - traded["ycp"]
    return {
        "turnover_cr": day["value_mn"].sum() / 10,      # 1 crore = 10 million
        "advances": int((chg > 0).sum()),
        "declines": int((chg < 0).sum()),
        "unchanged": int((chg == 0).sum()),
        "traded": len(traded),
    }


def recent_news(db: Database, codes: list[str], as_of: date, cfg: ReportConfig) -> dict[str, list[str]]:
    if not codes:
        return {}
    news = db.load_news(codes)
    start = pd.Timestamp(as_of - timedelta(days=cfg.news_lookback_days))
    news = news[(news["post_date"] >= start) & (news["post_date"] <= pd.Timestamp(as_of))]
    news = news[~news["body"].str.lstrip().str.startswith("(Cont")]
    out = {}
    for code, g in news.sort_values("post_date", ascending=False).groupby("code", sort=False):
        titles = g.drop_duplicates("title").head(cfg.max_news_per_pick)
        out[code] = [f"{r.post_date:%d %b} · {r.title.split(': ', 1)[-1]}" for r in titles.itertuples()]
    return out


def _e(s) -> str:
    return html.escape(str(s), quote=False)


def _pick_lines(pick, news: list[str], cfg: ReportConfig, rank: int) -> list[str]:
    lines = [f"<b>{rank}. {_e(pick.code)}</b> · score {pick.final_score:.0f}"]
    extras, tech = [], None
    for reason in pick.reasons:
        if reason.startswith("Tech: "):
            tech = reason.removeprefix("Tech: ")
            continue
        if reason[:1] in "+-" or reason.startswith("Note:"):
            extras.append(reason)
            continue
        head, _, body = reason.partition("): ")
        lines.append(f"• <b>{_e(head)})</b>")
        for part in body.split("; ")[: cfg.max_reasons_per_pick]:
            lines.append(f"   {_e(part)}")
    if extras:
        lines.append("➕ " + _e(" · ".join(extras)))
    if tech:
        lines.append("📈 " + _e(tech))
    for n in news:
        lines.append(f"📰 {_e(n)}")
    return lines


def build_daily_report(
    as_of: date,
    results: list[tuple[Profile, ScreenResult]],
    market: dict,
    news: dict[str, list[str]],
    cfg: ReportConfig,
) -> str:
    blocks = [
        f"<b>📊 DSE Screener · {as_of:%a %d %b %Y}</b>\n"
        f"Turnover ৳{market['turnover_cr']:,.0f} cr · ▲ {market['advances']}  ▼ {market['declines']}  "
        f"● {market['unchanged']}"
    ]
    for profile, res in results:
        passed = res.universe_size - len(res.excluded)
        head = (f"<b>▸ {_e(profile.name.upper())}</b> <i>{_e(profile.description)}</i>\n"
                f"{passed}/{res.universe_size} pass quality · {len(res.signals)} signals · "
                f"{len(res.picks)} pick{'s' if len(res.picks) != 1 else ''}")
        blocks.append(head)
        if res.picks.empty:
            blocks.append("No stock meets the bar today.")
        for i, pick in enumerate(res.picks.itertuples(), 1):
            blocks.append("\n".join(_pick_lines(pick, news.get(pick.code, []), cfg, i)))
    blocks.append(f"<i>{_e(DISCLAIMER)}</i>")
    return "\n\n".join(blocks)


def build_notice(title: str, body: str) -> str:
    return f"<b>{_e(title)}</b>\n{_e(body)}"


def to_plain(text_html: str) -> str:
    """For printing a preview in the terminal."""
    return html.unescape(re.sub(r"</?(b|i)>", "", text_html))
