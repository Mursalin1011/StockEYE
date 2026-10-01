# StockEYE

A configurable, multi-strategy stock screener for the Dhaka Stock Exchange (DSE). It stores
daily market data, runs your strategies every trading day, sends an explained shortlist to
Telegram around 3pm, and has a web dashboard for charts, fundamentals and backtests.

Plans: [product brief](docs/01-product-brief.md) · [MVP spec](docs/02-mvp-spec.md)

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
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
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
| Picks | Each day's shortlist per profile: score, strategies, reasons, recent DSE news |
| Stocks | The universe with key figures and quality pass/fail per profile |
| Stock page | Candles + signal markers + ex-dates, volume, **RSI(14)**, **MACD(12,26,9)**; fundamentals, shareholding, dividends, news |
| History | What was picked on each day |
| Quality | The "good business" filter, metric by metric, with why a stock failed |
| Backtest | What would have happened if you'd bought the shortlist, vs a quality-stock basket |
| Settings | The YAML config (read-only for now) |

## How stocks are chosen

Every trading day, for each profile (`swing`, `position`):

1. **Quality filter**: rules such as Category A, dividend streak, profitable 5/5 years, P/E cap,
   sponsor + government holding. Stocks that fail are excluded. These rules came from what your
   seed stocks (GP, BATBC, SQURPHARMA, LHB, BSC) have in common.
2. **Strategies** run on the price history, adjusted for dividends and bonus shares. Each returns a
   0–100 score plus reasons:
   - **Quiet accumulation** (your method): volume well above its own baseline, price nearly flat,
     volume growth much bigger than the price move.
   - **Base breakout**: the close breaks above a tight N-day range on high volume.
   - **Big hands** (confirmation only): average trade size rising, i.e. fewer, larger trades.
3. **Ranking**: the best primary strategy score × its weight, +10 per extra strategy that agrees,
   + boosts (e.g. institutional holding rising), − a penalty near record dates (dividend-driven volume).
4. Stocks scoring at least `min_score` make the shortlist (top 10).

## How to edit parameters

All numbers are in YAML, so no code changes are needed:

| File | What it controls |
|---|---|
| `config/profiles/swing.yaml`, `position.yaml` | quality rules, strategy parameters and weights, ranking, backtest settings |
| `config/settings.yaml` | data sources, the daily job (times, retries), Telegram summary, adjustments |
| `config/universes/ds30.yaml` | which stocks are scanned (update after DSE's Jan/Jul rebalance) |
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

## Daily Telegram summary

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. Copy `config/secrets.example.yaml` to `config/secrets.yaml` and paste the token as `bot_token`.
3. Send your bot any message, then run `telegram-setup` (saves your chat id) and `telegram-test`.
4. Schedule it (Sun–Thu, 14:40; it runs later if the PC was off):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
   ```
   Logs: `data/logs/daily-YYYY-MM-DD.log`. Remove with `Unregister-ScheduledTask -TaskName "DSE Screener"`.

## Commands

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m dse_screener backfill        # download all available history (~2 years), resumable
& $py -m dse_screener ingest          # fetch today (or --date 2026-09-30)
& $py -m dse_screener fundamentals    # company pages + news, rebuild dividend/bonus events
& $py -m dse_screener actions         # list dividend/bonus events, checked against ex-date opens
& $py -m dse_screener quality --profile position
& $py -m dse_screener screen          # run all profiles, saved (add --date, --all-signals)
& $py -m dse_screener daily --dry-run # the full 3pm job, printing instead of sending
& $py -m dse_screener report          # preview the summary from stored data (--send to send)
& $py -m dse_screener backtest --profile swing [--set PATH=VALUE] [--csv trades.csv]
& $py -m dse_screener tune --profile swing --grid PATH=V1,V2
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
  indicators.py            # RSI, MACD, moving averages
  strategies/              # one file per strategy; register new ones in strategies/__init__.py
  engine.py                # filter -> strategies -> ranking (shared by live screen and backtest)
  backtest.py              # next-day entry, costs, benchmark, non-overlapping trades
  daily.py, report.py, notify/   # the 3pm job and Telegram
  api/app.py               # FastAPI for the dashboard
web/                       # Next.js 16 dashboard (App Router, Tailwind, TradingView Lightweight Charts)
scripts/                   # dev.ps1, run_daily.ps1, register_task.ps1
data/                      # created on first run: dse.sqlite + raw pages + logs (git-ignored)
```

## Notes

- The DSE archive only serves a rolling ~2 years. **Back up `data/dse.sqlite`**: older history
  can't be downloaded again.
- Raw pages are saved gzipped in `data/raw/`, so a parser fix can be re-run without re-downloading.
