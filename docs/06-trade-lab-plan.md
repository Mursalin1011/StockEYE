# Trade lab: test your own entry/exit rules on any stock

_Status: v0.4 · 2026-10-02 · phases 1–3 done_

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
| **2** | `POST /api/simulate`, `/lab` web page (stock picker, entry/exit builders, chart with entry/exit markers, trade table, save plan), equal-weight basket benchmark (needs all prices; the API already caches them) | ✅ 2026-10-02 |
| **3** | Same plan over a list or universe; portfolio mode (shared capital, max open positions); parameter grid shown for tuning vs test period; liquidity check (position size vs traded value) | ✅ 2026-10-02 |

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

## 9. Phase 2 results (2026-10-02)

- **Dashboard → Trade lab** (`/lab`): stock chips, dates, a saved-plan picker (loads its rules, keeps your stocks
  and dates), Buy (strategy signal and/or conditions, or buy dates), Sell, Hold & money, **Save plan**
  (writes `config/plans/<name>.yaml`; asks before replacing). The plan travels in the URL (`?p=`), so a result is a
  shareable link; `?plan=NAME[&code=X]` runs a saved plan.
- Results: plan in words, stat tiles (trades, win rate, average, profit factor, plan vs buy & hold, vs basket),
  warnings and "signal now", per-stock table (plan / buy & hold / basket held / drawdowns / time in market), price
  chart with **B**uy / **S**ell markers (sell coloured by result) and the price-level columns the plan uses (e.g. MA20),
  equity chart (plan vs buy & hold, same money), trade list, summary by period / stock / exit reason.
- **Basket benchmark**: equal-weight basket of a profile's quality stocks (default `swing`, 71 stocks), bought and sold
  on each trade's days, so "vs basket" shows whether the rule beat the market on the same dates. Also in the CLI:
  `simulate ... --basket swing`.
- API: `GET /api/lab` (saved plans, columns, strategies, profiles), `POST /api/simulate`, `POST /api/plans`.
  First run ~4 s (loads all prices for the basket), then ~0.4 s (cached).
- Checks: API tests (same PTL 25 Feb 2026 entry as the case study, markers on chart days, readable errors, plan-name
  and overwrite rules); a basket unit test; the form driven in headless Edge (add stocks, add a condition, run, save,
  replace, load a plan).

## 10. Phase 3 results (2026-10-02)

- **Many stocks**: `universe: ds30` (or `all_equities`) adds every stock in a universe; `quality: swing` keeps only
  those passing that profile's quality filter today. Both warn about the bias they bring (today's list, today's
  fundamentals).
- **Shared capital** (`portfolio: {max_positions: 5}`): one pot, at most N positions, each equity / N (capped at the
  cash left). When more stocks signal than there are free slots, the highest `rank_by` goes first (default: the
  strategy's score, else `vol_x_20`); the rest are skipped and counted. Compared with the same money split equally
  over the stocks and held. Tested for no lookahead across stocks.
- **Liquidity**: every trade's stake vs the stock's 20-day average traded value (`liquidity.max_pct`, default 10%):
  bigger trades are flagged.
- **Parameter grid**: `--grid exit.stop_pct=5,8,12 --grid exit.trail_ma=10,20,50` (or the dashboard's grid
  section, up to 36 combinations): one row per combination with tuning / test trades, mean, win rate, profit factor,
  vs basket, return and drawdown; heat tables for two parameters; "Open" runs a combination in full. Any plan value
  works, including a condition's number (`entry.when.1.2`) or a strategy parameter (`entry.params.base_days`).
  Signals and columns are cached across combinations (9 combinations x 71 stocks: ~8 s).

### First finding: base breakouts as a 5-slot portfolio (swing quality stocks, Jan 2025 → Oct 2026)

| Setting | Tuning (2025) mean / PF | Test (2026) mean / PF | Portfolio | Stocks held |
|---|---|---|---|---|
| −8% stop, below MA20 (current) | +0.1% / 1.0 | −1.1% / 0.7 | **−8.5%** (DD −22%) | **+28.0%** (DD −14%) |
| best of 9 in tuning: −5% stop, MA20 | +1.0% / 1.3 | −1.1% / 0.7 | −0.7% | +28.0% |

All 9 stop × MA settings are flat in 2025 and lose in 2026; 290 signals were skipped for lack of slots. As a
standalone portfolio with these exits, base breakouts don't beat simply holding the quality stocks. The tuning
"winner" (−5% stop) is no better in the test period, which is the curve-fitting the grid is meant to expose.

## 11. Why the breakout portfolio loses to holding (2026-10-05)

Setup as in §10: base breakouts (swing settings) on the 71 swing quality stocks, Jan 2025 → Oct 2026, 5 slots,
−8% stop / below MA20 / 60 days, 1% round trip. Portfolio **−8.7%** vs **+26.3%** for the same money held across
the 71 stocks (the market was up in both years: 2025 +10.7%, 2026 +15.0%). Controls use random entry days on the
same stocks, the same number of entries per stock, the same exits (30–40 runs each).

**1. The exits do most of the damage.** The same 5-slot portfolio with *random* entries and these exits loses a median
**−22.7%** (5th–95th: −35% .. −4%) in a market up 26%; breakouts (−8.7%) beat 90% of those runs. The −8% stop and
MA20 exit churn: 85 round trips, median 14 days held, 29% winners.
- **Costs: 15.7% of starting capital** (85 × 1% of ~18,500 stakes). Before costs the trades made +7,047; after, −8,678.
  With zero costs the portfolio makes +7.8%, still well behind holding.
- **Cash drag:** on average 3.1 of 5 slots filled, so 62% invested vs 100% held.
- Trades sold below MA20 (266 of 289 signals): median −0.4% when sold, +1.6% if held 60 days from entry.

**2. The score picks the worst breakouts.** With more signals than slots, the portfolio takes the highest score first,
and the score ranks backwards with these exits:

| Score quartile | Mean | Win | vs basket |
|---|---|---|---|
| lowest (10–39) | +3.2% | 48% | +0.4 |
| low (39–53) | +3.3% | 51% | +0.2 |
| high (53–76) | +1.5% | 42% | +0.1 |
| highest (76–100) | +0.3% | 36% | −1.6 |

So the 74 signals the portfolio took averaged −0.6% (26% winners), while the 215 it skipped averaged +3.0% (51%).
The score's weight on breakout-day volume (50 of 100 points) and breakout size rewards extended, volatile breakouts that
pull back into the stop/MA20. The most consistent bad sign, under both exit styles: **entry ≥ ~4.3% above the base
high** (next open): 31% winners / −4.3% median with the current exits, 40% / −3.4% held 60 days, −1.5 vs basket in both.
The live shortlist ranks by this score too.

**3. Breakout entries have no measurable edge per trade.** Held a fixed 60 days (no stop), breakouts average **+4.5%**
vs **+4.0%** for random days (random 5th–95th: +2.7% .. +5.3%), and ≈ 0 vs the basket over the same dates. What they earn
is the market's rise. Breakouts in busy weeks (many stocks breaking out) do better (61% winners) but again ≈ 0 vs the basket:
that is the market, not the stock.

**4. "Hold 60 days" is not a fix yet.** The 5-slot portfolio held 60 days makes +42.8% (2025 +13.0%, 2026 +26.4%) and beats
95% of random-entry portfolios (median +15.3%). But nearby settings swing from −3.5% to +57.9% (hold 20–120 days × 3–10 slots,
12–145 trades each), and random-entry portfolios already lose ~11 points to holding (fewer, concentrated positions, costs,
cash). Too few trades to tell skill from luck.

**Takeaways (leads to test, not conclusions; 2 years, ~290 signals, today's quality list for both sides):**
- For these stocks, the −8% stop + MA20 exit costs far more than it saves; any exit change should be judged on the
  2026 test period at the shortlist level (backtest exits), not on this one portfolio.
- Don't chase: test a rule skipping breakouts whose next open is more than ~4% above the base high.
- Re-check the base breakout score (volume weight) before trusting it to rank the shortlist; at least don't use it to
  choose between simultaneous breakouts.
- Holding the quality stocks did +26%: in this window the quality filter (partly look-ahead) did more than the timing.

## 12. Follow-up: don't chase and the score fix (2026-10-05)

Tested as W9 (docs/05, with the tables): optional `base_breakout` settings `max_extension_pct` and re-weighted
score points, chosen on 2025 and checked on 2026 at three levels (every signal, the swing shortlist backtest, the
5-slot portfolio).
- **Don't chase (close ≤ 4% above the base)**: better in 2025, not in 2026; lower recall. Not adopted.
- **Score 0 / 30 / 0 / 70** (tight base + near the base, no volume points): ranks breakouts the right way round in
  both years and improves the shortlist's 2025 numbers; in 2026 a trade-off (higher median / PF / win rate, lower
  mean excess, slightly lower recall). Not adopted yet; the candidate to re-test as data grows.
- Neither fixes the portfolio's real problem from §11: the −8% stop + MA20 exit churn and its costs.


## 13. Moving-average crosses: 10/20 and 20/50 in an uptrend, with volume support (2026-10-06)

Plans: `golden-cross` (20/50) and `ma-cross-fast` (10/20) in `config/plans/`. Jan 2025 → Oct 2026, next-open fills,
1% round trip, 2-day settlement; 2025 = tuning, 2026 = test. Two universes: the 71 swing quality stocks and DS30.

| Version | Buy when |
|---|---|
| A | MA10 crosses above MA20 |
| B | A + uptrend (MA20 > MA50, close > MA50) |
| C | B + volume support (10-day average volume > 50-day) |
| C2 | B + volume spike on the cross day (volume ≥ 1.5× its 20-day average) |
| D | MA20 crosses above MA50 (golden cross) |
| E | D + close > MA50 + volume support |

**Every signal, fixed 20-day hold** (mean net %, PF, mean vs the basket on the same dates; 2025 / 2026):

| | 71 swing: mean | PF 25 / 26 | vs basket 25 / 26 | DS30: mean | PF 25 / 26 | vs basket 25 / 26 |
|---|---|---|---|---|---|---|
| A 10/20 | +0.5 (613) | 1.0 / 1.7 | −0.1 / +0.2 | +0.7 (238) | 0.8 / 3.6 | +0.1 / +0.5 |
| B + uptrend | −0.2 (241) | 0.7 / 1.3 | +0.2 / +0.1 | +0.5 (77) | 0.2 / 4.3 | +0.8 / +1.7 |
| C + volume | +0.9 (112) | 0.9 / 2.5 | +0.3 / +1.1 | +1.1 (29) | 0.1 / 9.0 | −0.6 / +2.6 |
| C2 + spike | −0.8 (107) | 0.6 / 1.0 | −0.3 / −1.8 | −0.3 (25) | 0.1 / 6.8 | +0.1 / −0.4 |
| **D 20/50** | **+3.5 (279)** | **2.7 / 3.6** | **+0.5 / +1.1** | +3.6 (118) | 2.6 / 7.0 | +0.7 / +0.3 |
| **E + volume** | +3.6 (179) | 2.5 / 2.7 | +0.3 / +1.1 | **+4.7 (65)** | **3.4 / 5.7** | **+2.2 / +1.1** |
| base breakout (swing) | +1.9 (301) | 2.0 / 1.4 | −0.2 / +0.6 | +2.4 (113) | 1.9 / 2.4 | −0.2 / +1.0 |

- **10/20 crosses have no edge.** About the basket in both universes; with their own exit (MA10 < MA20) 35% of trades
  end within 10 days, 66% lose, and 724 round trips in 21 months on 71 stocks. Volume support (C) helps a little (+0.7
  vs basket) but fails PF in 2025 and beats only 83–90% of random entry days.
- **20/50 golden crosses pass the per-signal bar** (mean vs basket > 0 and PF ≥ 1.5 in both years, docs/05 §4) on both
  universes: the first MA rule here to do so, and better than base breakouts on the same harness. Most of the raw
  return is the market (crosses cluster in rallies); the edge is +0.5 to +2 points per 20-day trade. At 60 days, E beats
  83–87% of random-entry runs (not 95%).
- **Volume:** a sustained rise (10-day > 50-day) helps on DS30 (+0.7 → +1.6 vs basket) and the 10/20 cross; a one-day
  spike hurts everywhere (as with base breakouts, §11).
- **Exits:** the reverse cross (MA20 < MA50) gives the edge back on the 71 stocks (−0.4 / −0.9 vs basket, median −0.3%,
  held ~53 days). Fixed 20–60-day holds work better. The −8% stop + MA20 exit is worse again.
- **Late:** golden crosses come a median 30 days after a big move starts, with the price ~9% above its 20-day low.
  Recall on big winners (≥ +50% in 120 days, 39 moves): D 85% at 8.5 signals per catch, E 56% at 8.3, base breakout
  69% at 11.2. None meets ≤ 3 signals per catch.
- **Portfolio (shared capital):** sensitive to slots and ranking (3/5/10 slots × rank by vol_x_20 / lowest ret_20).
  71 stocks: no MA version reliably beats holding them (+26.3%); E with the reverse-cross exit loses in all 6 settings.
  DS30: E beats holding (+19.0%) in 15 of 18 settings (median +44% with 20-day holds, ~65 trades). Few trades; treat as a lead.
- Caveats: ~21 months; today's quality list and today's DS30 (look-ahead, survivorship).

**Verdict:** drop the 10/20 cross as a buy signal. The 20/50 golden cross with volume support and a fixed ~20-day hold is
the candidate: a confirming strategy for the shortlist or a DS30 timing rule, re-checked as data grows. Built as the
`ma_cross` strategy (off by default); shortlist backtest results in docs/05, W10.
