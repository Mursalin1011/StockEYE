# DSE Stock Screener — MVP Spec

_Status: Draft v0.1 · 2026-09-30_

## 1. MVP goal

> On every DSE trading day, by around 3pm, send the owner a ranked, explained shortlist of
> DS30 stocks from several configurable strategies, with a dashboard to inspect each pick
> and a backtest showing how each strategy did historically.

## 2. Scope

| ✅ In MVP | ⏭️ Later |
|---|---|
| Universe = DS30 (config list); engine works for all stocks | All ~390 listed companies (a config switch) |
| Daily end-of-day OHLCV + trade count + value from DSE | Intraday / live data |
| Backfill of all available history (~2 yrs) and daily accumulation from now on | Deeper history (pre-2024) from other sources |
| Adjustment for bonus/rights issues | Manual corporate-action reconciliation UI |
| Basic fundamentals snapshot: sector, category, EPS, NAV, P/E, dividend history | Parsing financial statement PDFs |
| **3 strategies + 2 filters**, all numbers in YAML | Visual rule builder (no-code) |
| Backtest-lite: forward returns after each signal | Full portfolio backtest with costs and slippage |
| Streamlit dashboard: ranked list, reasons, price/volume chart | Web app, user accounts |
| Two profiles: `swing` and `position` | Unlimited user-defined profiles |
| | Broker research PDF extraction (Phase 2) |
| Telegram and email summary at ~15:00 BST | Push/mobile app, intraday alerts |
| Source adapters: DSE (primary), amarstock / LankaBD (secondary) | More sources, CSE |
| | Monthly shareholding tracking, PSI news with AI summaries |

## 3. Data sources (checked 2026-09-30)

| Source | What works | Use |
|---|---|---|
| **old.dsebd.org/day_end_archive.php** | ✅ `?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&inst=<CODE or All Instrument>&archive=data` returns DATE, CODE, LTP, HIGH, LOW, OPEN, CLOSE, **YCP**, **TRADE (count)**, VALUE (mn), VOLUME. One request for all instruments on a day returns ~634 rows. | **Primary price source** |
| ⚠️ Same archive | History is a **rolling ~2-year window** (min date 2024-09-30). Older data is gone, and each day another day drops off. | **Backfill immediately and store permanently** |
| **dse.com.bd** (new site, Next.js) | Pages for `/company/<CODE>`, `/corporate-actions`, `/filings/psi`, `/indices/DS30`, `/markets/latest-share-price`. Some data loads client-side. | Fundamentals, corporate actions, PSI (Phase 2) |
| www.dsebd.org old paths | ❌ Return HTTP 410 and redirect to dse.com.bd | — |
| amarstock.com, lankabd.com | ✅ Reachable (HTTP 200). Endpoints not mapped yet. | Fallback prices, older history, fundamentals |

**DS30 list:** kept as a config file and updated twice a year (January and July rebalancing).
In July 2026 BSRMLTD, ACMELAB and POWERGRID were added, and KOHINOOR, UNIQUEHRL and LINDEBD removed (effective July 19).
The full current list still needs confirming. The DS30 page loads it client-side.

## 4. Architecture

```
          ┌──────────── sources/ (adapters, one per site) ────────────┐
          │  dse_archive   dse_company   amarstock   lankabd   pdf… │
          └───────────────────────────┬───────────────────────────────┘
                                      ▼
  scheduler ─► ingest ─► validate ─► store (SQLite) ─► adjust (corp. actions)
  (Task Sched,                                              │
   Sun–Thu 14:55)                                           ▼
                                                 indicators (shared library)
                                                            │
                          filters ─► strategies (plugins, YAML params) ─► scores + reasons
                                                            │
                                ┌───────────────┬───────────┴───────┐
                                ▼               ▼                   ▼
                          notify (Telegram,  dashboard          backtest-lite
                           email)            (Streamlit)
```

### 4.1 Tech stack
Python 3.12+, `requests` + `BeautifulSoup`/`lxml`, `pandas`, **SQLite** behind a small repository layer
(so it can move to Postgres for the product later), `pydantic` for config validation, Streamlit, `plotly`
for charts, `python-telegram-bot` or plain HTTP to the Telegram Bot API, `smtplib` for email, Windows Task Scheduler.

### 4.2 Source adapter contract
```python
class PriceSource(Protocol):
    name: str
    def fetch_day(self, date: date) -> pd.DataFrame: ...              # all instruments, one day
    def fetch_range(self, code: str, start: date, end: date) -> pd.DataFrame: ...
```
Every adapter returns the **same normalized columns**. Adding a source means adding a new file, with no changes to the engine.

### 4.3 Adjustment for corporate actions
~~Plan v0.1: derive factors from YCP.~~ **Disproved on real data (2026-09-30):** the archive's YCP equals the previous
close in 311,769 of 311,777 rows, so it is *not* adjusted for bonus issues.

**Built in M2** (`corporate_actions.py`, `adjust.py`):
1. **DSE resets the reference price for cash and stock dividends**: `new_ref = (close − cash% × face) / (1 + stock%)`.
   Checked on real data: EBL FY2024 predicted 21.49, opened 21.3; GP 327.1 vs 331.0.
2. **Events and record dates** come from the per-company news archive (`old_news.php?inst=CODE&criteria=3`, ~2 years).
   Declarations without a record date (GP interims) are linked to the later "suspended on record date" notice.
3. **Final amounts** come from the company page. The AGM can revise the Board's recommendation after the record date
   (PUBALIBANK FY2025: 15%+15% → 10% cash + 20% stock). When the stock % differs, the page's approved figures win.
4. **Ex-date** is the first trading day after the record date. Prices before it are × factor; volume is × (1 + stock%).
   Cash adjustment can be switched off (`adjustments.adjust_cash_dividends`).
5. **Result for DS30:** 59 events across 28 stocks. Days with drops beyond the circuit limit went from 13 to 2, and the
   remaining 2 are real (price limit is lifted on "No Dividend" declaration days).

**No-trade days:** the archive prints open/high/low = 0 on days without trades (40% of all rows: suspensions, bonds,
illiquid stocks). These are stored as missing; close stays as DSE's carried value.

### 4.4 Data model (MVP)
- `instruments` (code, name, sector, category, is_ds30, listed_date)
- `daily_prices` (code, date, open, high, low, close, ltp, ycp, trades, value_mn, volume, source), raw and never modified
- `adjustments` (code, ex_date, factor, detected_by)
- `fundamentals` (code, as_of, eps, nav, pe, dividend_history_json, sponsor_pct, …)
- `strategy_runs` (run_id, date, profile, config_hash, status)
- `signals` (run_id, code, strategy, score, reasons_json)

## 5. Strategies (MVP)

A strategy is a Python class plus a YAML block. The class defines *how* it works, the YAML sets *the numbers*.

```python
class Strategy(ABC):
    name: str
    Params: type[BaseModel]                      # validated from YAML
    def evaluate(self, prices: pd.DataFrame, fundamentals: pd.Series, p) -> Signal | None:
        """Return Signal(score 0-100, reasons=[...]) or None"""
```

| # | Strategy | Idea | Key params |
|---|---|---|---|
| S1 | **quiet_accumulation** (yours) | Price stable, volume rising, volume growth ≫ price growth | lookback windows, max price range %, min volume ratio, divergence ratio |
| S2 | **base_breakout** | Close breaks above an N-day range on high volume | base length, max base range %, breakout volume multiple |
| S3 | **big_hands** (trade-size surge) | Volume ÷ trades rising, i.e. fewer but larger trades | window, min trade-size growth |
| S4 | **second_breakout** (re-entry after a shakeout) | A base breakout falls back into the base, then the close clears its high on volume | first-breakout params, window, re-break volume multiple, max undercut of the base low |
| F1 | **quality_filter** | Gate: category, profitability, dividends, market cap | allowed categories, min EPS, min dividend years |
| F2 | **red_flags** | Exclude/penalize: Z category, tiny float, spike with no news, abnormal turnover | thresholds |

### Example config (`config/profiles/swing.yaml`; `position.yaml` has the same shape with longer windows)
```yaml
universe: ds30            # ds30 | all | watchlist:<name>
filters:
  quality_filter: { categories: [A, B], min_eps_ttm: 0, min_dividend_years: 3 }
  red_flags:      { max_daily_turnover_pct_of_float: 5, penalize_only: false }
strategies:
  quiet_accumulation:
    enabled: true
    weight: 1.0
    price_window_days: 60
    max_price_range_pct: 12        # (high-low)/low over window
    vol_short_days: 20
    vol_long_days: 60
    min_volume_ratio: 1.5          # avg vol 20d / avg vol 60d
    min_divergence: 3.0            # volume % growth ÷ |price % growth|
  base_breakout: { enabled: true, weight: 0.8, base_days: 40, max_base_range_pct: 10, min_breakout_vol_x: 2.0 }
  big_hands:     { enabled: true, weight: 0.6, window_days: 20, min_trade_size_growth: 1.3 }
report: { top_n: 10, min_score: 50, channels: [telegram, email] }
```
_All the numbers above are placeholder defaults to be tuned with the backtest._

## 6. Daily run

| Time (BST, Sun–Thu) | Step |
|---|---|
| 14:30 | Market closes |
| 14:55 | Job starts. It fetches today's day-end data and **retries every 5 min until 15:30** if the data is incomplete. |
| — | If there is no new data by 15:30, the day is treated as a holiday or outage and a short "no data" notice is sent. |
| ~15:05 | Validate, then store, adjust, run strategies |
| ~15:10 | Telegram + email summary sent |

### Summary format (Telegram)
```
📊 DSE Screener — Wed 30 Sep 2026 (DS30)
DSEX 5,xxx (+0.4%) · Turnover ৳xxx cr

🟢 Quiet accumulation (3)
1. XYZ  82  Vol 20/60d 2.1× · price range 7% · trade size +34%
2. ...
🚀 Base breakout (1)
1. ABC  74  Broke 40d range on 2.6× volume
⭐ Confluence: XYZ (accumulation + big hands)

Dashboard: http://localhost:8501
Screening output from your own rules. Not investment advice.
```

## 7. Backtest-lite
For each strategy, over the stored history: every date it fired → forward returns at 5/20/60 days,
compared with DSEX over the same period. Reported as hit rate, median return, worst drawdown and
signal count. Floor-price periods are excluded. Tuning uses early data, and results are checked on later data.

## 8. Milestones

| # | Milestone | Deliverable | Done when |
|---|---|---|---|
| M0 | Project setup | Repo, venv, config loading, logging, DS30 list | `python -m app --help` works |
| **M1** ✅ | **Data foundation** (highest risk, first) | DSE archive adapter, **2-year backfill**, daily ingest | Done 2026-09-30: 480 trading days, 312k rows, 30/30 DS30 codes |
| M2 ✅ | Fundamentals + corporate actions | Company page + news adapters, adjustment factors (§4.3), config-driven quality filter in both profiles | Done 2026-10-01: 30/30 profiles, 1,624 news items, 59 corporate actions verified against ex-date opens; 25/30 DS30 pass quality in both profiles |
| M3 ✅ | Strategy engine | Plugin interface, 3 strategies, quality filter, ranking (confluence, boosts, record-date penalty), reasons, runs saved to DB | Done 2026-10-01: `screen` gives a ranked, explained list for any date; no-lookahead verified by test |
| M4 🔄 | Delivery | `daily` job (wait → retry → refresh news → screen → send), Telegram with recent news per pick, Task Scheduler script. Email deferred. | Built 2026-10-01; done when the summary arrives by 15:15 on 5 trading days in a row |
| M5 ✅ | Dashboard | **Next.js 16** (`web/`) over a FastAPI JSON API (`api` command), both localhost-only: Picks, Stocks, Stock page (candles + signal markers + ex-dates, volume, RSI, MACD), History, Quality, Backtest, Settings. Replaced the first Streamlit version. | Built 2026-10-01. "≤ 15 min review" to be confirmed by you |
| M6 🔄 | Backtest + tuning | `backtest` / `tune` commands and Backtest page: next-day entry, 1% costs, quality-basket benchmark, non-overlapping trades, in/out-of-sample split; verified identical to the live screen on 6 real dates | Built 2026-10-01; 2026-10-02 added profit factor, exit styles, recall and `casestudy` (docs/05 W1/W2). Position meets the return criteria in both periods; swing only in 2026 |

## 9. Decisions log

| Date | Decision |
|---|---|
| 2026-09-30 | **Two profiles**: `swing` (2–6 week holds) and `position` (3–12 month holds), with separate windows and thresholds, both running daily. The summary shows each profile's picks. |
| 2026-09-30 | **Quality seed**: GP, BATBC, SQURPHARMA, LHB, BSC (`config/universes/quality_seed.yaml`). M2 derives filter rules from what they have in common. |
| 2026-09-30 | **Hosting**: this Windows PC for now, so it must be on at ~3pm Sun–Thu. Nothing is Windows-only apart from the scheduler, so moving to a server later is simple. |
| 2026-09-30 | **PDFs**: broker research reports are what matter. They're Phase 2 (extract target price, rating and key points per stock with an AI model). |
| 2026-09-30 | DSE's old host serves an incomplete TLS chain, so verification goes through the OS trust store (`truststore`) and stays on. |
| 2026-10-01 | Price history is adjusted for **cash dividends too**, matching DSE's own reference-price reset (configurable). |
| 2026-10-01 | Quality rules derived from the seed: all 5 seed stocks pass both profiles. EPS growth is *not* a hard rule (BATBC −31%/yr would fail), so it becomes a ranking factor in M3. |
| 2026-10-01 | Holding rule uses **sponsor + government** (`strategic_pct`), so state-owned companies like BSC and the oil companies aren't excluded for showing 0% sponsor. |
| 2026-10-01 | `strategic_pct` lowered to **25** (keeps EBL); **insurers excluded** (`sector: not_in [Insurance]`). 26/30 DS30 pass. |
| 2026-10-01 | Strategies compute every date at once with backward-only windows, so today's screen and the backtest share one code path. |
| 2026-10-01 | **Big hands is `role: confirm`**. Alone over 2 years it was no better than a random day (swing) and worse (position, 35% positive at 60d), so it only adds confluence. |
| 2026-10-01 | **Second breakout on in swing, off in position.** Swing (71 stocks, 20d): 60 signals, median +3.6% vs −0.1% for first breakouts, better in 2025 and 2026; shortlist mean +1.0% → +1.3%. Position at 60d was mixed (n=20). It is **exempt from the MACD filter** (`filters.technical.exempt`): second breakouts failing the 10-day-cross rule did far better in both years. |
| 2026-10-01 | **Record-date penalty**: swing −20 (near-record signals did worse), position 0, note only (they did better, n=18). |
| 2026-10-01 | Quiet accumulation allows at most a **−2%** price dip (was −5%); a bigger dip on high volume may be selling. |
| 2026-10-01 | **Telegram only** for now; email later (the `notify/` package takes more channels). Summary shows swing first. |
| 2026-10-01 | Dashboard charts: price and volume in **two stacked panels** (no dual axis); strategies keep fixed colors and marker shapes; dark mode uses its own palette steps. Bound to `127.0.0.1` only. |
| 2026-10-01 | DSE's archive has **no rows for today during trading**, only after the close, so "data complete" = the day's rows exist. The job waits until 14:45, retries every 5 min, gives up at 16:30 with a "holiday or outage?" notice. |

### Early evidence (2 years, DS30, *not* the M6 backtest)
Median forward return after a signal vs any day. Caveats: small samples, one market phase, today's quality filter applied to the past.

| Profile | Strategy | Signals | Median return | % positive | Any day |
|---|---|---|---|---|---|
| swing (20d) | quiet accumulation | 146 | +1.6% | 63% | +0.0% / 50% |
| swing (20d) | base breakout | 152 | +2.6% | 63% | |
| position (60d) | quiet accumulation | 51 | +0.4% | 53% | +2.3% / 60% |
| position (60d) | base breakout | 69 | −0.7% | 42% | |

**Superseded by the M6 backtest (realistic: next-day entry, 1% costs, same-day quality basket as benchmark):**
swing picks returned a median +0.7% over 20 days vs +1.4% for the basket, beating it in 43% of 140 trades. A grid of
24 quiet-accumulation settings found nothing that beats the basket on the tuning period *and* holds on 2026. The
pattern alone shows no edge in DS30 over these two years. Next ideas to test: market-relative volume (built, off by
default), RSI/MACD filters, and a wider universe than DS30 (where volume anomalies may matter more).

| 2026-10-01 | **Universe = all active DSE equities** (`all_equities`, resolved from company pages; 322 today: 158 A, 74 B, 126 Z). Default **Category A** + liquidity (60-day avg value ≥ BDT 3 mn swing / 5 mn position, traded ≥ 90% of days) instead of a market-cap floor. 71 pass swing, 53 position. The daily job discovers new listings, refreshes the 60 stalest company pages, and refreshes news only for quality-passing stocks. |
| 2026-10-01 | **Technical filter**: swing requires a bullish MACD cross within 10 trading days (only rule that helped both periods); position has no technical filter (differences were noise). Every pick shows an RSI/MACD line. |
| 2026-10-01 | Dashboard moved to **Next.js + FastAPI** to grow into a platform; RSI(14) and MACD(12,26,9) added (`indicators.py`) and charted; not yet used by strategies. |

### Technical filter results (2026-10-01)

Each rule was applied on the signal day, then backtested (next-day entry, 1% cost, vs the same-day quality basket).
Median return vs basket, tuning period (2025) → test period (2026). Baseline swing: −1.3 → +0.3; position: −0.2 → +0.1.

| Profile | Rule | 2025 | 2026 | Verdict |
|---|---|---|---|---|
| swing | RSI ≤ 50 / 60 / 70 | −0.6 / −0.8 / −1.0 | −1.4 / −0.2 / −0.1 | Better in 2025, worse in 2026: noise |
| swing | RSI ≥ 40 / 50 | −1.5 / −1.5 | +0.3 / +0.3 | No effect |
| swing | MACD histogram > 0 | −1.8 | +1.0 | Periods disagree |
| swing | MACD histogram rising | −1.1 | +0.4 | Small, inconsistent |
| swing | **Bullish MACD cross ≤ 10 days** | **−0.5** | **+1.4** | **Better in both: enabled** |
| swing | Bullish MACD cross ≤ 3 days | −1.7 | +2.6 | Periods disagree |
| position | any RSI/MACD rule | −2.2 … +0.2 | −2.0 … +4.2 | 3–31 trades per cell: noise, kept off |

Swing with the cross ≤ 10 rule, 20-day hold: 91 trades, median **+0.3** vs basket (was −0.6), beat rate **52%** (was 43%).
About 20 variants were tried, so some luck is likely in the winner. Re-check this as history grows.

### Technical filter re-check on the 71-stock universe (2026-10-01)

The rule above was chosen when the universe was DS30 only. Re-run on today's universe (all A-category equities with
liquidity + quality rules, 71 pass swing) with the shortlist backtest, `second_breakout` exempt unless noted.
20-day hold, entry next open, net of 1%. Tuning period (2024-09-30 … 2025-12-31) → test (2026):

| Variant | Trades | Median % | Mean % | Win % | Mean vs basket | Profit factor |
|---|---|---|---|---|---|---|
| **Current: cross ≤ 10** | 117 → 133 | −1.6 → **+1.3** | +0.3 → **+2.1** | 41.9 → **58.6** | −0.1 → **+1.3** | 1.09 → **2.07** |
| Filter off | 173 → 144 | **−1.3** → +1.0 | **+0.9** → +1.7 | **44.5** → 56.3 | −0.3 → +0.5 | **1.35** → 1.78 |
| Cross ≤ 15 | 135 → 141 | −1.5 → +1.3 | +0.8 → +2.0 | 43.7 → 58.2 | −0.1 → +1.0 | 1.28 → 1.98 |
| Cross ≤ 20 | 150 → 143 | −1.0 → +1.2 | +1.4 → +1.8 | 46.0 → 56.6 | −0.1 → +0.8 | 1.51 → 1.81 |
| ≤ 10, base breakout also exempt | 155 → 148 | −1.0 → +1.1 | +1.6 → +1.6 | 45.2 → 55.4 | −0.1 → +0.7 | 1.57 → 1.73 |
| ≤ 10, quiet accumulation also exempt | 158 → 141 | −0.9 → +1.3 | +0.4 → +2.1 | 44.9 → 58.2 | −0.4 → +1.0 | 1.13 → 2.05 |
| Cross ≤ 5 | 89 → 107 | −2.7 → +2.3 | −0.6 → +1.7 | 37.1 → 59.8 | −1.0 → +0.6 | 0.83 → 1.80 |

Also tried, none better than current in 2026: ≤ 5 / 15 / 20 with base breakout or quiet accumulation exempt.

- **Kept, unchanged**: no variant beats the current rule in both periods.
- **But it is no longer "better in both"**: in the tuning period the filter now *hurts* (worse median, mean, win rate
  and profit factor than no filter); its support comes from 2026 alone. If it were proposed today it would fail
  against "off". It stays only because the incumbent wins ties under the rule.
- Bootstrap standard error of each median is 0.6–1.1 points, so most gaps above are noise.
- 2026 has now been looked at several times and is no longer an untouched test. Re-check when more history exists;
  "off" and "cross ≤ 15" are the alternatives to watch.

## 10. Open questions

1. **Notifications**: create a Telegram bot via @BotFather (2 min) and choose which email account to send from (needed for M4).
2. **"Never touch" examples**: 3–5 stocks you'd avoid, to sharpen the quality and red-flag filters (optional).
3. **Shareholding history**: the company page shows only the last ~3 months. Refreshing fundamentals monthly builds a
   history in our DB; deeper history would need another source (amarstock/lankabd).
