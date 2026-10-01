# Trend Template + VCP: review of the Pine script and upgrade plan

_Status: Draft v0.1 · 2026-10-01_

## 1. What the script does

The script adapts **Mark Minervini's Trend Template** (stage-2 uptrend checklist) and **VCP**
(Volatility Contraction Pattern) to DSE:

- **Trend criteria c1–c7:**
  - price above the 50- and 100-day MAs;
  - 50-day above 100-day;
  - 100-day rising versus 15 days ago;
  - 20-day above both;
  - price above the 20-day;
  - at least 20% above the 6-month low, and within 30% of the 6-month high.
- **c8:** a volume spike today (> 1.2× the 20-day average) **and** a 3-month gain > 15%.
- **c9:** 20-day volatility < 8%.
- **c10/c11:** a "basic" and an "enhanced" VCP detector, plus a 0–100 breakout score.
- **Buy** = c1…c8 all true. **Exit** = any of them fails while price was above the MAs yesterday.
- **Total score** = number of the 11 checks that pass (STRONG ≥ 9).

It's a sound framework: trend following plus a contracting base is one of the better-documented
equity setups. The problems are in how this script measures it.

## 2. Audit on real DSE data

The script's logic was ported faithfully to Python (Pine conventions, e.g. population stdev) and run on
the 30 DS30 stocks, 2024-10 → 2026-10, adjusted for dividends and bonus shares. That's 10,523 stock-days
after a 130-day warm-up. Returns are measured from the next day's open, net of a 1% round trip, and compared
with the same-day quality basket, as in the StockEYE backtest.

| Finding | Number |
|---|---|
| c7 "within 30% of 6M high" is true on | **97.9%** of days, so it filters almost nothing |
| c9 "volatility < 8%" is true on | **98.5%** of days, so it filters almost nothing |
| c8 (needs a volume spike *today*) is true on | 5.3% of days: the bottleneck for every Buy |
| Buy runs that last **one day only** | **51%** (median run: 1 day) |
| An Exit triangle appears within 1 day of a Buy | **51%** of Buys; Exit shows on 43% of all days |
| Buy (first day) → after 20 / 60 days, vs basket | +0.1 / +0.6 pts, beats it 51% / 53%: a **coin flip** (n = 181 / 154) |
| Basic VCP | 27 signals in 2 years; after 20 days −1.7 vs basket |
| Enhanced VCP | 61 signals; +0.5 vs basket at 20 days, −1.6 at 60 days |
| **Random walk with constant volatility** (no real contraction exists) | Enhanced contraction test fires on **3.0%** of days; **0.0%** when measured correctly |

Caveats: DS30 only, 2 years, entries not de-overlapped. This is enough to find design flaws, not
enough to judge Minervini's method itself.

## 3. Critique

### 3.1 Design and logic

| # | Issue | Why it matters | Fix |
|---|---|---|---|
| 1 | **No relative strength.** Minervini's RS rank ≥ 70 is replaced by an absolute "3-month gain > 15%" (c8) | In a bull market everything passes; in a bear market nothing does. The point is to buy the *leaders* | RS percentile vs the universe (weighted 3- and 6-month returns), require ≥ 70 |
| 2 | **c8 mixes a one-day volume spike into the trend checklist** | A Buy exists only on spike days, so it switches on and off (51% last one day) | Volume belongs to the *breakout trigger*, not the trend state |
| 3 | **c7 and c9 are almost always true** (98%) | They add nothing but still count toward the score | Drop c9; tighten c7 to 25% (Minervini) or make it a score item |
| 4 | **The score double-counts.** c1, c2, c4, c5 are all MA alignment; c10, c11 are both VCP | "9/11 = STRONG" mostly measures one thing four times | Score by *pillars*: trend, RS, base/VCP, volume, each counted once |
| 5 | **Momentum vs stability conflict:** c8 wants a spike + 15% run, c9 wants calm | The criteria pull in opposite directions | Momentum before the base (prior uptrend), calm *inside* the base, volume at the breakout |
| 6 | **No breakout trigger.** VCP marks a setup, but Minervini buys the **pivot breakout** | Without a trigger, "Buy" appears in the middle of a base or after the move | Entry = close above the pivot (last contraction high) on ≥ 1.5× volume |

### 3.2 VCP measurement

| # | Issue | Why it matters | Fix |
|---|---|---|---|
| 7 | **Enhanced VCP compares stdev over windows of different lengths** (8, 16, 24, 32 days) | Longer windows of *prices* include more drift, so their stdev is naturally larger. That makes "contraction" appear by construction: 3.0% of days on pure random walks | Compare **equal-length** windows of **returns** or ATR%, or better, measure real pullbacks (#9) |
| 8 | Stdev of **price** (not returns) | A steady uptrend has a high price stdev with low volatility | Use ATR% (true range / close) or stdev of daily returns |
| 9 | **Fixed windows, not real contractions.** A VCP is a sequence of shrinking *pullbacks* (e.g. −22% → −11% → −5%) | Fixed 10-day blocks don't line up with the actual swing highs and lows | Detect swing highs/lows (zigzag with a % or ATR threshold) and measure each pullback's depth |
| 10 | **Volume rule is backwards.** VCP quality requires volume > 0.8× average | In a VCP, volume should **dry up** in the last contraction and **expand** at the breakout | Require 10-day volume ≤ ~0.7× the 50-day average in the final contraction; ≥ 1.5× on the breakout |
| 11 | Basic VCP needs volatility to **halve three times** (ratio < 0.5) | So strict it barely ever fires (27 times in 2 years across DS30) | Use the pullback-depth rule from #9 with a ratio of ~0.75 |
| 12 | Magic numbers (base range < 25/30/35, proximity 0.85, stability 8%) | Untested; easy to overfit | Fewer parameters, all in YAML, chosen by walk-forward testing |

### 3.3 Signal and exit mechanics

| # | Issue | Fix |
|---|---|---|
| 13 | Buy triangles print on **every** qualifying bar, not just the first | Mark only the first bar of a setup or breakout |
| 14 | **Exit = any criterion fails.** A normal-volume day after a spike day is an "exit" (51% within 1 day) | Separate exit rules: stop-loss, close below MA20/MA50, time stop |
| 15 | **No risk management**: no stop, sizing or target | Initial stop = max(last contraction low, entry −8%); size by risk per trade; trailing exit |

### 3.4 Missing context (especially on DSE)

| # | Issue | Fix |
|---|---|---|
| 16 | **No market regime filter.** Minervini only buys in a confirmed uptrend; DSE has long weak phases | Breadth (% of stocks above their 50-day MA) and an equal-weight index above its 100-day MA |
| 17 | **No liquidity / junk filter.** DSE small caps get pumped; the template triggers on pumps | StockEYE's quality filter, plus a minimum average traded value |
| 18 | **Bonus shares distort charts** if the data isn't adjusted (we found 13 fake crashes in DS30) | StockEYE adjusts for cash and stock dividends; worth checking which setting your TradingView uses |
| 19 | Record dates / spot trading produce dividend-driven volume | StockEYE's record-date handling |

### 3.5 Pine technical notes

- Several `ta.*` calls (stdev, sma, highest) run **inside `if` blocks and functions** called only on some
  bars. Pine warns that this can give inconsistent results; compute them at the top level on every bar.
- `var line` declared inside a conditional; levels only drawn on the last bar.
- About 20 inputs and no backtest (it's an `indicator`, not a `strategy`), so there's no evidence for any setting.

## 4. Upgraded design for StockEYE

Three parts that fit the existing engine (filters → strategies → ranking), all configurable in YAML:

### 4.1 Trend Template v2 (filter)
| Rule | Default |
|---|---|
| T1 Stacked trend: close > MA50 > MA100 | MA periods configurable (yours: 20/50/100) |
| T2 MA100 rising: MA100 > MA100 20 trading days ago | ≈ 1 month |
| T3 Off the lows: close ≥ 25% above the 130-day low | |
| T4 Near the highs: close within 25% of the 130-day high | |
| T5 **Relative strength** percentile vs universe ≥ 70 | 0.6 × 63-day + 0.4 × 126-day return |
| T6 Liquidity: 20-day average traded value ≥ BDT 5 mn | plus the existing quality filter |
| Regime gate: ≥ 40% of the universe above its MA50, and the equal-weight index > its MA100 | built from stored prices |

### 4.2 VCP setup (detector, measured properly)
1. **Base window:** 25–65 trading days, starting after a prior advance of ≥ 25%.
2. **Swing points:** zigzag with a reversal ≥ max(3%, 1.5 × ATR%).
3. **Contractions:** at least 2 (default 3) pullbacks, **each ≤ 0.75× the previous** one; first ≤ 35%, last ≤ 10%.
4. **Tightness:** ATR%(10) ≤ 0.6 × ATR%(50), comparing equal measures.
5. **Volume dry-up:** 10-day average volume ≤ 0.7 × 50-day in the final contraction.
6. **Pivot** = highest high of the final contraction.

### 4.3 VCP breakout (entry strategy)
- **Trigger:** close ≥ pivot × 1.005 and volume ≥ 1.5 × 50-day average, within 5 days of a valid setup, with T1–T6 and the regime gate true.
- **Score** (0–100, explained like today's picks): volume multiple, tightness, RS rank, depth of the last contraction.
- **Stop and exit:**
  - Initial stop = max(last contraction low, entry −8%).
  - Exit on a close below MA20 (swing) or MA50 (position), or a time stop: not +5% within 15 days.

### 4.4 How it fits
- A new profile **`trend.yaml`** (1–3 month holds), so results don't mix with swing/position.
- **Quiet accumulation** can be a *confirming* strategy here. Accumulation inside the base followed by a
  dry-up and a breakout is the classic sequence, and it ties your method to Minervini's.
- **Watchlist:** stocks in a valid VCP setup within 5% of their pivot ("near pivot"). A daily Telegram
  section, so you're ready before the breakout.
- **Dashboard:** MA20/50/100 overlays, 6-month high/low lines, the base shaded with the pivot line and
  contraction depths labeled (−18% / −9% / −4%), a breakout marker, and a **Trend Template checklist**
  panel on each stock page (your Pine table, with the pillar scores).
- **Telegram:** picks with **pivot, stop and risk %**, e.g. "Buy above 214.5 · stop 201 (−6.3%)".

### 4.5 Backtest upgrades this needs
- **Rule-based exits** (stop, trailing MA, time stop) in addition to fixed holding periods. Trend following
  makes its money in the tails, which fixed 20/60-day holds understate.
- Per-trade **R-multiple**, win rate, average win/loss, max drawdown, time in market; still compared with the basket.
- **Walk-forward** (rolling quarterly folds) and **ablation** (remove one rule at a time to see what it adds).
- **Parameter stability** maps instead of a single "best" setting.

### 4.6 Universe: the biggest lever
VCPs and breakouts are **rare** (27–61 in DS30 over 2 years), which is too few to judge. Prices for **all
~390 equities** are already in the database. Plan:
- Add an `all_equities` universe (exclude mutual funds, bonds and T-bills).
- Fetch company pages for all of them once (≈ 15 min), then weekly.
- Rely on the quality + liquidity filters.

That should multiply the sample roughly 10×.

## 5. Milestones

| # | Milestone | Done when |
|---|---|---|
| V1 | **Parity baseline**: your script exactly, as a StockEYE strategy | Signals match TradingView on 3–5 stocks you check; audit numbers reproduced in `backtest` |
| V2 | Indicators: MAs, ATR%, RS percentile, breadth/regime, zigzag swings | Unit tests incl. random-walk check (no false contractions) |
| V3 | Trend Template v2 filter + regime gate | Ablation table: what each rule adds |
| V4 | VCP setup + breakout strategy, `trend.yaml` profile | Tests on synthetic VCPs; backtest vs basket and vs V1 |
| V5 | Backtest: rule-based exits, R-multiples, walk-forward | Results on DS30 and all equities |
| V6 | All-equities universe (data + quality pages) | ≥ 300 stocks screened daily within the 3pm job |
| V7 | Dashboard + Telegram: overlays, base/pivot drawing, checklist panel, near-pivot watchlist | Visual check on 5 known setups |
| V8 | Go/no-go | Turn on only if it beats the basket over the test period with ≥ 100 trades and holds in most walk-forward folds |

## 6. Decisions needed from you

1. **MA periods:** keep 20/50/100 (fits 2 years of data), or 50/150/200 like Minervini (needs more warm-up)?
2. **Holding period and exits** for this strategy: trailing below MA20 (faster) or MA50 (slower)? Max stop 8%?
3. **Universe:** OK to expand to all liquid DSE equities for this profile?
4. **Parity check:** can you send TradingView values (the table) for 3–5 stocks on a given date, so V1
   can be verified to match your chart? Also: is your TradingView chart adjusted for dividends?
5. Do you use this script for **entries only**, or also its exit triangles?
