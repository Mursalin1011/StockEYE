# Trade lab: test your own entry/exit rules on any stock

_Status: v0.2 · 2026-10-02 · phase 1 done_

## 1. Why

The two tools we have answer other questions:

- `backtest` runs a profile's strategies across the whole universe: "does the shortlist work?"
- `casestudy` shows what the built-in strategies did on one stock, with the profile's fixed exits.

Neither lets you say "on PTL, from Jan 2025, buy when X, sell when Y, and show me every trade".
The trade lab does: you write the rules as a **trade plan**, pick the scrip(s) and dates, and get
the trade list, stats and an equity curve against buy-and-hold.

## 2. Decisions (2026-10-02)

| Question | Choice |
|---|---|
| Rule format | Structured conditions `[left, op, right]` (YAML / form dropdowns), not free-text formulas: easy to validate, nothing is `eval`'d |
| Positions | One at a time per stock (no pyramiding) |
| Results | % per trade **and** money: starting capital, position size, equity curve, drawdown |
| Order | Engine + CLI first, then API + web page |

## 3. The trade plan

Saved as YAML in `config/plans/<name>.yaml` (or built from CLI flags):

```yaml
name: ma-pullback
codes: [PTL]              # one or more scrips (each simulated on its own)
from: 2025-01-01
to: 2026-10-01

entry:                    # signal on day t's close; at least one of strategy / when / dates
  strategy: base_breakout   # an existing strategy's signal...
  profile: swing            # ...with this profile's parameters (optional)
  params: {}                # ...and these overrides (optional)
  when: ["close > sma_50", "rsi_14 < 40"]   # all must be true (with strategy: AND); [close, ">", sma_50] also works
  # dates: [2025-03-12]     # instead: the days you buy on
  fill: next_open           # or same_close
  new_signal_only: true     # only the first day a setup appears (no re-buying the same setup)

exit:                     # first one to trigger wins
  stop_pct: 8             # intraday low; a gap down fills at the open
  target_pct: 25          # intraday high; a gap up fills at the open; stop wins if both hit the same day
  trail_pct: 12           # close this far below the highest close since entry
  trail_ma: 20            # close below MA20
  when_any: ["rsi_14 > 75"]
  max_days: 60            # trading days after the signal day (as in the backtest)

hold:
  min_days: 2             # settlement: no exit before entry day + 2 trading days
  cooldown_days: 5        # trading days to wait after an exit

costs: { round_trip_pct: 1.0 }
capital: { start: 100000, per_trade_pct: 100 }
in_sample_until: 2025-12-31   # optional: split the stats into tuning / test periods
```

Operators: `>`, `<`, `>=`, `<=`, `crosses_above`, `crosses_below`. The right side is a number or a column.

**Columns** (any N): `open high low close volume value_mn change_pct`, `sma_N ema_N rsi_N atr_N`,
`high_N low_N` (highest/lowest close of the **previous** N days, so `close > high_20` is a breakout),
`vol_x_N` (volume ÷ average of the previous N days), `avg_vol_N`, `ret_N` (% change over N days),
`pct_from_high_N`, `macd macd_signal macd_hist macd_hist_change days_since_macd_cross`.
All backward-looking, computed on the full history so they're warmed up at the window start.

## 4. How a trade is simulated

Per stock, day by day: flat → in a position → flat.

- **Entry:** signal on day t (stock must have traded) → buy at t+1's open (its close if no open), or at
  t's close with `same_close`. Explicit `dates` are buy days: that day's open (`next_open`) or close.
- **Exits**, checked in this order on each day from `entry + min_days` (stop/target/trail only on days
  the stock traded): stop, target, trailing %, trailing MA, `when_any`, time limit. If the data ends
  first, the trade is marked at the last close as "open".
- **Prices:** signals use bonus/rights-adjusted prices; the trade list also shows the actual traded
  prices of the day.
- **Flags:** entry day locked at the upper limit (high = low, up), exit day locked at the lower limit
  (fill unlikely), entry on a day with no trades.

## 5. Results

- **Trades:** signal date, entry/exit date and price (adjusted and actual), exit reason, days, net %,
  best/worst point during the trade (MFE/MAE), flags.
- **Stats:** trades, win rate, mean/median, average win/loss, profit factor, best/worst, median days;
  all / per stock / tuning / test periods.
- **Per stock:** buy-and-hold over the same window (net of one round trip), plan return compounded,
  max drawdown, time in the market.
- **Warnings:** under 10 trades; a strategy entry whose profile was tuned on part of the window;
  trades still open; flagged fills.

## 6. Phases

| # | What | Status |
|---|---|---|
| **1** | Plan model, column library, simulation engine (strategy / condition / date entries, every exit type), stats, CLI `simulate`, example plans, tests | ✅ 2026-10-02 |
| **2** | `POST /api/simulate`, `/lab` web page (stock picker, entry/exit builders, chart with entry/exit markers, trade table, save plan), equal-weight basket benchmark (needs all prices; the API already caches them) | |
| **3** | Same plan over a list or universe; portfolio mode (shared capital, max open positions); parameter grid shown for tuning vs test period; liquidity check (position size vs traded value) | |

## 7. Caveats

- ~2 years of data: one stock gives few trades. Treat anything under ~10 trades as an anecdote.
- Rules you tune by looking at a chart are in-sample by definition; keep `in_sample_until` and judge on the later period.
- Fills at the open assume you get the open price; DSE opens can be thin.

## 8. Phase 1 results (2026-10-02)

- `python -m dse_screener simulate CODE... [--plan NAME] [flags]`; plans in `config/plans/`
  (`breakout-swing`, `ma-pullback`). `simulate --help` lists every column.
- Engine: `src/dse_screener/simulate.py`; columns: `src/dse_screener/features.py`; plan model: `TradePlan` in `config.py`.
- Checks (`tests/test_simulate.py`): it reproduces `backtest.simulate_exit` exactly for stop + trailing MA +
  time limit; truncating the data at the window end gives the same trades (no lookahead); gap fills, stop-before-target,
  settlement delay, cooldown, one position at a time, date roll-forward, actual vs adjusted prices, equity maths.
- No entry signal → it says how many days each part of the rule held (e.g. `close > sma_50 on 298, rsi_14 < 40 on 47`),
  so you can see which part is too strict.
- Example: PTL, 13 Nov 2025 buy with a −10% stop: the low hit −15% the next day, but the shares weren't sellable yet
  (`min_days: 2`); the stop couldn't fire, and the trade left two days later on the MA rule at −2.7%. Use `--min-days 0`
  to ignore settlement.
