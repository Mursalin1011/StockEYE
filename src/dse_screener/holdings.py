"""Holdings tracker (docs/05 W8): your buys and sells, marked in Telegram, checked every trading day.

Commands (Telegram, or `python -m dse_screener holdings ...`):
    /bought PTL 53.7 [500] [5/10] [stop 48]    buy at 53.7; optional shares, date (default today), stop
    /sold PTL 60 [200] [5/10]                  sell; without shares the whole position is closed
    /stop PTL 48                               set the stop (/stop PTL off = back to the default)
    /holdings                                  your positions as of the latest close
    /undo                                      remove the last entry (a typo)

The ledger (`trades` table) keeps one row per entry; positions are derived from it, in the order
entered. Prices are as you paid them. Bonus shares and dividends after a buy adjust the cost the
same way the screen adjusts price history, so P/L stays correct across record dates.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import report
from .config import Profile, ReportConfig, Settings
from .db import Database
from .engine import ScreenResult, load_adjusted_prices

ALIASES = {"bought": "buy", "buy": "buy", "b": "buy", "sold": "sell", "sell": "sell", "s": "sell",
           "stop": "stop", "sl": "stop", "holdings": "list", "positions": "list", "h": "list",
           "undo": "undo", "help": "help", "start": "help"}

USAGE = {
    "buy": "/bought CODE PRICE [SHARES] [DATE] [stop PRICE], e.g. /bought PTL 53.7 500 or /bought PTL 53.7 500 5/10 stop 48",
    "sell": "/sold CODE PRICE [SHARES] [DATE], e.g. /sold PTL 60 (whole position) or /sold PTL 60 200",
    "stop": "/stop CODE PRICE, e.g. /stop PTL 48 (or /stop PTL off for the default)",
}

HELP = ("<b>💼 Holdings</b>\n"
        "/bought PTL 53.7 500: bought 500 PTL at 53.7 today\n"
        "   add a date (5/10 or 2026-10-05) and/or <code>stop 48</code>; shares are optional\n"
        "/sold PTL 60: sold the whole position (or /sold PTL 60 200 for part)\n"
        "/stop PTL 48: set your stop (off = default)\n"
        "/holdings: your positions now\n"
        "/undo: remove your last entry\n"
        "The 3pm summary checks every position: P/L, stop, trailing MA, heavy selling, record dates, "
        "news, and alerts when a stock you sold signals again.")


class CommandError(ValueError):
    """Shown to you as the reply: what was wrong and the usage."""


@dataclass
class Command:
    kind: str                    # buy | sell | stop | list | undo | help
    code: str | None = None
    price: float | None = None   # stop: None = back to the default
    qty: float | None = None
    day: date | None = None
    stop: float | None = None    # buy only: also set this stop


# --- parsing --------------------------------------------------------------------------------------

def parse(text: str, today: date) -> Command:
    words = text.replace(" ", " ").split()
    if not words:
        raise CommandError("Empty message. Send /help for the commands.")
    head = words[0].lstrip("/").split("@")[0].lower()        # "/bought@StockEyeBot" in groups
    kind = ALIASES.get(head)
    if kind is None:
        raise CommandError(f"I don't know '{_short(words[0])}'. Send /help for the commands.")
    if kind in ("list", "undo", "help"):
        return Command(kind)
    args = words[1:]
    if len(args) < 2:
        raise CommandError(f"Usage: {USAGE[kind]}")
    cmd = Command(kind, code=args[0].upper())
    if kind == "stop" and args[1].lower() in ("off", "none", "default"):
        cmd.price = None
    else:
        cmd.price = _price(args[1], kind)
    rest, i = args[2:], 0
    while i < len(rest):
        w = rest[i].lower()
        if kind == "buy" and w in ("stop", "sl"):
            if i + 1 >= len(rest):
                raise CommandError(f"'stop' needs a price. Usage: {USAGE[kind]}")
            cmd.stop = _price(rest[i + 1], kind)
            i += 2
            continue
        if kind != "stop" and (d := _date(w, today)) is not None:
            if d > today:
                raise CommandError(f"{d:%d %b %Y} is in the future.")
            cmd.day = d
        elif kind != "stop" and (q := _number(w)) is not None:
            if q <= 0 or q != int(q):
                raise CommandError(f"Shares must be a whole number, got '{_short(rest[i])}'.")
            cmd.qty = q
        else:
            raise CommandError(f"I couldn't read '{_short(rest[i])}'. Usage: {USAGE[kind]}")
        i += 1
    if kind != "stop":
        cmd.day = cmd.day or today
    return cmd


def _short(s: str) -> str:
    return s if len(s) <= 20 else s[:20] + "…"


def _number(w: str) -> float | None:
    w = w.lower().replace(",", "").removeprefix("৳").removeprefix("tk").removeprefix("@")
    try:
        return float(w)
    except ValueError:
        return None


def _price(w: str, kind: str) -> float:
    p = _number(w)
    if p is None or p <= 0:
        raise CommandError(f"'{_short(w)}' isn't a price. Usage: {USAGE[kind]}")
    return p


# day/month(/year) with / or -; dots only with a year, so "1.5" stays a number
_DMY = re.compile(r"^(\d{1,2})([/-])(\d{1,2})(?:\2(\d{2}|\d{4}))?$|^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$")


def _date(w: str, today: date) -> date | None:
    """2026-10-05, 5/10, 5-10-26, 05.10.2026 (day first, like Bangladesh); today / yesterday.
    Without a year: this year, or last year if that's more than a month ahead ("20/12" typed in January)."""
    if w == "today":
        return today
    if w == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(w)
    except ValueError:
        pass
    m = _DMY.match(w)
    if not m:
        return None
    d, mth, y = (m.group(1), m.group(3), m.group(4)) if m.group(1) else (m.group(5), m.group(6), m.group(7))
    year = int(y) if y else today.year
    year += 2000 if year < 100 else 0
    try:
        out = date(year, int(mth), int(d))
    except ValueError:
        raise CommandError(f"'{w}' isn't a valid date (day/month).") from None
    if not y and out > today + timedelta(days=31):
        out = out.replace(year=year - 1)
    return out


# --- positions from the ledger --------------------------------------------------------------------

@dataclass
class Position:
    code: str
    opened: date                     # first buy since the position was last flat
    shares: float                    # in today's shares (after any bonus issues); unsized: count of buys
    cost: float                      # average cost per share, adjusted to today
    sized: bool                      # every buy had a share count
    paid: float                      # sum of price x shares as paid (sized only)
    stop: float | None = None        # your stop, adjusted to today; None = default
    buys: int = 0
    closed: date | None = None
    exit_price: float | None = None  # adjusted to today
    realized_pct: float | None = None
    ids: list[int] = field(default_factory=list)


def _factors(actions: pd.DataFrame, code: str, since: date, until: date, include_cash: bool) -> tuple[float, float]:
    """(price factor, share factor) for corporate actions with since < ex_date <= until."""
    if actions.empty:
        return 1.0, 1.0
    a = actions[(actions["code"] == code) & actions["ex_date"].notna()]
    a = a[(a["ex_date"] > pd.Timestamp(since)) & (a["ex_date"] <= pd.Timestamp(until))]
    pf = (a["price_factor"] if include_cash else a["bonus_factor"]).prod()
    return float(pf), float(a["volume_factor"].prod())


def build_positions(trades: pd.DataFrame, actions: pd.DataFrame, as_of: date,
                    include_cash: bool = True) -> tuple[dict[str, Position], list[Position]]:
    """(open positions by code, closed positions) as of a date. Rows are applied in the order entered."""
    open_: dict[str, Position] = {}
    closed: list[Position] = []
    for t in trades.itertuples():
        day = t.date.date()
        pf, vf = _factors(actions, t.code, day, as_of, include_cash)
        qty = None if pd.isna(t.qty) else float(t.qty)
        pos = open_.get(t.code)
        if t.action == "buy":
            n = qty * vf if qty is not None else 1.0
            if pos is None:
                pos = open_[t.code] = Position(t.code, day, 0.0, 0.0, qty is not None, 0.0)
            pos.cost = (pos.cost * pos.shares + t.price * pf * n) / (pos.shares + n)
            pos.shares += n
            pos.sized &= qty is not None
            pos.paid += t.price * (qty or 0)
            pos.buys += 1
            pos.ids.append(t.id)
        elif t.action == "stop" and pos is not None:
            pos.stop = t.price * pf if t.price > 0 else None
            pos.ids.append(t.id)
        elif t.action == "sell" and pos is not None:
            pos.ids.append(t.id)
            sold = pos.shares if qty is None or not pos.sized else min(qty * vf, pos.shares)
            pos.shares -= sold
            if pos.shares <= 1e-9:
                pos.closed, pos.exit_price = day, t.price * pf
                pos.realized_pct = (pos.exit_price / pos.cost - 1) * 100
                closed.append(open_.pop(t.code))
    return open_, closed


# --- applying commands ----------------------------------------------------------------------------

def known_codes(db: Database) -> list[str]:
    return [r[0] for r in db.conn.execute("SELECT DISTINCT code FROM daily_prices")]


def apply(db: Database, settings: Settings, cmd: Command, source: str = "cli",
          source_ref: str | None = None) -> str:
    """Carry out a command and return the reply (Telegram HTML)."""
    if cmd.kind == "help":
        return HELP
    if cmd.kind == "list":
        return holdings_message(db, settings)
    if cmd.kind == "undo":
        return _undo(db)

    codes = known_codes(db)
    if cmd.code not in codes:
        close = difflib.get_close_matches(cmd.code, codes, n=3, cutoff=0.6)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise CommandError(f"No DSE stock '{cmd.code}' in the data.{hint}")

    today = settings.today()
    trades = db.load_trades()
    opened, _ = build_positions(trades, db.load_corporate_actions([cmd.code]), today,
                                settings.adjustments.adjust_cash_dividends)
    pos = opened.get(cmd.code)
    e = report._e
    notes = []

    if cmd.kind == "stop":
        if pos is None:
            raise CommandError(f"You have no open {cmd.code} position. Use /bought first.")
        db.add_trade(cmd.code, "stop", today, cmd.price or 0.0, source=source, source_ref=source_ref)
        what = f"Stop for <b>{e(cmd.code)}</b> set to {cmd.price:,.2f}" if cmd.price else \
            f"Stop for <b>{e(cmd.code)}</b> back to the default ({settings.holdings.default_stop_pct:g}% below cost)"
        if cmd.price and cmd.price >= pos.cost * 1.5:
            notes.append(f"⚠️ That's above your cost {pos.cost:,.2f} by more than 50%. Typo? /undo")
        return "\n".join([f"🛡 {what}.", *notes])

    if cmd.kind == "sell":
        if pos is None:
            raise CommandError(f"You have no open {cmd.code} position to sell.")
        if cmd.qty is not None and not pos.sized:
            cmd.qty = None
            notes.append("Your buys had no share count, so this closes the whole position.")
        if cmd.qty is not None and cmd.qty > pos.shares + 1e-6:
            raise CommandError(f"You hold {pos.shares:,.0f} {cmd.code}, can't sell {cmd.qty:,.0f}.")
    if cmd.kind == "buy" and pos is not None and pos.sized != (cmd.qty is not None):
        raise CommandError(f"Your {cmd.code} position was entered {'with' if pos.sized else 'without'} share "
                           f"counts: add this buy the same way.")

    notes += _price_check(db, settings, cmd)
    action = cmd.kind
    tid = db.add_trade(cmd.code, action, cmd.day, cmd.price, cmd.qty, source=source, source_ref=source_ref)
    if tid is None:
        return "Already recorded."
    if cmd.kind == "buy" and cmd.stop:
        db.add_trade(cmd.code, "stop", cmd.day, cmd.stop, source=source,
                     source_ref=f"{source_ref}:stop" if source_ref else None)

    opened, closed = build_positions(db.load_trades(), db.load_corporate_actions([cmd.code]), today,
                                     settings.adjustments.adjust_cash_dividends)
    size = f" {cmd.qty:,.0f}" if cmd.qty else ""
    verb = "Bought" if action == "buy" else "Sold"
    lines = [f"✅ {verb} <b>{e(cmd.code)}</b>{size} @ {cmd.price:,.2f} on {cmd.day:%a %d %b %Y}."]
    now = opened.get(cmd.code)
    if now is not None:
        stop, default = _stop(now, settings)
        lines.append(f"Position: {_size_text(now)} @ {now.cost:,.2f} avg · stop {stop:,.2f}"
                     + (f" (default {settings.holdings.default_stop_pct:g}%)" if default else ""))
        if now.sized and now.paid and abs(now.cost * now.shares / now.paid - 1) > 0.001:
            lines.append(f"<i>The average is adjusted for dividends/bonus shares since you bought "
                         f"(paid ৳{now.paid:,.0f}).</i>")
    elif action == "sell" and closed and closed[-1].code == cmd.code:
        c = closed[-1]
        lines.append(f"Position closed: {c.realized_pct:+.1f}% on an average cost of {c.cost:,.2f}. "
                     f"I'll tell you if it signals again in the next {settings.holdings.reentry_days} days.")
    lines += notes
    lines.append("<i>/undo if anything is wrong.</i>")
    return "\n".join(lines)


def _undo(db: Database) -> str:
    trades = db.load_trades()
    if trades.empty:
        return "Nothing to undo."
    last = trades.iloc[-1]
    # a /bought with a stop wrote two rows: undo both
    rows = trades.iloc[-2:] if (len(trades) > 1 and last["action"] == "stop" and isinstance(last["source_ref"], str)
                                and last["source_ref"].endswith(":stop")) else trades.iloc[-1:]
    for tid in rows["id"]:
        db.delete_trade(int(tid))
    t = rows.iloc[0]
    if t["action"] == "stop":
        what = f"stop {t['price']:,.2f}" if t["price"] else "stop reset"
    else:
        size = f" {t['qty']:,.0f}" if pd.notna(t["qty"]) else ""
        what = f"{'bought' if t['action'] == 'buy' else 'sold'}{size} @ {t['price']:,.2f} ({t['date']:%d %b})"
    return f"↩️ Removed: <b>{report._e(t['code'])}</b> {what}."


def _price_check(db: Database, settings: Settings, cmd: Command) -> list[str]:
    """A price far from the market that day is probably a typo: say so, but keep it."""
    rows = db.load_prices([cmd.code], end=cmd.day)
    if rows.empty:
        return []
    last = rows.iloc[-1]
    on_day = last["date"].date() == cmd.day
    if on_day and pd.notna(last["low"]) and pd.notna(last["high"]) and last["low"] > 0:
        if not (last["low"] * 0.995 <= cmd.price <= last["high"] * 1.005):
            return [f"⚠️ {cmd.day:%d %b} traded {last['low']:,.1f}–{last['high']:,.1f}. Typo? /undo"]
        return []
    ref = last["close"] if pd.notna(last["close"]) and last["close"] else last["ycp"]
    if ref and abs(cmd.price / ref - 1) * 100 > settings.holdings.max_price_gap_pct:
        return [f"⚠️ Last close was {ref:,.1f} ({last['date']:%d %b}), {(cmd.price / ref - 1) * 100:+.0f}% away. Typo? /undo"]
    return []


def _stop(pos: Position, settings: Settings) -> tuple[float, bool]:
    """(stop level, is it the default)."""
    if pos.stop:
        return pos.stop, False
    return pos.cost * (1 - settings.holdings.default_stop_pct / 100), True


def _size_text(pos: Position) -> str:
    if pos.sized:
        return f"{pos.shares:,.0f} sh"
    return f"{pos.buys} buy{'s' if pos.buys != 1 else ''}"


# --- the daily check ------------------------------------------------------------------------------

@dataclass
class Check:
    pos: Position
    as_of: date
    close: float | None = None
    day_pct: float | None = None
    pnl_pct: float | None = None
    pnl_amount: float | None = None
    days_held: int = 0
    peak: float | None = None
    stop: float = 0.0
    default_stop: bool = True
    ma: float | None = None
    ma_days: int = 20
    warnings: list[str] = field(default_factory=list)   # most serious first
    notes: list[str] = field(default_factory=list)
    news: list[str] = field(default_factory=list)
    traded_today: bool = True


@dataclass
class Reentry:
    pos: Position
    what: list[str]


@dataclass
class Review:
    as_of: date
    checks: list[Check]
    reentries: list[Reentry]


def tracked_codes(db: Database, settings: Settings, as_of: date) -> list[str]:
    """Open positions plus stocks sold within reentry_days: keep their news and adjustments fresh."""
    opened, closed = build_positions(db.load_trades(), pd.DataFrame(), as_of)
    recent = as_of - timedelta(days=settings.holdings.reentry_days)
    return sorted(set(opened) | {c.code for c in closed if c.closed and c.closed >= recent})


def review(db: Database, settings: Settings, as_of: date,
           results: list[tuple[Profile, ScreenResult]] | None = None) -> Review:
    trades = db.load_trades()
    if trades.empty:
        return Review(as_of, [], [])
    codes = sorted(set(trades["code"]))
    actions = db.load_corporate_actions(codes)
    opened, closed = build_positions(trades, actions, as_of, settings.adjustments.adjust_cash_dividends)
    cfg = settings.holdings
    signals = _signals_today(results or [])

    checks = []
    if opened:
        prices = load_adjusted_prices(db, settings, sorted(opened))
        prices = prices[prices["date"] <= pd.Timestamp(as_of)]
        news_cfg = ReportConfig(news_lookback_days=cfg.news_days, max_news_per_pick=2)
        news = report.recent_news(db, sorted(opened), as_of, news_cfg)
        for code, pos in opened.items():
            c = _check(pos, prices[prices["code"] == code].reset_index(drop=True), actions, as_of, settings)
            c.notes += [f"✅ {s}" for s in signals.get(code, [])]
            c.news = news.get(code, [])
            checks.append(c)
    checks.sort(key=lambda c: (not c.warnings, -(c.pnl_pct or 0)))

    recent = as_of - timedelta(days=cfg.reentry_days)
    reentries = []
    for pos in closed:
        if pos.code in opened or not pos.closed or pos.closed < recent or pos.closed > as_of:
            continue
        if what := signals.get(pos.code, []) + _watching(results or [], pos.code):
            reentries.append(Reentry(pos, what))
    # one alert per stock: the latest sell
    reentries = list({r.pos.code: r for r in sorted(reentries, key=lambda r: r.pos.closed)}.values())
    return Review(as_of, checks, reentries)


def _signals_today(results: list[tuple[Profile, ScreenResult]]) -> dict[str, list[str]]:
    """code -> ["Base breakout (swing, score 72)", ...] from today's screens (quality-passing stocks only)."""
    out: dict[str, list[str]] = {}
    for profile, res in results:
        for s in res.signals.itertuples():
            if s.role == "primary":
                out.setdefault(s.code, []).append(f"{s.title} today ({profile.name}, score {s.score:.0f})")
    return out


def _watching(results: list[tuple[Profile, ScreenResult]], code: str) -> list[str]:
    out = []
    for profile, res in results:
        for w in res.watch[res.watch["code"] == code].itertuples() if not res.watch.empty else []:
            out.append(f"{w.title} setting up ({profile.name}): " + "; ".join(w.reasons[:2]))
    return out


def _check(pos: Position, g: pd.DataFrame, actions: pd.DataFrame, as_of: date, settings: Settings) -> Check:
    cfg = settings.holdings
    c = Check(pos, as_of)
    c.stop, c.default_stop = _stop(pos, settings)
    if g.empty:
        c.warnings.append("No prices stored for this stock.")
        return c
    last = g.iloc[-1]
    c.traded_today = last["date"].date() == as_of and bool(last["volume"])
    c.close = float(last["close"])
    prev = float(g["close"].iloc[-2]) if len(g) > 1 else None
    c.day_pct = (c.close / prev - 1) * 100 if prev else None
    c.pnl_pct = (c.close / pos.cost - 1) * 100
    if pos.sized:
        c.pnl_amount = (c.close - pos.cost) * pos.shares
    since = g[g["date"] >= pd.Timestamp(pos.opened)]
    c.days_held = int((g["date"] > pd.Timestamp(pos.opened)).sum())
    c.peak = float(since["close"].max()) if not since.empty else c.close

    # stop: close at or below it is the signal; an intraday touch is a heads-up
    low = float(last["low"]) if pd.notna(last["low"]) else c.close
    if c.close <= c.stop:
        c.warnings.append(f"🛑 Closed at or below your stop {c.stop:,.2f}")
    elif low <= c.stop and c.traded_today:
        c.warnings.append(f"⚠️ Touched your stop {c.stop:,.2f} intraday (low {low:,.2f}), closed above")
    elif c.close <= c.stop * (1 + cfg.near_stop_pct / 100):
        c.warnings.append(f"⚠️ Within {(c.close / c.stop - 1) * 100:.1f}% of your stop {c.stop:,.2f}")

    c.ma_days = cfg.trail_ma
    ma = g["close"].rolling(cfg.trail_ma).mean()
    if pd.notna(ma.iloc[-1]):
        c.ma = float(ma.iloc[-1])
        if c.close < c.ma:
            first = len(g) > 1 and pd.notna(ma.iloc[-2]) and g["close"].iloc[-2] >= ma.iloc[-2]
            c.warnings.append(f"⚠️ {'First close' if first else 'Closed'} below MA{cfg.trail_ma} ({c.ma:,.2f})")

    if c.traded_today and c.day_pct is not None and c.day_pct <= -cfg.heavy_drop_pct and len(g) > 20:
        avg = g["volume"].iloc[-21:-1].astype(float).mean()
        if avg and last["volume"] >= cfg.heavy_volume_x * avg:
            c.warnings.append(f"⚠️ Heavy selling: {c.day_pct:.1f}% on {last['volume'] / avg:.1f}× average volume")
    if not c.traded_today:
        c.notes.append(f"Not traded on {as_of:%d %b}; last close {last['date']:%d %b}")

    rec = actions[actions["code"] == pos.code] if not actions.empty else actions
    if not rec.empty:
        rd = pd.to_datetime(rec["record_date"])
        soon = rec[(rd >= pd.Timestamp(as_of)) & (rd <= pd.Timestamp(as_of + timedelta(days=cfg.record_date_days)))]
        for r in soon.itertuples():
            parts = [f"{r.cash_pct:g}% cash" if r.cash_pct else "", f"{r.stock_pct:g}% bonus" if r.stock_pct else ""]
            what = ", ".join(p for p in parts if p)
            c.notes.append(f"📅 Record date {pd.Timestamp(r.record_date):%d %b}" + (f": {what}" if what else "")
                           + " (the price drops by it on the ex-date; the cost here is adjusted)")
    return c


# --- rendering ------------------------------------------------------------------------------------

def render(rv: Review, title: str = "💼 YOUR POSITIONS") -> str | None:
    """Telegram HTML: a header block, one block per position, re-entry alerts. None if nothing to show."""
    if not rv.checks and not rv.reentries:
        return None
    e = report._e
    flagged = sum(1 for c in rv.checks if c.warnings)
    head = f"<b>▸ {e(title)}</b>\n{len(rv.checks)} open" + (f" · {flagged} need a look" if flagged else "")
    sized = [c for c in rv.checks if c.pos.sized and c.pnl_amount is not None]
    if sized and len(sized) == len(rv.checks):
        cost = sum(c.pos.cost * c.pos.shares for c in sized)
        pnl = sum(c.pnl_amount for c in sized)
        head += f"\nValue ৳{cost + pnl:,.0f} · P/L ৳{pnl:+,.0f} ({pnl / cost * 100:+.1f}%)" if cost else ""
    blocks = [head]
    for c in rv.checks:
        blocks.append("\n".join(_check_lines(c)))
    for r in rv.reentries:
        p = r.pos
        lines = [f"🔁 <b>{e(p.code)}</b> · you sold {p.closed:%d %b} at {p.exit_price:,.2f} ({p.realized_pct:+.1f}%)"]
        lines += [f"   {e(w)}" for w in r.what]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _check_lines(c: Check) -> list[str]:
    e, p = report._e, c.pos
    lines = [f"<b>{e(p.code)}</b> · {_size_text(p)} @ {p.cost:,.2f} · {c.days_held}d held"]
    if c.close is not None:
        day = f" ({c.day_pct:+.1f}% today)" if c.day_pct is not None else ""
        amount = f" (৳{c.pnl_amount:+,.0f})" if c.pnl_amount is not None else ""
        off = f" · {(c.close / c.peak - 1) * 100:+.1f}% from high {c.peak:,.2f}" if c.peak and c.close < c.peak else ""
        lines.append(f"💹 Close {c.close:,.2f}{e(day)} · <b>{c.pnl_pct:+.1f}%</b>{e(amount)}{e(off)}")
        lines.append(f"🛡 Stop {c.stop:,.2f} ({'default, ' if c.default_stop else ''}{_away(c.stop, c.close)})"
                     + (f" · MA{c.ma_days} {c.ma:,.2f} ({_away(c.ma, c.close)})" if c.ma else ""))
    lines += [e(w) for w in c.warnings]
    lines += [e(n) for n in c.notes]
    lines += [f"📰 {e(n)}" for n in c.news]
    return lines


def _away(level: float, close: float) -> str:
    """'12.3% below' / '2.1% above': where a level is relative to the close."""
    pct = (level / close - 1) * 100
    return f"{abs(pct):.1f}% {'above' if pct > 0 else 'below'}"


def holdings_message(db: Database, settings: Settings) -> str:
    """Reply to /holdings: positions as of the latest stored close (no screen signals)."""
    last = db.date_range()[1]
    if not last:
        return "No prices stored yet."
    as_of = date.fromisoformat(last)
    text = render(review(db, settings, as_of), f"💼 YOUR POSITIONS · close {as_of:%a %d %b}")
    return text or "No open positions. Add one with /bought PTL 53.7 500 (send /help for more)."
