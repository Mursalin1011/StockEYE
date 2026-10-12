# StockEYE

A configurable, multi-strategy stock screener for the Dhaka Stock Exchange (DSE). It stores
daily market data, runs your strategies every trading day, sends an explained shortlist to
Telegram around 3pm, and has a web dashboard for charts, fundamentals and backtests.

Plans: [product brief](docs/01-product-brief.md) · [MVP spec](docs/02-mvp-spec.md) · [trade lab](docs/06-trade-lab-plan.md)

> Screening output from your own rules. Not investment advice.

## Architecture

```
DSE websites ──► Python engine (src/dse_screener) ──► SQLite (data/dse.sqlite)
                   │  ingest · adjust · quality · strategies · ranking · backtest
                   ├──► daily job ──► Telegram (3pm, Sun–Thu)
                   └──► FastAPI (src/dse_screener/api) ──► Next.js dashboard (web/)
```

- **Python** does all data and analysis. Every number lives in YAML under `config/`.
- **FastAPI** serves it as JSON on `127.0.0.1:8000` (docs at `/api/docs`).
- **Next.js 16** (`web/`) is the dashboard. It only talks to the API, so it can grow into a
  full platform (accounts, more markets, mobile) without touching the analysis code.

## Setup (Windows)

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api,research]"
cd web; npm install; cd ..
```

## Run the dashboard

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1    # API + dashboard
```

Then open http://127.0.0.1:3000. Both servers listen on this PC only. Or start them separately:
`python -m dse_screener api` and `npm run dev` inside `web/`.

| Page | What it shows |
|---|---|
| Picks | Each day's shortlist per profile: score, strategies, reasons, recent DSE news; **setups to watch** (second breakouts still forming: the close and volume needed, days left) and **all signals** (incl. below the cut, filter by strategy) |
| Holdings | Your positions with the same checks as the 3pm message (P/L, stop, MA20, warnings, record dates, news), a form to add buys, sells and stops, re-entry alerts, closed positions, and every entry with undo/delete. Telegram entries show up here too |
| Stocks | The universe with key figures and quality pass/fail per profile |
| Stock page | Candles + signal markers + ex-dates, volume, **RSI(14)**, **MACD(12,26,9)**; fundamentals, shareholding, dividends, news |
| History | What was picked on each day |
| Big moves | Every +50% run-up in **any** stock (quality filter not applied), which strategies caught it early, and every stock your strategies flagged, with filters (quality, liquidity, strategy, date). Rebuilt by the daily job after the summary |
| Quality | The "good business" filter, metric by metric, with why a stock failed |
| Backtest | What would have happened if you'd bought the shortlist, vs a quality-stock basket |
| Settings | The YAML config (read-only for now) |

## How stocks are chosen

Every trading day, for each profile (`swing`, `position`):

1. **Quality filter** over all ~320 active DSE equities: by default **Category A**, liquid (≥ BDT 3 mn
   traded per day for swing, 5 mn for position), no insurers, plus dividend streak, profitable years,
   P/E cap and sponsor + government holding. About 70 stocks pass for swing, 50 for position. The rules
   came from what your seed stocks (GP, BATBC, SQURPHARMA, LHB, BSC) have in common.
2. **Strategies** run on the price history, adjusted for dividends and bonus shares. Each returns a
   0–100 score plus reasons:
   - **Quiet accumulation** (your method): volume well above its own baseline, price nearly flat,
     volume growth much bigger than the price move.
   - **Base breakout**: the close breaks above a tight N-day range on high volume.
   - **Second breakout** (swing): a breakout fell back into its base (shakeout), then the close clears
     that breakout's high on high volume within 40 days. The MACD filter doesn't apply to it.
     While a shakeout is waiting for its re-break it shows under **Setups to watch** (about 1 in 3 of
     those became a second breakout over the 2-year history).
   - **Big hands** (confirmation only): average trade size rising, i.e. fewer, larger trades.
3. **Ranking**: the best primary strategy score × its weight, +10 per extra strategy that agrees,
   + boosts (e.g. institutional holding rising), − a penalty near record dates (dividend-driven volume).
4. Stocks scoring at least `min_score` make the shortlist (top 10).

## How to edit parameters

All numbers are in YAML, so no code changes are needed:

| File | What it controls |
|---|---|
| `config/profiles/swing.yaml`, `position.yaml`, `trend.yaml` | quality rules, strategy parameters and weights, ranking, backtest settings (`trend`: the 20/50 golden cross list, docs/05 W10) |
| `config/plans/*.yaml` | trade lab plans: your own entry/exit rules for `simulate` |
| `config/settings.yaml` | data sources, the daily job (times, retries), Telegram summary, adjustments |
| `config/universes/all_equities.yaml` | default universe: every active DSE equity (resolved from stored company pages, so new listings join automatically); `ds30.yaml` is the blue-chip list |
| `config/secrets.yaml` | Telegram token and chat id (git-ignored, never shown in the dashboard) |

Example: require stronger volume for quiet accumulation in the swing profile:

```yaml
# config/profiles/swing.yaml
strategies:
  quiet_accumulation:
    weight: 1.0
    params:
      min_volume_ratio: 2.0     # was 1.5
```

Every parameter and its default is documented in `src/dse_screener/strategies/<name>.py`
(`class Params`). A typo in a parameter name fails loudly instead of being silently ignored.

**Test a change before saving it.** `--set` overrides any value just for that run:

```powershell
.\.venv\Scripts\python.exe -m dse_screener backtest --profile swing --set strategies.quiet_accumulation.params.min_volume_ratio=2
.\.venv\Scripts\python.exe -m dse_screener tune --profile swing --grid strategies.quiet_accumulation.params.min_volume_ratio=1.5,2,2.5
```

`tune` chooses settings on the tuning period (up to `backtest.in_sample_until`) and shows how they did
on the later, untouched test period, which is the honest check.

The backtest reports median **and** mean, profit factor (gross wins / gross losses), average win/loss,
the fixed holding periods in `backtest.horizons`, any exit styles in `backtest.exits` (e.g.
`stop8_ma20: {stop_pct: 8, trail_ma: 20, max_days: 60}`), and **recall**: how many big run-ups
(`backtest.winners`, default +50% within 120 days) the shortlist and each strategy caught early.

**Check a stock you spotted.** `casestudy` shows every signal on one stock over a period, with outcomes
(also the dashboard's **Case study** page):

```powershell
.\.venv\Scripts\python.exe -m dse_screener casestudy PTL --from 2025-11-01 [--profile swing] [--shortlist]
```

**See every big move and what caught it.** `moves` scans every stock (not only the quality ones) for big
run-ups (`backtest.winners`) and lists which strategies of every profile caught each early, plus every
strategy signal (also the dashboard's **Big moves** page). The scan takes about a minute, so it is stored:
the daily job rebuilds it after sending the summary, and the page rebuilds it on the first visit after new
prices or a profile change.

```powershell
.\.venv\Scripts\python.exe -m dse_screener moves [--top 25] [--rebuild]
```

**Test your own rules (trade lab).** `simulate` runs a trade plan (your entry, exit and hold rules) on any
stock(s) and period: every trade, stats, equity vs buy-and-hold ([docs/06](docs/06-trade-lab-plan.md)).
Use a saved plan from `config/plans/`, flags, or both (flags win):

```powershell
.\.venv\Scripts\python.exe -m dse_screener simulate PTL --plan breakout-swing --from 2025-01-01
.\.venv\Scripts\python.exe -m dse_screener simulate PTL BXPHARMA --when "close > sma_50" --when "rsi_14 < 50" --stop 7 --target 15 --max-days 30
.\.venv\Scripts\python.exe -m dse_screener simulate PTL --dates 2025-11-13,2026-04-12 --trail-ma 50 --stop 10
```

`simulate --help` lists every column a condition can use (`sma_N`, `rsi_N`, `high_N`, `vol_x_N`, ...).
Add `--basket swing` to compare each trade with an equal-weight basket of the swing profile's quality stocks.
The dashboard's **Trade lab** page does the same with a form: build the rules, run, see the trades on the
chart and the equity curve against buy & hold, and save the plan to `config/plans/`.

Many stocks at once, with shared capital, and a parameter grid (tuning vs test period):

```powershell
.\.venv\Scripts\python.exe -m dse_screener simulate --plan breakout-swing --universe all_equities --quality swing --portfolio 5 --from 2025-01-01
.\.venv\Scripts\python.exe -m dse_screener simulate --plan breakout-swing --universe ds30 --portfolio 5 --grid exit.stop_pct=5,8,12 --grid exit.trail_ma=10,20,50
```

## AI research review

Broker PDFs (newsflash, market review, monetary policy review, company research) are read by Claude
together with StockEYE's own data on every stock they mention, and turned into a market view,
sector views and stock calls with confidence, horizon and "wrong if" conditions.

- **The analyst's instructions** are in [`config/research/ANALYST.md`](config/research/ANALYST.md):
  your method, ground rules, how to read each report type, DSE realities, the confidence scale.
  Edit it to change how it judges.
- **Sources** are recognised by [`config/research/sources.yaml`](config/research/sources.yaml)
  (publisher, report type). Add a rule for each new publisher; unknown documents still work.
- **Every call is scored** against the quality-stock basket once its horizon has passed
  (`research score`, also run by the daily job); the analyst sees its own track record next time.

```powershell
# one-time: an API key from platform.claude.com, in config/secrets.yaml -> anthropic: {api_key: ...}
.\.venv\Scripts\python.exe -m dse_screener research add https://…/SSL-Newsflash-October-1-2026-….pdf
.\.venv\Scripts\python.exe -m dse_screener research inbox      # or drop PDFs into data/inbox/pdf/
.\.venv\Scripts\python.exe -m dse_screener research review     # unreviewed recent documents -> review + Telegram
.\.venv\Scripts\python.exe -m dse_screener research review --dry-run   # see exactly what would be sent
.\.venv\Scripts\python.exe -m dse_screener research show       # print the latest review
.\.venv\Scripts\python.exe -m dse_screener research score      # score matured calls, calibration table
.\.venv\Scripts\python.exe -m dse_screener research import review.json --doc 1 --doc 2   # store a review written elsewhere
```

**Evening job** (Sun–Thu 22:30, after the market review usually arrives): imports `data/inbox/pdf/`,
scores matured calls, reviews new documents and sends the summary to Telegram. It stays silent when
nothing is new. Logs: `data/logs/research-YYYY-MM-DD.log`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_research_task.ps1
& $py -m dse_screener research evening --dry-run    # same job, printed instead of sent
```

The dashboard's **Research** page does the same: add links, import the inbox, run a review, read it,
and see the track record. A review of three PDFs (~30 pages) costs roughly USD 0.40–0.70 with
`claude-opus-5-5` at `effort: high` (settings.yaml → `research`). Broker reports are marked "not for
public distribution": they stay in `data/` (git-ignored) and are only sent to the Claude API.

## Daily Telegram summary

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. Copy `config/secrets.example.yaml` to `config/secrets.yaml` and paste the token as `bot_token`.
3. Send your bot any message, then run `telegram-setup` (saves your chat id) and `telegram-test`.
4. Schedule it (Sun–Thu, 14:40; it runs later if the PC was off):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
   ```
   Logs: `data/logs/daily-YYYY-MM-DD.log`. Remove with `Unregister-ScheduledTask -TaskName "DSE Screener"`.

## Your positions (holdings tracker)

Tell the bot what you bought and sold (or use the dashboard's **Holdings** page: same ledger, same checks);
the 3pm summary then opens with **Your positions**:

| Send | Means |
|---|---|
| `/bought PTL 53.7 500` | bought 500 PTL at 53.7 today (shares optional; add a date `5/10` or `2026-10-05`, and `stop 48`) |
| `/sold PTL 60` | sold the whole position (`/sold PTL 60 200` for part) |
| `/stop PTL 48` | set your stop (`off` = the default, 8% below your average cost) |
| `/holdings` | your positions as of the latest close |
| `/undo` | remove your last entry |

Each position shows the close, P/L (% and taka), where your stop and MA20 are, and warnings:
closed below the stop (or touched it intraday), close to the stop, below MA20, heavy selling (a 2%+
drop on 2× volume), an upcoming record date, today's signals and recent news. After you sell, a 🔁
line appears when a strategy signals that stock again within 60 days. Dividends and bonus shares
after a buy adjust the average cost. All thresholds: `holdings:` in `config/settings.yaml`.

For instant replies, keep the bot running (starts at logon, restarts itself if it stops):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_bot_task.ps1
```

Without it the 3pm job still reads your messages first, but Telegram keeps unread messages only
24 hours (a Thursday-evening `/bought` would be gone by Sunday). Only messages from your own chat
(`chat_id`) are acted on. The same commands work locally: `python -m dse_screener holdings bought PTL 53.7 500`.

## Commands

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m dse_screener backfill        # download all available history (~2 years), resumable
& $py -m dse_screener ingest          # fetch today (or --date 2026-09-30)
& $py -m dse_screener market          # DSE's official daily totals (incl. block trades) for the stored history
& $py -m dse_screener discover        # company pages for new listings (the daily job does this too)
& $py -m dse_screener fundamentals --universe all_equities   # refresh company pages + news
& $py -m dse_screener actions         # list dividend/bonus events, checked against ex-date opens
& $py -m dse_screener quality --profile position
& $py -m dse_screener screen          # run all profiles, saved (add --date; --all-signals adds setups to watch)
& $py -m dse_screener daily --dry-run # the full 3pm job, printing instead of sending
& $py -m dse_screener report          # preview the summary from stored data (--send to send)
& $py -m dse_screener backtest --profile swing [--set PATH=VALUE] [--csv trades.csv]
& $py -m dse_screener tune --profile swing --grid PATH=V1,V2
& $py -m dse_screener casestudy PTL --from 2025-11-01   # every signal on one stock, with outcomes
& $py -m dse_screener moves           # big moves in every stock and which strategies caught them
& $py -m dse_screener simulate PTL --plan breakout-swing   # your own entry/exit rules on any stock
& $py -m dse_screener research add <link> ; research review   # AI review of research PDFs
& $py -m dse_screener holdings        # your positions (or: holdings bought PTL 53.7 500, holdings undo)
& $py -m dse_screener bot             # answer Telegram commands (/bought, /sold, ...); --once to drain and exit
& $py -m dse_screener api             # API for the dashboard
& $py -m pytest                       # tests
```

## Layout

```
config/                    # all settings and strategy numbers (YAML)
src/dse_screener/
  sources/                 # one adapter per website: archive (prices), company page, news
  db.py                    # SQLite storage (raw prices are never modified)
  ingest.py, fundamentals.py, corporate_actions.py, adjust.py
  quality.py, rules.py     # quality metrics and the YAML rule engine
  indicators.py            # RSI, MACD, moving averages, ATR
  features.py              # named columns for trade-plan conditions (sma_50, rsi_14, high_20, ...)
  strategies/              # one file per strategy; register new ones in strategies/__init__.py
  engine.py                # filter -> strategies -> ranking (shared by live screen and backtest)
  backtest.py              # next-day entry, costs, benchmark, non-overlapping trades, exit styles, recall
  casestudy.py             # one stock over a period: every signal, outcome and big move
  simulate.py              # trade lab: your own entry/exit/hold rules on any stock, trades + equity
  research/                # AI review: documents, StockEYE context, Claude review, prediction ledger
  daily.py, report.py, notify/   # the 3pm job and Telegram
  holdings.py, bot.py      # your positions: ledger, daily check, Telegram commands
  api/app.py               # FastAPI for the dashboard
web/                       # Next.js 16 dashboard (App Router, Tailwind, TradingView Lightweight Charts)
scripts/                   # dev.ps1, run_daily.ps1, register_task.ps1, run_bot.ps1, register_bot_task.ps1
data/                      # created on first run: dse.sqlite + raw pages + logs (git-ignored)
```

## Notes

- The DSE archive only serves a rolling ~2 years. **Back up `data/dse.sqlite`**: older history
  can't be downloaded again.
- Raw pages are saved gzipped in `data/raw/`, so a parser fix can be re-run without re-downloading.
