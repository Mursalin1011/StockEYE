"""Command line entry point: `python -m dse_screener <command>`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from pathlib import Path

import pandas as pd
import yaml

from . import (backtest, bot, casestudy, daily, engine, features, fundamentals, holdings, ingest, market, quality,
               report, rules, simulate)
from .config import (CONFIG_DIR, Profile, TradePlan, list_plans, list_profiles, load_profile, load_settings,
                     read_plan_data, save_secret, set_plan_value)
from .universes import universe_codes
from .notify import TelegramNotifier, find_chat_ids
from .notify.telegram import TelegramError
from .db import Database
from .sources import DseArchiveSource, DseCompanySource, DseMarketSummarySource, DseNewsSource
from .sources.http import PoliteClient

log = logging.getLogger("dse_screener")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dse_screener", description="DSE stock screener")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backfill", help="download price history from the DSE archive")
    p.add_argument("--start", type=_parse_date, help="default: backfill_years ago")
    p.add_argument("--end", type=_parse_date, help="default: today")
    p.add_argument("--no-resume", action="store_true", help="refetch chunks already downloaded")

    p = sub.add_parser("ingest", help="fetch one trading day of prices (default: today)")
    p.add_argument("--date", type=_parse_date)

    p = sub.add_parser("market", help="download DSE's official daily totals (incl. block trades) for stored days")
    p.add_argument("--start", type=_parse_date, help="default: first stored trading day")
    p.add_argument("--end", type=_parse_date, help="default: today")

    p = sub.add_parser("fundamentals", help="fetch company pages + news, rebuild corporate actions")
    p.add_argument("--universe", default="all_equities")

    sub.add_parser("discover", help="fetch company pages for all unknown instruments (new listings), news for equities")

    p = sub.add_parser("actions", help="rebuild corporate actions from stored news and list them")
    p.add_argument("--universe", default="all_equities")

    p = sub.add_parser("quality", help="quality metrics and filter result per stock")
    p.add_argument("--profile", default="position", help="profile whose quality rules to apply")
    p.add_argument("--universe", help="override the profile's universe")

    p = sub.add_parser("screen", help="run profiles: quality filter -> strategies -> ranked shortlist")
    p.add_argument("--profile", action="append", help="profile name (repeatable); default: all profiles")
    p.add_argument("--date", type=_parse_date, help="as-of date (default: latest stored trading day)")
    p.add_argument("--all-signals", action="store_true", help="also list signals below the shortlist cut, and setups still forming")
    p.add_argument("--no-save", action="store_true", help="don't store the run in the database")

    p = sub.add_parser("daily", help="the 3pm job: wait for data, refresh news, screen, send to Telegram")
    p.add_argument("--date", type=_parse_date, help="re-run a past day (no waiting)")
    p.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")

    p = sub.add_parser("report", help="build the summary from stored data (no downloads)")
    p.add_argument("--date", type=_parse_date, help="default: latest stored trading day")
    p.add_argument("--send", action="store_true", help="send it to Telegram (default: print only)")

    p = sub.add_parser("backtest", help="what if you had bought each day's shortlist?")
    p.add_argument("--profile", required=True)
    p.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                   help="override a profile value, e.g. strategies.quiet_accumulation.params.vol_short_days=20")
    p.add_argument("--trades", action="store_true", help="also list every trade")
    p.add_argument("--csv", type=Path, help="write every trade to this CSV file (opens in Excel)")

    p = sub.add_parser("tune", help="grid-search parameters on the in-sample period, check out-of-sample")
    p.add_argument("--profile", required=True)
    p.add_argument("--grid", action="append", required=True, metavar="PATH=V1,V2,...",
                   help="e.g. strategies.quiet_accumulation.params.min_volume_ratio=1.5,2,2.5 (repeatable)")
    p.add_argument("--set", action="append", default=[], metavar="PATH=VALUE")
    p.add_argument("--min-trades", type=int, default=15, help="ignore combinations with fewer in-sample trades")
    p.add_argument("--top", type=int, default=15)

    p = sub.add_parser("casestudy", help="every signal on one stock over a period, with outcomes")
    p.add_argument("code", help="any stock code, e.g. PTL (doesn't need to pass the quality filter)")
    p.add_argument("--from", dest="start", type=_parse_date, help="default: one year before the last stored day")
    p.add_argument("--to", dest="end", type=_parse_date, help="default: last stored day")
    p.add_argument("--profile", action="append", help="profile name (repeatable); default: all profiles")
    p.add_argument("--shortlist", action="store_true",
                   help="also run each profile's backtest to show the stock's actual shortlist rank (slower)")
    p.add_argument("--csv", type=Path, help="write the signals to this CSV file")

    p = sub.add_parser("moves", help="big moves (+50%%) in every stock and which strategies caught them early")
    p.add_argument("--rebuild", action="store_true", help="rebuild even if the stored scan is current")
    p.add_argument("--top", type=int, default=25, help="how many of the biggest moves to list")

    p = sub.add_parser("simulate", help="trade lab: test your own entry/exit rules on any stock (docs/06)",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="Condition columns (N = any number):\n  " + "\n  ".join(features.known())
                       + "\nOperators: >  <  >=  <=  crosses_above  crosses_below")
    p.add_argument("codes", nargs="*", help="stock codes, e.g. PTL (default: the plan's codes)")
    p.add_argument("--plan", help="saved plan in config/plans (name) or a YAML file; flags override it")
    p.add_argument("--from", dest="start", type=_parse_date, help="first signal day (default: plan, else all data)")
    p.add_argument("--to", dest="end", type=_parse_date, help="end of the test (default: plan, else last stored day)")
    g = p.add_argument_group("entry (any of these replaces the plan's entry)")
    g.add_argument("--strategy", help="enter on this strategy's signal, e.g. base_breakout")
    g.add_argument("--profile", help="with --strategy: take its parameters from this profile, e.g. swing")
    g.add_argument("--when", action="append", metavar='"LEFT OP RIGHT"',
                   help='entry condition, e.g. "close > sma_50" (repeatable; all must hold)')
    g.add_argument("--dates", help="buy on these days instead, e.g. 2025-03-12,2025-08-04")
    g = p.add_argument_group("entry options")
    g.add_argument("--fill", choices=["next_open", "same_close"])
    g.add_argument("--every-signal-day", action="store_true",
                   help="act on every signal day, not just the first day of each setup")
    g = p.add_argument_group("exit (first to trigger wins)")
    g.add_argument("--stop", type=float, metavar="PCT", help="stop loss, %% below the entry (intraday low)")
    g.add_argument("--target", type=float, metavar="PCT", help="profit target, %% above the entry (intraday high)")
    g.add_argument("--trail-pct", type=float, metavar="PCT", help="close this %% below its highest since entry")
    g.add_argument("--trail-ma", type=int, metavar="N", help="close below the N-day moving average")
    g.add_argument("--exit-when", action="append", metavar='"LEFT OP RIGHT"',
                   help='exit condition at the close, e.g. "rsi_14 > 75" (repeatable; any one)')
    g.add_argument("--max-days", type=int, help="time limit: trading days after the signal day")
    g = p.add_argument_group("hold, costs, money")
    g.add_argument("--min-days", type=int, help="no exit before entry + this many trading days (default 2)")
    g.add_argument("--cooldown", type=int, help="trading days to wait after an exit (default 0)")
    g.add_argument("--cost", type=float, metavar="PCT", help="round-trip cost (default 1.0)")
    g.add_argument("--capital", type=float, help="starting capital (default 100,000)")
    g.add_argument("--size-pct", type=float, help="%% of equity per trade (default 100)")
    g.add_argument("--in-sample-until", type=_parse_date, help="split stats into tuning / test periods")
    g = p.add_argument_group("many stocks")
    g.add_argument("--universe", help="also every stock in this universe, e.g. ds30 or all_equities")
    g.add_argument("--quality", metavar="PROFILE", help="keep only stocks passing this profile's quality filter today")
    g.add_argument("--portfolio", type=int, metavar="N",
                   help="shared capital: at most N positions at once, each 1/N of equity")
    g.add_argument("--rank-by", metavar="COLUMN",
                   help="with --portfolio: who gets a free slot first (default: strategy score, else vol_x_20)")
    g.add_argument("--max-value-pct", type=float, metavar="PCT",
                   help="flag trades bigger than this %% of the stock's average daily traded value (default 10)")
    g = p.add_argument_group("parameter grid")
    g.add_argument("--grid", action="append", default=[], metavar="PATH=V1,V2,...",
                   help="run every combination, e.g. exit.stop_pct=5,8,10 --grid exit.trail_ma=20,50; "
                        "a condition's number: entry.when.1.2=30,40 (repeatable)")
    g.add_argument("--top", type=int, default=20, help="grid rows to show (default 20)")
    p.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                   help="override any plan value, e.g. exit.stop_pct=6 or entry.params.base_days=30")
    p.add_argument("--trades", action="store_true", help="list every trade even when there are many")
    p.add_argument("--csv", type=Path, help="write the trades to this CSV file")
    p.add_argument("--equity-csv", type=Path, help="write the daily equity curve to this CSV file")
    p.add_argument("--basket", metavar="PROFILE",
                   help="also compare with an equal-weight basket of this profile's quality stocks, e.g. swing (slower)")

    p = sub.add_parser("research", help="research PDFs and the AI review (see config/research/ANALYST.md)")
    rs = p.add_subparsers(dest="research_cmd", required=True)
    r = rs.add_parser("add", help="add PDF links (https) or files")
    r.add_argument("items", nargs="+", help="https:// links or local PDF paths")
    r.add_argument("--type", dest="doc_type", choices=["newsflash", "market_review", "macro", "company", "sector", "other"],
                   help="override the type from config/research/sources.yaml")
    rs.add_parser("inbox", help="import every PDF in the inbox folder (research.inbox)")
    r = rs.add_parser("list", help="list stored documents")
    r.add_argument("--limit", type=int, default=20)
    r = rs.add_parser("review", help="AI review of unreviewed recent documents (or --doc ids)")
    r.add_argument("--doc", type=int, action="append", help="document id (repeatable)")
    r.add_argument("--dry-run", action="store_true", help="write the request to a file instead of calling the API")
    r.add_argument("--no-send", action="store_true", help="don't send the summary to Telegram")
    r = rs.add_parser("show", help="print a stored review (default: the latest)")
    r.add_argument("id", nargs="?", type=int)
    rs.add_parser("score", help="score AI calls whose horizon has passed, and show the track record")
    r = rs.add_parser("import", help="store a review written elsewhere (JSON in the review schema) and its calls")
    r.add_argument("file", type=Path)
    r.add_argument("--doc", type=int, action="append", required=True, help="document id it covers (repeatable)")
    r.add_argument("--model", default="manual", help="who wrote it, e.g. 'claude-opus-5-5 (Claude Code)'")
    r = rs.add_parser("evening", help="the 22:30 job: import inbox, score calls, review new documents, send")
    r.add_argument("--dry-run", action="store_true", help="print instead of sending to Telegram")

    p = sub.add_parser("api", help="start the API for the web dashboard (127.0.0.1 only)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="restart on code changes (development)")

    p = sub.add_parser("bot", help="answer your Telegram commands (/bought, /sold, /stop, /holdings, /undo)")
    p.add_argument("--once", action="store_true", help="handle pending messages and exit")

    p = sub.add_parser("holdings", help="your positions, or a tracker command, e.g. holdings bought PTL 53.7 500")
    p.add_argument("words", nargs="*", help="same as in Telegram without the slash: bought, sold, stop, undo, help")

    sub.add_parser("telegram-setup", help="find your chat id after you've messaged the bot, and save it")
    sub.add_parser("telegram-test", help="send a test message")

    p = sub.add_parser("status", help="show what is stored")
    p.add_argument("--universe", default="all_equities")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    settings = load_settings()
    db = Database(settings.resolve(settings.paths.db))
    try:
        return COMMANDS[args.command](args, settings, db)
    finally:
        db.close()


def _client(settings) -> PoliteClient:
    return PoliteClient(settings.http, settings.resolve(settings.paths.raw))


def cmd_backfill(args, settings, db) -> int:
    source = DseArchiveSource(_client(settings), settings.sources.dse_archive.base_url)
    report = ingest.backfill(db, source, settings, args.start, args.end, resume=not args.no_resume)
    print(
        f"Backfill done: {report.rows:,} rows from {report.chunks_ok} chunks "
        f"({report.chunks_skipped} skipped, {len(report.errors)} failed)"
    )
    for err in report.errors:
        print(f"  FAILED {err}")
    return 1 if report.errors else 0


def cmd_ingest(args, settings, db) -> int:
    source = DseArchiveSource(_client(settings), settings.sources.dse_archive.base_url)
    day = args.date or settings.today()
    rows, complete = ingest.ingest_day(db, source, settings, day)
    print(f"{day}: {rows} rows ({'complete' if complete else 'INCOMPLETE or no trading'})")
    return 0 if complete else 2


def cmd_market(args, settings, db) -> int:
    source = DseMarketSummarySource(_client(settings), settings.sources.dse_market_summary.base_url)
    start = args.start or date.fromisoformat(db.date_range()[0])
    rows = market.backfill(db, source, start, args.end or settings.today(), settings.ingest.chunk_days)
    print(f"Official totals stored for {rows} trading days")
    return 0


def cmd_fundamentals(args, settings, db) -> int:
    client = _client(settings)
    codes = universe_codes(args.universe, db)
    report = fundamentals.refresh_fundamentals(
        db,
        DseCompanySource(client, settings.sources.dse_company.base_url),
        DseNewsSource(client, settings.sources.dse_news.base_url),
        codes,
    )
    print(f"Fundamentals: {report.companies}/{len(codes)} companies, {report.news_added} new news items")
    for err in report.errors:
        print(f"  FAILED {err}")
    return cmd_actions(args, settings, db) or (1 if report.errors else 0)


def cmd_discover(args, settings, db) -> int:
    client = _client(settings)
    report = fundamentals.discover_instruments(
        db, DseCompanySource(client, settings.sources.dse_company.base_url),
        DseNewsSource(client, settings.sources.dse_news.base_url),
    )
    comp = db.load_companies()
    print(f"Discovered {report.companies} instruments, {report.news_added} news items. Now known: "
          f"{len(comp)} ({(comp['instrument_type'] == 'Equity').sum()} equities)")
    print(comp.groupby(["instrument_type", "category"], dropna=False).size().to_string())
    for err in report.errors:
        print(f"  FAILED {err}")
    return 1 if report.errors else 0


def cmd_actions(args, settings, db) -> int:
    codes = universe_codes(args.universe, db)
    actions = fundamentals.rebuild_corporate_actions(db, codes)
    print(f"Corporate actions: {len(actions)} events for {actions['code'].nunique() if len(actions) else 0} stocks")
    _print_actions(actions)
    return 0


def _print_actions(actions) -> None:
    if actions.empty:
        return
    print(f"  {'code':<11} {'record':<10}  {'ex-date':<10}  {'cash%':>6} {'stock%':>6}  "
          f"{'ref':>7} {'expected':>8} {'opened':>7}  check")
    for a in actions.sort_values(["code", "record_date"]).itertuples(index=False):
        expected = a.ref_close * a.price_factor
        if a.ex_open is None or a.ex_open != a.ex_open:  # None or NaN
            opened, check = "-", "upcoming"
        else:
            dev = a.ex_open / expected - 1
            opened, check = f"{a.ex_open:7.1f}", f"{dev:+.1%}" + ("" if abs(dev) <= 0.05 else "  <- CHECK")
        ex = str(a.ex_date)[:10] if a.ex_date is not None and a.ex_date == a.ex_date else "-"
        if a.revised:
            check += "  (AGM-revised amounts)"
        print(f"  {a.code:<11} {a.record_date:<10}  {ex:<10}  {a.cash_pct:6.1f} {a.stock_pct:6.1f}  "
              f"{a.ref_close:7.1f} {expected:8.1f} {opened:>7}  {check}")


def cmd_quality(args, settings, db) -> int:
    profile = load_profile(args.profile)
    codes = universe_codes(args.universe or profile.universe, db)
    seed = set(universe_codes("quality_seed", db))
    metrics = quality.compute_quality_metrics(db, codes)
    qf = profile.filters.get("quality")
    result = rules.evaluate(metrics, qf.rules if qf and qf.enabled else {})

    cols = ["category", "market_cap_mn", "dividend_streak", "cash_dividend_years_5", "eps_positive_years_5",
            "eps_cagr_3y", "pe", "p_nav", "dividend_yield", "strategic_pct", "institute_change_pp"]
    short = ["cat", "mcap_bn", "div_strk", "cash5", "eps+5", "eps_cagr", "pe", "p/nav", "yield", "strat%", "inst_chg"]
    table = metrics[cols].copy()
    table["market_cap_mn"] = table["market_cap_mn"] / 1000
    table.columns = short
    table["pass"] = result["passed"].map({True: "PASS", False: "-"})
    table.index = [f"{c}{'*' if c in seed else ''}" for c in table.index]
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:,.1f}".format):
        print(table.sort_values(["pass", "mcap_bn"], ascending=[True, False]).to_string())
    print(f"\n* = your quality seed. Profile '{profile.name}': "
          f"{int(result['passed'].sum())}/{len(result)} pass the quality filter.")
    for code, r in result[~result["passed"]].iterrows():
        print(f"  {code:<11} {'; '.join(r['failures'])}")
    return 0


def cmd_screen(args, settings, db) -> int:
    for name in args.profile or list_profiles(settings):
        profile = load_profile(name)
        result = engine.run_profile(db, settings, profile, args.date)
        if not args.no_save:
            db.save_screen(result, profile.model_dump_json(by_alias=True))
        _print_screen(result, profile, args.all_signals)
    return 0


def _print_screen(result, profile, all_signals: bool) -> None:
    passed = result.universe_size - len(result.excluded)
    print(f"\n=== {profile.name.upper()}: {profile.description}")
    print(f"    {result.as_of}  |  {passed}/{result.universe_size} pass quality  |  "
          f"{len(result.signals)} strategy signals  |  {len(result.picks)} on the shortlist "
          f"(score >= {profile.ranking.min_score:g})")
    if result.skipped:
        print(f"    not traded on {result.as_of}: {', '.join(result.skipped)}")
    for i, p in enumerate(result.picks.itertuples(), 1):
        print(f"\n  {i}. {p.code}  score {p.final_score:.0f}")
        for reason in p.reasons:
            print(f"       - {reason}")
    if result.picks.empty:
        print("\n  No stock meets the shortlist bar today.")
    if all_signals and not result.signals.empty:
        print("\n  All signals:")
        for s in result.signals.sort_values("score", ascending=False).itertuples():
            print(f"    {s.code:<11} {s.title:<26} {s.score:5.1f}")
    if all_signals and not result.watch.empty:
        print("\n  Setups to watch (not a signal yet):")
        for w in result.watch.itertuples():
            print(f"    {w.code:<11} {w.title:<26} needs {w.metrics['trigger']:.1f} "
                  f"({w.metrics['to_trigger_pct']:+.1f}%), {w.metrics['days_left']} day(s) left")


def _deliverer(settings, dry_run: bool):
    if dry_run:
        return lambda text: print(report.to_plain(text))
    if not settings.telegram.enabled:
        raise SystemExit("Telegram is disabled in config/settings.yaml (telegram.enabled)")
    return TelegramNotifier(settings.telegram.bot_token, settings.telegram.chat_id).send


def _log_to_file(settings, name: str) -> Path:
    log_dir = settings.resolve(settings.paths.db).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{name}-{settings.today().isoformat()}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return path


def cmd_daily(args, settings, db) -> int:
    log_path = _log_to_file(settings, "daily")
    try:
        deliver = _deliverer(settings, args.dry_run)
    except TelegramError as exc:
        log.error("%s", exc)
        return 3
    inbox = None
    if not args.dry_run:
        tg = TelegramNotifier(settings.telegram.bot_token, settings.telegram.chat_id)
        inbox = lambda: None if bot.bot_running(db) else bot.poll_once(db, settings, tg)  # noqa: E731
    try:
        outcome = daily.run_daily(settings, db, deliver, day=args.date, wait=args.date is None, inbox=inbox)
    except Exception as exc:
        log.exception("Daily run failed")
        if not args.dry_run:
            try:
                deliver(report.build_notice("⚠️ DSE Screener failed",
                                            f"{type(exc).__name__}: {exc}\nLog: {log_path}"))
            except Exception:
                log.exception("Could not send the failure notice either")
        return 1
    log.info("Daily run: %s for %s, picks %s", outcome.status, outcome.day, outcome.picks)
    return 0


def cmd_report(args, settings, db) -> int:
    profiles = [load_profile(n) for n in list_profiles(settings)]
    results = [(p, engine.run_profile(db, settings, p, args.date)) for p in profiles]
    day = results[0][1].as_of
    pick_codes = sorted({c for _, r in results for c in r.picks["code"]})
    text = report.build_daily_report(
        day, results, report.market_summary(db, day), report.recent_news(db, pick_codes, day, settings.report),
        settings.report, report.pick_quotes(db, pick_codes, day),
        holdings.render(holdings.review(db, settings, day, results)),
    )
    _deliverer(settings, dry_run=not args.send)(text)
    return 0


def cmd_bot(args, settings, db) -> int:
    try:
        tg = TelegramNotifier(settings.telegram.bot_token, settings.telegram.chat_id)
    except TelegramError as exc:
        log.error("%s", exc)
        return 3
    if args.once:
        print(f"Handled {bot.poll_once(db, settings, tg)} message(s).")
        return 0
    _log_to_file(settings, "bot")
    try:
        bot.run(db, settings, tg)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_holdings(args, settings, db) -> int:
    text = " ".join(args.words) or "holdings"
    try:
        reply = holdings.apply(db, settings, holdings.parse(text, settings.today()), source="cli")
    except holdings.CommandError as exc:
        print(exc)
        return 2
    print(report.to_plain(reply))
    return 0


def _profile_with(name: str, overrides: list[str]) -> Profile:
    """Load a profile and apply PATH=VALUE overrides (values parsed as YAML: 20, 1.5, true, [A, B])."""
    data = yaml.safe_load((CONFIG_DIR / "profiles" / f"{name}.yaml").read_text(encoding="utf-8"))
    for item in overrides:
        path, _, raw = item.partition("=")
        node = data
        *parents, leaf = path.strip().split(".")
        for key in parents:
            node = node.setdefault(key, {})
        node[leaf] = yaml.safe_load(raw)
    return Profile.model_validate(data)


def _backtest_inputs(db, settings, profile):
    codes = universe_codes(profile.universe, db)
    return (engine.load_adjusted_prices(db, settings, codes), quality.compute_quality_metrics(db, codes),
            db.load_corporate_actions(codes))


def _fmt_summary(df: pd.DataFrame, days: bool = False) -> str:
    cols = {"trades": "trades", "median_ret": "median%", "mean_ret": "mean%", "hit_rate": "hit%",
            "avg_win": "avg win%", "avg_loss": "avg loss%", "profit_factor": "PF",
            "median_excess": "vs bench (median)", "mean_excess": "vs bench (mean)",
            "beat_bench": "beat%", "worst": "worst%", "best": "best%"}
    if days:
        cols["median_days"] = "days"
    out = df[list(cols)].rename(columns=cols)
    with pd.option_context("display.width", 250, "display.float_format", "{:,.1f}".format):
        return out.to_string()


def _fmt_recall(df: pd.DataFrame) -> str:
    cols = {"moves": "moves", "caught": "caught", "recall_pct": "recall%", "signals": "signals",
            "signals_per_catch": "signals/catch", "median_days_after_start": "days after start (median)"}
    with pd.option_context("display.width", 200, "display.float_format", "{:,.1f}".format):
        return df[list(cols)].rename(columns=cols).to_string()


def cmd_backtest(args, settings, db) -> int:
    profile = _profile_with(args.profile, args.set)
    res = backtest.run_backtest(profile, *_backtest_inputs(db, settings, profile))
    bt = profile.backtest
    print(f"\n=== Backtest {profile.name}: {res.start:%Y-%m-%d} .. {res.end:%Y-%m-%d}, "
          f"{len(res.universe)} stocks pass quality, cost {bt.cost_pct}% round trip, "
          f"entry next open, non-overlapping {bt.primary_horizon}d trades")
    if res.in_sample_until is not None:
        print(f"    in-sample (tuning) up to {res.in_sample_until:%Y-%m-%d}; later = out-of-sample test")
    for h in res.horizons:
        print(f"\n--- holding {h} trading days (returns net of costs, %; PF = profit factor, gross win / gross loss)")
        print(_fmt_summary(backtest.summarize(res, h)))
    for name, rule in res.exits.items():
        n_open = int((res.trades[f"why_{name}"] == "open").sum())
        print(f"\n--- exit '{name}': {backtest.exit_label(name, rule)} (same entries; days = trading days held"
              + (f"; {n_open} still open, left out" if n_open else "") + ")")
        print(_fmt_summary(backtest.summarize(res, name), days=True))
    w = res.winners_cfg
    print(f"\n--- recall: big moves (close +{w.min_gain_pct:g}% within {w.within_days} days) in quality stocks, "
          f"caught {w.before_days} days before to {w.after_days} after the start at <= +{w.max_entry_premium_pct:g}%")
    print(_fmt_recall(backtest.recall(res)))
    if args.trades:
        h = res.primary
        cols = ["date", "code", "rank", "final_score", "strategies", f"ret_{h}", f"bench_{h}", f"excess_{h}"]
        with pd.option_context("display.width", 200, "display.max_rows", 500, "display.float_format", "{:,.1f}".format):
            print("\n" + res.trades[cols].to_string(index=False))
    if args.csv:
        res.trades.to_csv(args.csv, index=False, float_format="%.2f")
        print(f"\nWrote {len(res.trades)} trades to {args.csv}")
    print("\nCaveats: today's fundamentals and today's universe are applied to the past "
          "(look-ahead and survivorship bias). Treat small samples with care.")
    return 0


def cmd_tune(args, settings, db) -> int:
    import itertools

    base = _profile_with(args.profile, args.set)
    if base.backtest.in_sample_until is None:
        raise SystemExit("Set backtest.in_sample_until in the profile first: tuning needs an untouched test period.")
    inputs = _backtest_inputs(db, settings, base)
    axes = []
    for g in args.grid:
        path, _, values = g.partition("=")
        axes.append([(path, v.strip()) for v in values.split(",")])
    rows = []
    h = base.backtest.primary_horizon
    for combo in itertools.product(*axes):
        prof = _profile_with(args.profile, args.set + [f"{p}={v}" for p, v in combo])
        s = backtest.summarize(backtest.run_backtest(prof, *inputs), h)
        ins, oos = s.loc["in-sample"], s.loc["out-of-sample"]
        label = lambda p: p.removeprefix("strategies.").replace(".params.", ".")  # noqa: E731
        rows.append({**{label(p): v for p, v in combo},
                     "in_trades": ins["trades"], "in_vs_bench": ins["median_excess"], "in_beat%": ins["beat_bench"],
                     "out_trades": oos["trades"], "out_vs_bench": oos["median_excess"], "out_beat%": oos["beat_bench"]})
    table = pd.DataFrame(rows)
    ok = table[table["in_trades"] >= args.min_trades].sort_values("in_vs_bench", ascending=False)
    print(f"\n=== Tune {base.name}: {len(table)} combinations, ranked by in-sample median return vs benchmark "
          f"({h}d, net). Choose on in-sample; out-of-sample is the honest check.")
    with pd.option_context("display.width", 220, "display.float_format", "{:,.1f}".format):
        print(ok.head(args.top).to_string(index=False))
    dropped = len(table) - len(ok)
    if dropped:
        print(f"({dropped} combinations had fewer than {args.min_trades} in-sample trades and are hidden)")
    return 0


def cmd_casestudy(args, settings, db) -> int:
    code = args.code.upper()
    g = engine.load_adjusted_prices(db, settings, [code])
    if g.empty:
        raise SystemExit(f"No prices stored for {code}")
    last = g["date"].max()
    start = pd.Timestamp(args.start) if args.start else last - pd.DateOffset(years=1)
    metrics = quality.compute_quality_metrics(db, [code])
    actions = db.load_corporate_actions([code])
    frames = []
    for name in args.profile or list_profiles(settings):
        profile = load_profile(name)
        picks = None
        if args.shortlist:
            print(f"Running the {name} backtest for shortlist ranks...")
            picks = backtest.run_backtest(profile, *_backtest_inputs(db, settings, profile)).picks
        cs = casestudy.run_casestudy(profile, g, metrics, actions, start, args.end, picks)
        _print_casestudy(cs, shortlist=args.shortlist)
        frames.append(cs.signals.assign(profile=name))
    if args.csv:
        out = pd.concat(frames, ignore_index=True)
        out.to_csv(args.csv, index=False, float_format="%.2f")
        print(f"\nWrote {len(out)} signals to {args.csv}")
    return 0


def _plan_from_args(args) -> TradePlan:
    """The saved plan (if any), then the flags, then --set overrides."""
    data = read_plan_data(args.plan) if args.plan else {}
    entry = data.setdefault("entry", {})
    if args.strategy or args.when or args.dates:
        for key in ("strategy", "profile", "params", "when", "dates"):
            entry.pop(key, None)
        if args.strategy:
            entry["strategy"] = args.strategy
        if args.when:
            entry["when"] = args.when
        if args.dates:
            entry["dates"] = [d.strip() for d in args.dates.split(",") if d.strip()]
    flags = {
        "codes": [c.upper() for c in args.codes] or None, "from": args.start, "to": args.end,
        "entry.profile": args.profile, "entry.fill": args.fill,
        "entry.new_signal_only": False if args.every_signal_day else None,
        "exit.stop_pct": args.stop, "exit.target_pct": args.target, "exit.trail_pct": args.trail_pct,
        "exit.trail_ma": args.trail_ma, "exit.when_any": args.exit_when, "exit.max_days": args.max_days,
        "hold.min_days": args.min_days, "hold.cooldown_days": args.cooldown, "costs.round_trip_pct": args.cost,
        "capital.start": args.capital, "capital.per_trade_pct": args.size_pct, "in_sample_until": args.in_sample_until,
        "universe": args.universe, "quality": args.quality, "portfolio.max_positions": args.portfolio,
        "portfolio.rank_by": args.rank_by, "liquidity.max_pct": args.max_value_pct,
    }
    for path, value in flags.items():
        if value is not None:
            set_plan_value(data, path, value)
    for item in args.set:
        path, _, raw = item.partition("=")
        set_plan_value(data, path, yaml.safe_load(raw))
    return TradePlan.model_validate(data)


def cmd_moves(args, settings, db) -> int:
    from . import moves

    d = moves.latest(db, settings, force=args.rebuild)
    w, mv = d["winners"], d["moves"]
    primary = [m for m in mv if any(c["strategy"] != "big_hands" for c in m["caught_by"])]
    print(f"\n=== Big moves: close +{w['min_gain_pct']:g}% within {w['within_days']} days, {d['from']} .. {d['as_of']}, "
          f"all stocks (built {d['built_at']})")
    print(f"{len(mv)} moves in {len({m['code'] for m in mv})} stocks; {len(primary)} caught early by a primary strategy "
          f"({w['before_days']} days before to {w['after_days']} after the start, entry <= +{w['max_entry_premium_pct']:g}%)\n")
    for m in mv[:args.top]:
        caught = ", ".join(f"{c['key']} ({c['days_from_start']:+d}d)" for c in m["caught_by"] if c["strategy"] != "big_hands")
        print(f"  {m['code']:<12} {m['date']} -> {m['peak_date']}  {m['peak_gain_pct']:+6.0f}%  {caught or 'missed'}")
    print(f"\n{len(d['signals'])} signal starts in {len({s['code'] for s in d['signals']})} stocks. "
          "Full lists on the dashboard's Big moves page.")
    return 0


def cmd_simulate(args, settings, db) -> int:
    if not (args.plan or args.strategy or args.when or args.dates):
        saved = ", ".join(list_plans()) or "none yet"
        raise SystemExit("Give a plan (--plan NAME) or an entry rule (--strategy / --when / --dates). "
                         f"Saved plans: {saved}. See docs/06-trade-lab-plan.md")
    try:
        plan = _plan_from_args(args)
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(str(e))
    if not (plan.codes or plan.universe):
        raise SystemExit("Which stocks? Give codes, e.g. `simulate PTL ...`, a --universe, or set codes in the plan.")
    codes = simulate.plan_codes(plan, db)
    if not codes:
        raise SystemExit("No stocks left (check --universe / --quality)")
    prices = engine.load_adjusted_prices(db, settings, codes)
    basket = None
    if args.basket:
        prof = load_profile(args.basket)
        universe = universe_codes(prof.universe, db)
        bcodes = simulate.quality_codes(prof, quality.compute_quality_metrics(db, universe), universe)
        basket = simulate.Basket(engine.load_adjusted_prices(db, settings, bcodes), bcodes,
                                 f"{len(bcodes)} {args.basket} quality stocks")
    if args.grid:
        return _print_grid(args, plan, prices, basket, codes)
    try:
        res = simulate.run_plan(plan, prices, codes=codes)
    except ValueError as e:
        raise SystemExit(str(e))
    if basket is not None and not res.stocks.empty:
        basket.apply(res)
    _print_simulation(res, codes, show_all=args.trades)
    if args.csv:
        res.trades.to_csv(args.csv, index=False, float_format="%.2f")
        print(f"\nWrote {len(res.trades)} trades to {args.csv}")
    if args.equity_csv:
        res.equity.to_csv(args.equity_csv, index=False, float_format="%.2f")
        print(f"Wrote the equity curve ({len(res.equity)} rows) to {args.equity_csv}")
    return 0


def _print_grid(args, plan: TradePlan, prices: pd.DataFrame, basket, codes: list[str]) -> int:
    grid = {}
    for item in args.grid:
        path, _, values = item.partition("=")
        grid[path.strip()] = [yaml.safe_load(v.strip()) for v in values.split(",") if v.strip()]
    try:
        table = simulate.sweep(plan, grid, prices, basket, codes=codes)
    except ValueError as e:
        raise SystemExit(str(e))
    split = "in_mean" in table
    key = "in_mean" if split else "all_mean"
    table = table.sort_values(key, ascending=False, na_position="last")
    print(f"\n=== Trade lab grid: {plan.name} on {len(codes)} stock(s), {len(table)} combinations")
    for line in simulate.describe(plan):
        print("  " + line)
    print(f"\nRanked by the mean return per trade in {'the tuning period' if split else 'all trades'} (closed trades, net)."
          + (" Choose on the tuning period (in_); the test period (out_) is the honest check." if split else
             " Set --in-sample-until to split into tuning and test periods."))
    with pd.option_context("display.width", 260, "display.max_columns", 50, "display.float_format", "{:,.1f}".format):
        print(table.head(args.top).to_string(index=False))
    if len(table) > args.top:
        print(f"({len(table) - args.top} more; --top N to show them)")
    return 0


def _print_simulation(res: simulate.LabResult, codes: list[str] | None = None, show_all: bool = False) -> None:
    plan = res.plan
    codes = codes or plan.codes
    span = ""
    if not res.stocks.empty:
        span = f", {res.stocks['start'].min():%Y-%m-%d} .. {res.stocks['end'].max():%Y-%m-%d}"
    names = ", ".join(codes) if len(codes) <= 8 else f"{len(codes)} stocks"
    print(f"\n=== Trade lab: {plan.name} on {names}{span}")
    for line in simulate.describe(plan):
        print("  " + line)
    t = res.trades
    if t.empty:
        print("\nNo trades.")
    elif len(t) > 60 and not show_all:
        print(f"\n{len(t)} trades (--trades to list them, --csv to save them).")
    else:
        table = pd.DataFrame({
            "code": t["code"], "signal": t["signal_date"].dt.strftime("%Y-%m-%d"),
            "bought": t["entry_date"].dt.strftime("%Y-%m-%d"), "at": t["entry"], "actual": t["entry_actual"],
            "sold": t["exit_date"].dt.strftime("%Y-%m-%d"), "at ": t["exit"], "actual ": t["exit_actual"],
            "why": t["why"], "days": t["days"], "net%": t["ret_pct"], "best%": t["best_pct"],
            "worst%": t["worst_pct"], "flags": t["flags"],
        })
        if res.basket:
            table.insert(table.columns.get_loc("net%") + 1, "vs basket%", t["excess_pct"])
        adjusted = (t["entry_actual"] - t["entry"]).abs().gt(1e-9).any() or (t["exit_actual"] - t["exit"]).abs().gt(1e-9).any()
        if not adjusted:
            table = table.drop(columns=["actual", "actual "])
        if len(codes) == 1:
            table = table.drop(columns="code")
        if not t["flags"].astype(bool).any():
            table = table.drop(columns="flags")
        print("\nTrades (prices adjusted for bonus/rights" + ("; actual = the price traded that day" if adjusted else "")
              + "; net of costs; days = trading days from signal to exit; best/worst = intraday extremes while held):")
        with pd.option_context("display.width", 250, "display.max_rows", 1000, "display.max_colwidth", 60,
                               "display.float_format", "{:,.1f}".format):
            print(table.to_string(index=False))

    if not t.empty:
        cols = {"trades": "trades", "win_rate": "win%", "mean_ret": "mean%", "median_ret": "median%",
                "avg_win": "avg win%", "avg_loss": "avg loss%", "profit_factor": "PF", "best": "best%",
                "worst": "worst%", "median_days": "days"}
        if res.basket:
            cols |= {"mean_excess": "vs basket%", "beat_basket": "beat%"}
        s = simulate.summarize(res)
        if s.loc["all", "trades"]:
            print("\nSummary (closed trades; PF = profit factor, gross wins / gross losses):")
            with pd.option_context("display.width", 220, "display.float_format", "{:,.1f}".format):
                print(s[list(cols)].rename(columns=cols).to_string())

    if res.portfolio:
        pf = res.portfolio
        print(f"\nPortfolio (shared capital, up to {pf['max_positions']} positions): {pf['return_pct']:+.1f}% "
              f"(max drawdown {pf['max_dd_pct']:.1f}%) vs {pf['bench_pct']:+.1f}% for the same money split equally over "
              f"the {pf['stocks']} stocks and held (max drawdown {pf['bench_max_dd_pct']:.1f}%)"
              + (f"; basket held {pf['basket_hold_pct']:+.1f}%" if pf.get("basket_hold_pct") is not None else "")
              + f". Average {pf['avg_positions']:.1f} positions open, invested {pf['in_market_pct']:.0f}% of days, "
              f"end equity {pf['end_equity']:,.0f}.")
    if not res.stocks.empty and not res.portfolio:
        st = res.stocks
        out = pd.DataFrame({
            "window": st["start"].dt.strftime("%Y-%m-%d") + " .. " + st["end"].dt.strftime("%Y-%m-%d"),
            "plan%": st["plan_pct"], "buy&hold%": st["buy_hold_pct"],
            "plan max DD%": st["plan_max_dd_pct"], "B&H max DD%": st["buy_hold_max_dd_pct"],
            "in market%": st["in_market_pct"], "trades": st["trades"], "end equity": st["end_equity"],
        })
        if res.basket:
            out.insert(2, "basket held%", st["basket_hold_pct"])
        many = len(out) > 30 and not show_all
        print("\nPer stock (plan = equity growth with the sizing above; buy & hold = first open to last close, "
              "less one round trip; DD = largest fall from a high)"
              + (f"; best and worst 15 of {len(out)} by plan%:" if many else ":"))
        if many:
            out = out.sort_values("plan%", ascending=False)
            out = pd.concat([out.head(15), out.tail(15)])
        with pd.option_context("display.width", 220, "display.float_format", "{:,.1f}".format):
            print(out.to_string())
        if len(st) > 1:
            print(f"Average stock: plan {st['plan_pct'].mean():+.1f}% vs buy & hold {st['buy_hold_pct'].mean():+.1f}%; "
                  f"plan beat buy & hold on {(st['plan_pct'] > st['buy_hold_pct']).mean() * 100:.0f}% of stocks.")
    if res.basket:
        print(f"\nBasket: {res.basket}, equal weight, bought and sold on each trade's days (vs basket = trade - basket).")
    for line in res.pending:
        print("\nSignal now: " + line)
    if res.warnings:
        print("\nWarnings:")
        for w in res.warnings:
            print("  - " + w)


def _print_casestudy(cs: casestudy.CaseStudy, shortlist: bool) -> None:
    w = cs.window
    print(f"\n=== {cs.code}: {cs.profile} profile, {cs.start:%Y-%m-%d} .. {cs.end:%Y-%m-%d}")
    print(f"Close {w['first_close']:.1f} -> {w['last_close']:.1f} ({w['change_pct']:+.1f}%); "
          f"low {w['low']:.1f} ({w['low_date']:%d %b %Y}), high {w['high']:.1f} ({w['high_date']:%d %b %Y}). "
          f"Last stored close {cs.last_close:.1f} on {cs.last_date:%Y-%m-%d}.")
    print("Quality filter today: " + ("passes" if cs.quality_passed else "FAILS (" + "; ".join(cs.quality_failures) + ")"
                                       + " -> the screen would not show it"))
    if cs.signals.empty:
        print("No signals in this period.")
    else:
        s = cs.signals
        exit_cols = [f"ret_{n}" for n in cs.exits]
        table = pd.DataFrame({
            "date": s["date"].dt.strftime("%Y-%m-%d"),
            "strategy": s["strategy"] + s["role"].map({"primary": "", "confirm": " (confirm)"}),
            "status": s.apply(lambda r: r["status"] if r["status"] == "signal" else "blocked: " + "; ".join(r["blocked_by"]), axis=1),
            "days": s["days_on"],
            "score": s["best_score"],
            "shortlisted": s["cut_date"].map(lambda d: "" if pd.isna(d) else f"{d:%d %b}"),
        })
        if shortlist:
            table["rank"] = s["shortlist_rank"].map(lambda v: "" if pd.isna(v) else f"#{int(v)}")
        table["entry"] = s["entry"]
        for h in cs.horizons:
            table[f"{h}d%"] = s[f"ret_{h}"]
        table[f"best {cs.primary}d%"], table[f"worst {cs.primary}d%"] = s["best"], s["worst"]
        for n, col in zip(cs.exits, exit_cols):
            table[f"{n}%"] = s[col]
            table[f"{n} exit"] = s[f"why_{n}"].fillna("") + " " + s[f"days_{n}"].map(lambda v: "" if pd.isna(v) else f"{int(v)}d")
        table["to last%"] = s["to_last"]
        print(f"\nSignals (first day of each run; days = run length; score = the stock's best ranking score in the run; "
              f"shortlisted = first day it scored >= {cs.min_score:g}"
              + ("; rank = best rank among all stocks" if shortlist else "")
              + f"; entry = next open; returns net of {cs.cost_pct:g}% cost):")
        with pd.option_context("display.width", 260, "display.max_rows", 500, "display.float_format", "{:,.1f}".format):
            print(table.to_string(index=False))
    if len(cs.moves):
        print("\nBig moves starting in this period:")
        for m in cs.moves.itertuples():
            print(f"  {m.date:%Y-%m-%d} at {m.start:.1f} -> peak {m.peak_date:%Y-%m-%d} (+{m.peak_gain_pct:.0f}%): "
                  + ("caught early by " + ", ".join(m.caught_by) if m.caught_by else "not caught early"))


def cmd_research(args, settings, db) -> int:
    from .research import documents, ledger, render, review

    cmd = args.research_cmd
    if cmd == "evening":
        from .research.evening import run_evening

        log_path = _log_to_file(settings, "research")
        try:
            deliver = _deliverer(settings, args.dry_run)
        except TelegramError as exc:
            log.error("%s", exc)
            return 3
        try:
            outcome = run_evening(db, settings, deliver)
        except Exception as exc:
            log.exception("Evening research run failed")
            if not args.dry_run:
                try:
                    deliver(report.build_notice("⚠️ AI review failed", f"{type(exc).__name__}: {exc}\nLog: {log_path}"))
                except Exception:
                    log.exception("Could not send the failure notice either")
            return 1
        log.info("Evening research run: %s", outcome)
        return 0
    if cmd in ("add", "inbox"):
        results = []
        if cmd == "inbox":
            results = documents.scan_inbox(db, settings)
        else:
            for item in args.items:
                try:
                    if item.lower().startswith(("http://", "https://")):
                        results.append(documents.add_url(db, settings, item, args.doc_type))
                    else:
                        results.append(documents.add_file(db, settings, Path(item), args.doc_type))
                except Exception as e:  # noqa: BLE001 - report and continue with the other items
                    print(f"FAILED {item}: {e}")
        for res in results:
            state = "added" if res.created else "already stored"
            print(f"#{res.doc_id} {state}: {res.filename} ({res.doc_type}, {res.published}, {len(res.codes)} stocks mentioned)")
        if not results:
            print("Nothing added.")
        return 0
    if cmd == "list":
        docs = documents.load_docs(db).head(args.limit)
        if docs.empty:
            print("No documents yet. Add some: research add <link>")
            return 0
        docs["stocks"] = docs["codes"].map(len)
        docs["reviewed"] = docs["reviewed"].map({True: "yes", False: ""})
        with pd.option_context("display.width", 200, "display.max_colwidth", 70):
            print(docs[["id", "published", "doc_type", "source", "pages", "stocks", "reviewed", "filename"]].to_string(index=False))
        return 0
    if cmd == "review":
        run = review.run_review(db, settings, args.doc, dry_run=args.dry_run)
        if args.dry_run:
            print(f"Dry run: request for documents {run.doc_ids} (PDF bytes omitted) written to {run.request_file}")
            return 0
        docs = documents.load_docs(db, run.doc_ids)
        print(render.text(run.review, run.as_of))
        u = run.usage or {}
        print(f"\nReview #{run.review_id} saved · {len(run.review.calls)} calls · tokens in {u.get('input_tokens')}, "
              f"out {u.get('output_tokens')}, cache read {u.get('cache_read_input_tokens')}")
        if settings.research.send_telegram and not args.no_send and settings.telegram.enabled:
            TelegramNotifier(settings.telegram.bot_token, settings.telegram.chat_id).send(
                render.telegram_html(run.review, run.as_of, (docs["source"].fillna(docs["filename"])).tolist()))
            print("Sent to Telegram.")
        return 0
    if cmd == "import":
        rv = review.Review.model_validate_json(args.file.read_text(encoding="utf-8"))
        as_of = db.date_range()[1]
        review_id = review.save_review(db, settings, rv, args.doc, as_of, args.model)
        print(f"Review #{review_id} stored (as of {as_of}) with {len(rv.calls)} call(s) in the ledger.")
        return 0
    if cmd == "show":
        reviews = review.load_reviews(db)
        if reviews.empty:
            print("No reviews yet.")
            return 0
        row = reviews.iloc[0] if args.id is None else reviews[reviews["id"] == args.id].iloc[0]
        print(f"Review #{row['id']} · {row['created_at']} · {row['model']} · documents {row['doc_ids']}\n")
        print(render.text(review.Review.model_validate(row["review"]), row["as_of"]))
        return 0
    if cmd == "score":
        n = ledger.score_calls(db, settings)
        print(f"Scored {n} call(s).")
        with pd.option_context("display.float_format", "{:,.1f}".format):
            print(ledger.calibration_table(db).to_string(index=False))
        return 0
    raise SystemExit(f"unknown research command {cmd}")


def cmd_api(args, settings, db) -> int:
    import uvicorn

    db.close()
    # Bound to this PC only: the API can trigger screens and serves your data
    uvicorn.run("dse_screener.api.app:app", host="127.0.0.1", port=args.port, reload=args.reload)
    return 0


def cmd_telegram_setup(args, settings, db) -> int:
    token = settings.telegram.bot_token
    if not token:
        print("No bot token yet. Steps:\n"
              "  1. In Telegram, message @BotFather and send /newbot\n"
              "  2. Copy config/secrets.example.yaml to config/secrets.yaml and paste the token as bot_token\n"
              "  3. Send your new bot any message (e.g. 'hi')\n"
              "  4. Run this command again")
        return 1
    chats = find_chat_ids(token)
    if not chats:
        print("The bot hasn't received any messages yet. Send it a message in Telegram, then run this again.")
        return 1
    for c in chats:
        print(f"  chat {c['id']}  {c['name']}  ({c['type']})")
    chosen = chats[-1]
    path = save_secret("telegram", "chat_id", chosen["id"])
    print(f"Saved chat_id {chosen['id']} ({chosen['name']}) to {path}. Next: python -m dse_screener telegram-test")
    return 0


def cmd_telegram_test(args, settings, db) -> int:
    n = _deliverer(settings, dry_run=False)(
        report.build_notice("✅ DSE Screener connected", "You'll get the daily summary here around 3pm, Sun–Thu.")
    )
    print(f"Sent {n} message(s). Check Telegram.")
    return 0


def cmd_status(args, settings, db) -> int:
    first, last = db.date_range()
    if not first:
        print("Database is empty. Run: python -m dse_screener backfill")
        return 0
    per_day = db.rows_per_day()
    print(f"Prices: {first} .. {last}, {len(per_day)} trading days, {int(per_day.sum()):,} rows")
    print(f"Instruments per day: min {per_day.min()}, median {int(per_day.median())}, max {per_day.max()}")

    codes = universe_codes(args.universe, db)
    prices = db.load_prices(codes)
    counts = prices.groupby("code").size().reindex(codes, fill_value=0)
    missing = counts[counts == 0].index.tolist()
    print(f"{args.universe}: {len(codes) - len(missing)}/{len(codes)} codes have prices, "
          f"days per code min {counts.min()} / max {counts.max()}")
    if missing:
        print(f"  no prices for: {', '.join(missing)}")

    companies = db.load_companies(codes)
    news = db.load_news(codes)
    print(f"Fundamentals: {len(companies)}/{len(codes)} company profiles, {len(news)} news items")
    actions = db.load_corporate_actions(codes)
    print(f"Corporate actions: {len(actions)} (run `actions` to list)")
    return 0


COMMANDS = {
    "backfill": cmd_backfill,
    "ingest": cmd_ingest,
    "market": cmd_market,
    "fundamentals": cmd_fundamentals,
    "discover": cmd_discover,
    "actions": cmd_actions,
    "quality": cmd_quality,
    "screen": cmd_screen,
    "daily": cmd_daily,
    "report": cmd_report,
    "api": cmd_api,
    "backtest": cmd_backtest,
    "tune": cmd_tune,
    "casestudy": cmd_casestudy,
    "moves": cmd_moves,
    "simulate": cmd_simulate,
    "research": cmd_research,
    "bot": cmd_bot,
    "holdings": cmd_holdings,
    "telegram-setup": cmd_telegram_setup,
    "telegram-test": cmd_telegram_test,
    "status": cmd_status,
}

if __name__ == "__main__":
    sys.exit(main())
