# DSE Stock Screener

A configurable, multi-strategy screener for the Dhaka Stock Exchange. It stores daily
market data, runs your strategies every trading day, and sends a short explained
shortlist around 3pm.

Plans: [product brief](docs/01-product-brief.md) · [MVP spec](docs/02-mvp-spec.md)

> Screening output from your own rules. Not investment advice.

## Setup (Windows)

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,dashboard]"
```

## Dashboard

```powershell
.\.venv\Scripts\python.exe -m dse_screener dashboard     # opens http://127.0.0.1:8501 (this PC only)
```

- **Picks**: each saved daily screen, with reasons, recent news and a chart.
- **Stock explorer**: any DS30 stock, with every past signal of a profile's strategies marked on the chart.
- **History**: what was picked on each day.
- **Quality**: the quality filter, metric by metric.
- **Settings**: your config, read-only.

Charts mark the first day of each signal (circle = quiet accumulation, triangle = breakout, diamond = big hands).
Dotted lines are dividend/bonus ex-dates.

## Daily Telegram summary

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. Copy `config/secrets.example.yaml` to `config/secrets.yaml` and paste the token as `bot_token`.
3. Send your new bot any message, then:
   ```powershell
   .\.venv\Scripts\python.exe -m dse_screener telegram-setup   # finds and saves your chat id
   .\.venv\Scripts\python.exe -m dse_screener telegram-test    # sends a test message
   ```
4. Schedule it (Sun–Thu, 14:40; runs later if the PC was off):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
   ```
   Logs: `data/logs/daily-YYYY-MM-DD.log`. Remove with `Unregister-ScheduledTask -TaskName "DSE Screener"`.

The PC must be on (or asleep; the task wakes it) around 3pm. Settings are under `daily:`, `report:` and
`telegram:` in `config/settings.yaml`.

## Commands

```powershell
.\.venv\Scripts\python.exe -m dse_screener backfill      # download all available history (~2 years), resumable
.\.venv\Scripts\python.exe -m dse_screener ingest        # fetch today (or --date 2026-09-30)
.\.venv\Scripts\python.exe -m dse_screener fundamentals  # company pages + news for DS30, rebuild corporate actions
.\.venv\Scripts\python.exe -m dse_screener actions       # list dividends/bonus events and check them vs ex-date opens
.\.venv\Scripts\python.exe -m dse_screener quality --profile position   # quality metrics + filter result
.\.venv\Scripts\python.exe -m dse_screener screen        # run all profiles: ranked, explained shortlist (saved)
.\.venv\Scripts\python.exe -m dse_screener screen --profile swing --date 2026-06-15 --all-signals
.\.venv\Scripts\python.exe -m dse_screener daily --dry-run   # the full 3pm job, printing instead of sending
.\.venv\Scripts\python.exe -m dse_screener report            # preview the summary from stored data (--send to send)
.\.venv\Scripts\python.exe -m dse_screener status        # what is stored
.\.venv\Scripts\python.exe -m pytest                     # tests
```

## Layout

```
config/
  settings.yaml            # paths, source settings, thresholds for ingest/adjustments
  universes/ds30.yaml      # DS30 list (update after the Jan/Jul rebalance)
  universes/quality_seed.yaml
  profiles/position.yaml   # 3-12 month holds: quality rules (strategies from M3)
  profiles/swing.yaml      # 2-6 week holds
src/dse_screener/
  sources/                 # one adapter per website: archive (prices), company page, news
  db.py                    # SQLite storage (raw prices are never modified)
  ingest.py                # price backfill + daily fetch
  fundamentals.py          # company pages + news refresh
  corporate_actions.py     # dividend/bonus events from news -> adjustment factors
  adjust.py                # back-adjust prices and volume
  quality.py, rules.py     # quality metrics and the YAML rule engine
  strategies/              # one file per strategy; register new ones in strategies/__init__.py
  engine.py                # filter -> strategies -> ranking; pure function reused by backtests
  daily.py                 # the scheduled job
  report.py                # builds the Telegram message
  notify/                  # delivery channels (Telegram; email later)
  dashboard/               # Streamlit app (app.py) and Plotly charts (charts.py)
  cli.py
scripts/                   # run_daily.ps1 (what the task runs), register_task.ps1
data/                      # created on first run: dse.sqlite + gzipped raw pages (git-ignored)
```

## Notes

- The DSE archive only serves a rolling ~2 years. Everything fetched is kept in `data/`, so
  **back up `data/dse.sqlite`**, because older history can't be downloaded again.
- Raw pages are saved gzipped in `data/raw/`, so a parser fix can be re-run without re-downloading.
