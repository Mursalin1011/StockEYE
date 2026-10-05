# Catching moves like PTL: case study, market-wide evidence, upgrade plan

_Status: Draft v0.1 · 2026-10-01_

## 1. PTL (Paramount Textile), Nov 2025 → Oct 2026

Low 41.3 (13 Nov 2025) → high 85.7 (30 Sep 2026): **+107%**. From the Dec–Feb base (~50): **+60%**.

| Phase | Data |
|---|---|
| Dec → mid Feb: base | Price 49–51, 30-day range ~6%, **volume below normal** (0.7–0.9× its prior average) |
| 24–26 Feb: first breakout (your circle) | **4.6× volume**, RSI 76 |
| March: shakeout | Pulled back to 50.9 (−5% from the breakout), volume back to normal |
| 12–23 Apr: second breakout | **8× volume**, then a 6-month trend to 85.7 |

PTL is Category A, with 13 years of unbroken dividends, EPS +11.5% a year, 61% sponsor holding and
**institutions +2.4 pts**. It **passes the quality filter** in both profiles.

### What each strategy did (entry = next day's open; "now" = 81.9 on 1 Oct 2026)

| Signal | First fired | Entry | To now | Notes |
|---|---|---|---|---|
| **StockEYE swing: base breakout** | **25 Feb** | 53.7 | **+52.5%** | **Shortlist #1, score 82** (if PTL had been in the universe) |
| StockEYE position: base breakout | 25 Feb, again **12 Apr** | 55.9 / 59.4 | +46.5% / +37.9% | Shortlisted both times (66, 70) |
| StockEYE swing: quiet accumulation | 1 Apr | 55.0 | +48.9% | Missed Feb: the breakout widened the 30-day range to 13.4% (limit 12%) |
| StockEYE position: quiet accumulation | never | | | |
| Pine Trend Template "Buy" | 12 Apr | 59.4 | +37.9% | Then flickered on and off 13 times |
| Pine enhanced VCP | 18 Jan | 50.6 | +61.9% | Early, but the detector is biased (doc 04) |
| Pocket pivot (MA10/50) | 19 Jan | 52.4 | +56.3% | Earliest, but fired 16 times |
| MA cross 20 > 50 | 15 Dec, 25 Feb | 52.4 / 55.9 | +56% / +47% | |

Lessons from PTL:
1. **It was never scanned.** StockEYE only screens DS30. This is the main miss.
2. **The base breakout logic worked**: it flagged your exact circled breakout as the #1 pick.
3. **An RSI ≤ 70 filter would have blocked it** (RSI 76 at the breakout), consistent with the backtest that rejected it.
4. **The first breakout was a shakeout.** A −8% stop exits within 3–6 days at −6% to −9%. The real move
   started at the **second** breakout, so **re-entry** matters more than exits.
5. PTL was a **quiet base with volume drying up, then breakout volume** (VCP-like), not "volume rising
   while price is flat". Your method and the VCP sequence are related but different stages.

## 2. Market-wide evidence (all 374 equities, Oct 2024 → Oct 2026)

Price and volume only (fundamentals exist only for DS30 + PTL so far); liquid days only (60-day average value ≥ BDT 3 mn).
Prices outside DS30/PTL aren't yet adjusted for dividends and bonus shares, which adds some noise.

### Recall: how many big moves were caught (840 moves of ≥ +50% within 120 days, in 201 stocks)
| Strategy | Caught early* | Signals per catch |
|---|---|---|
| swing: base breakout | **29.5%** (median 20 days after the move starts) | 2.2 |
| swing: quiet accumulation | 15.8% | 2.2 |
| position: base breakout | 10.5% | 2.6 |
| position: quiet accumulation | 3.3% | 4.1 |
| **any strategy** | **36%** | |

\* Signal within 20 days before to 60 days after the move started, with entry ≤ 1.2× the starting price.

The biggest misses (DAFODILCOM +306%, DOMINAGE +237%, KPPL, SHARPIND, BDTHAIFOOD…) are mostly
speculative names that the quality filter is *meant* to avoid.

### Precision: same entries, different exits (per trade, net of 1%; basket = same dates)
| Strategy (all equities) | Exit | Win % | Avg win / loss | Median | **Mean vs basket** | Profit factor |
|---|---|---|---|---|---|---|
| position: base breakout | fixed 20 days | 48 | +11.4 / −7.1 | −0.6 | **+0.8** | 1.5 |
| position: base breakout | −8% stop + below MA20 | 36 | +14.0 / −5.6 | −2.8 | +0.9 | 1.4 |
| swing: base breakout | fixed 20 days | 44 | +9.9 / −7.8 | −1.3 | −0.2 | 1.0 |
| swing: quiet accumulation | fixed 20 days | 49 | +9.0 / −6.4 | −0.2 | +0.5 | 1.4 |
| swing: quiet accumulation | −8% stop + below MA50 | 31 | +13.9 / −4.3 | −2.3 | +0.9 | 1.4 |

On **DS30 quality stocks**, swing base breakout with a fixed 20-day hold had a **mean of +1.3 vs the basket**, 50% beat rate, PF 1.9 (72 trades).

What this says:
- Signals catch a fair share of big moves; **averages are slightly positive, medians negative**. The
  returns come from a minority of big winners. StockEYE's backtest headline (median) understates this.
- **Trailing exits didn't help on their own.** DSE breakouts often shake out (like PTL in March), so tight
  trailing exits cut the eventual winners too.
- **Without the quality filter**, swing breakouts are no better than the basket. The quality filter
  appears to be what makes them work, which is why the universe has to grow *with* fundamentals.

## 3. Upgrade plan

| # | Upgrade | Why (evidence) | How we'll know it works |
|---|---|---|---|
| **W1** ✅ | **Case-study tool**: `python -m dse_screener casestudy PTL --from 2025-11-01`, plus a dashboard page. Any stock you spot → timeline of every signal on the chart, entries, outcomes | Lets you test stocks like PTL yourself in seconds | Reproduces this document's PTL table |
| **W2** ✅ | **Backtest metrics**: mean, profit factor, avg win/loss, recall on big winners; exit modes (fixed / stop + trailing MA / time stop) | Median-only reporting hides positive-skew strategies | Summary shows both views; this doc's numbers reproduced |
| **W3** | **All-equities universe** with fundamentals for every company (one-time ~25 min, then weekly) and instrument type from DSE (not name rules); dividend/bonus adjustment for all | PTL-type misses; quality matters most outside DS30 | Daily screen of ~300 quality-passing equities within the 3pm job |
| **W4** ✅ | **Re-entry after a shakeout**: if a breakout fails (stop or close back in the base) but the stock **re-breaks the base high on ≥ 2× volume within 40 days**, signal again with a "second breakout" reason | PTL's real move started at the second breakout | Backtest: more winners captured per false alarm |
| **W5** ✅ (tested, not adopted) | **Base breakout v2**: optional **volume dry-up** in the base (10-day vol ≤ 0.8× 50-day before the breakout), longer bases (40–90 days), and a "follow-through" option (close above the pivot on 2 of the next 3 days) | PTL's base had volume drying up; filters weak breakouts | Precision up without losing recall |
| **W6** ✅ (tested, not adopted) | **Quiet accumulation v2**: measure the price range on the base *before* the last 5 days, so a breakout doesn't disqualify an accumulation; "accumulation, then breakout" as a confluence | Missed PTL in Feb by 1.4% of range | Recall up on quality winners; precision stable |
| **W7** | **Pocket pivot** as a confirming strategy; **Trend Template v2 + RS rank** (doc 04) for trend-continuation entries | Pocket pivots were earliest but noisy; the trend template caught the Apr–Sep phase | Confirm-role tests; trend profile backtest |
| **W9** ✅ (tested, not adopted) | **Base breakout: don't chase + score fix** (docs/06 §11): optional `max_extension_pct` (no signal once the close is more than X% above the base high) and re-weighted score points, incl. a new "near the base" term | Trade lab: the score ranked breakouts backwards (top quartile +0.3% vs +3.2% bottom); entries far above the base did worst | Shortlist beats the current version in both periods |
| **W8** | **Holdings tracker**: mark "bought PTL @ 53.7" (dashboard or Telegram), then a daily line with P/L, stop, trailing MA, warnings, and re-entry alerts | Catching isn't enough; you need to manage the position | You get a "your positions" section in the 3pm message |

**Order:** W1 + W2 first (cheap, and they make everything else measurable), then W3 (the biggest lever),
then W4–W6 (each measured with W2 on the wider universe), then W7 and W8.

## 4. Acceptance criteria (on the all-equities, quality-passing universe)

- **Recall on quality big winners** ≥ 40%, with ≤ 3 signals per catch.
- **Mean excess vs basket > 0** and **profit factor ≥ 1.5** in both the tuning (2025) and test (2026) periods.
- No change goes live without beating the current version on these numbers.

## 5. Decisions needed from you

1. **Expand to all liquid DSE equities** (with the quality filter) for daily screening? It adds ~25 min once, then a few minutes weekly.
2. **Holdings tracker:** would you mark your buys in the dashboard, or by Telegram message (e.g. `/bought PTL 53.7`)?
3. **Re-entry style:** alert on a second breakout automatically, or only for stocks you're watching?
4. Any **other winners** you remember, to add to the case-study set (the more examples, the better the tuning)?

## 6. Results

### W2: backtest metrics, exit styles and recall, 2026-10-02
`backtest` (CLI and dashboard) now reports mean, avg win / avg loss, **profit factor**, rule-based **exit styles**
(`backtest.exits`: stop on the low, trailing MA on the close, time limit; same entries as the fixed holds)
and **recall** on big winners (`backtest.winners`).

**Big-move counting changed.** Section 2 counted every day a +50% run-up was still ahead, so one run-up
with pullbacks counted many times (PTL: 6 "moves" in 2026). Now one run-up = one move (from its first day
to its peak). On the 71 swing-quality stocks that is **52 moves**, not 160, so signals per catch are
higher than in section 2 and not comparable.

Shortlist backtest, all-A universe (2024-09-30 → 2026-10-01, net of 1%):

| Profile | Exit | Trades | Mean | PF | Mean vs basket 2025 / 2026 | PF 2025 / 2026 |
|---|---|---|---|---|---|---|
| swing | fixed 20d | 250 | +1.3 | 1.5 | −0.1 / +1.3 | 1.1 / 2.1 |
| swing | −8% stop, below MA20 (max 60d) | 252 | +1.3 | 1.5 | +0.1 / +0.8 | 1.4 / 1.7 |
| swing | −8% stop, below MA50 (max 120d) | 251 | +0.5 | 1.2 | −0.7 / +0.7 | 1.0 / 1.3 |
| position | fixed 60d | 103 | +3.4 | 2.0 | **+2.3 / +1.7** | **2.3 / 1.7** |
| position | −10% stop, below MA50 (max 120d) | 105 | +1.8 | 1.6 | +1.8 / −0.0 | 2.5 / 1.1 |
| position | −15% stop, below MA100 (max 120d) | 98 | −0.1 | 1.0 | +1.3 / −0.9 | 1.6 / 0.5 |

Recall (moves of +50% within 120 days; caught 20 days before to 60 after the start at ≤ +20%):

| Profile | Moves | Shortlist recall | 2025 / 2026 | Signals per catch |
|---|---|---|---|---|
| swing | 52 | **46%** | 39% / 100% (6 moves) | 10.5 |
| position | 34 | 18% | 14% / 40% (5 moves) | 17.7 |

Against the acceptance criteria (section 4):
- **Position, fixed 60 days, meets the return criteria in both periods** (mean vs basket > 0, PF ≥ 1.5).
  Its recall (18%) is low: it buys fewer, slower moves.
- **Swing meets the recall target (46% ≥ 40%)** but not "≤ 3 signals per catch" (10.5 with the stricter move count;
  the target was set on the old count and should be revisited). Returns pass in 2026 only; 2025 fails (PF 1.1).
- **Exits:** stop + MA20 smooths swing's 2025 (PF 1.1 → 1.4) at no cost overall, but doesn't change the verdict.
  Slower trailing exits (MA50 / MA100) are worse for both profiles: DSE run-ups pull back hard. Fixed holds stay the default.
- 2026 has few complete big moves yet (6), so its recall is not meaningful.

### W9: base breakout don't-chase + score fix, 2026-10-05 (tested, not adopted)
New `base_breakout` options, off by default (signals and scores unchanged; the W5 regression test still passes):
`max_extension_pct` (signal only while the close is at most X% above the base high) and score points
`volume_points` / `tight_points` / `breakout_points` (default 50 / 30 / 20) plus `near_base_points` (default 0:
full points at the base high, none at `strong_breakout_pct` above it). Settings were **chosen on 2025 only**, then
checked on 2026. Swing quality stocks (71), net of 1%, vs bkt = mean excess over the same-day basket.

**Stage 1, every breakout signal (choose on 2025)**

| Variant | 2025 mean / PF / vs bkt | 2026 mean / PF / vs bkt |
|---|---|---|
| current exits (−8% stop, MA20), no limit | +3.6% / 2.5 / −0.2 | +0.7% / 1.2 / −0.3 |
| … close ≤ 4% above the base (**2025 pick**) | +4.2% / 3.0 / +0.4 | +0.6% / 1.2 / −0.4 |
| held 60 days, no limit | +7.3% / 3.2 / +0.8 | +1.6% / 1.5 / −0.4 |
| … close ≤ 4% above the base | +6.9% / 2.9 / +0.5 | +1.6% / 1.5 / −0.6 |

Score rank power on the same signals (rank correlation with the trade's return; current exits): current score
**−0.16** in 2025 / −0.05 in 2026 (higher-scored half 5.0 points *worse* in 2025). 2025 pick, **F = 0 / 30 / 0 / 70**
(tight base + near the base, no volume or breakout-size points): **+0.10** in 2025 / **+0.32** in 2026 (higher half
+0.8 / +2.8 points better). Held 60 days the picture is weaker (F +0.03 / +0.16; current −0.16 / +0.03). F keeps the
same share of signals above the shortlist's 40-point cut (72%).

**Stage 2, swing shortlist backtest (all strategies, ranking, top 10)**

| Variant | 20d mean 2025 / 2026 | 20d PF 2025 / 2026 | 20d vs bkt 2025 / 2026 | stop8_ma20 PF 2025 / 2026 | stop8_ma20 vs bkt 2025 / 2026 | Recall 2025 |
|---|---|---|---|---|---|---|
| **current** | +0.3% / +2.1% | 1.1 / 2.1 | **−0.1 / +1.3** | 1.4 / 1.7 | +0.1 / +0.9 | **39%** |
| score F | +0.8% / +2.0% | 1.3 / 2.1 | +0.5 / +0.8 | **1.6 / 1.9** | **+0.9 / +0.7** | 35% |
| close ≤ 4% | +0.7% / +2.0% | 1.3 / 2.0 | +0.4 / +0.6 | 1.5 / 1.8 | +0.5 / +0.5 | 37% |
| score F + close ≤ 4% | same as score F: under F, a close > ~4% above the base already scores below the 40 cut | | | | | |

Shortlist picks that include a base breakout (20d): current −0.0% / +1.7% (win 37% / 51%), score F +1.4% / +1.3%
(win 39% / 59%). 5-slot breakout portfolio (trade lab, current exits): current −8.7% (2025 −4.9%, 2026 −4.0%),
score F −3.3% (+5.2% / −8.1%), close ≤ 4% +4.8% (+7.0% / −2.1%); held: +26.3%.

What it says:
- **Don't chase** helps in 2025 and not in 2026 at every level except the 5-slot portfolio (one path, ~90 trades);
  it costs recall. Not a rule yet.
- **Score F fixes the ranking direction** (rank power positive in both years with the current exits) and is better
  than the current score on every 2025 shortlist number. In 2026 it is a trade-off: higher median, profit factor and
  win rate, but a lower mean excess over the basket (+1.3 → +0.8) and two fewer big moves caught in 2025 (39% → 35%).
- With the stop8_ma20 exit, score F is the only variant that meets the docs/05 bar (PF ≥ 1.5 and beats the basket)
  in both periods; at the 20-day hold none does.
- **Decision: no change for now** (it doesn't beat the current version on every number in both periods). F is the
  candidate to re-test as 2026 data grows: `backtest --profile swing --set strategies.base_breakout.params.volume_points=0 ...`.

### W6: quiet accumulation v2, 2026-10-02 (tested, not adopted)
New `quiet_accumulation` options, off by default: `range_exclude_days` (judge the price range on the base
before the last N days, so a late breakout doesn't cancel the signal) and `max_days_since` (keep the signal
on N days with a decaying score, so "accumulation, then breakout" earns the confluence bonus).

PTL: with the last 3–5 days excluded, quiet accumulation fires on **25 Feb 2026, the same day as the base
breakout** (missed before: range 13.4% > 12%). But the volume rise it sees that day is mostly the breakout's
own volume, so it partly re-labels the breakout rather than finding accumulation earlier.

| Profile, variant | Every signal: n | PF 2025 / 2026 | vs bkt 2025 / 2026 | QA recall | Shortlist vs bkt 2025 / 2026 | Shortlist PF 2025 / 2026 |
|---|---|---|---|---|---|---|
| **swing, current** | 202 | 0.6 / 2.3 | −1.3 / +1.1 | 29% | **−0.1 / +1.3** | 1.1 / 2.1 |
| swing, exclude last 3 days | 217 | 0.5 / 2.8 | −1.6 / +1.7 | 31% | −0.2 / +1.2 | 1.1 / 2.1 |
| swing, exclude last 5 days | 213 | 0.5 / 2.8 | −1.6 / +1.7 | 31% | −0.3 / +1.3 | 1.0 / 2.1 |
| swing, carry 5 days | 213 | 0.5 / 2.3 | −1.3 / +1.2 | 29% | −0.4 / +1.2 | 1.0 / 2.0 |
| swing, carry 10 days | 237 | 0.6 / 2.4 | −1.1 / +1.1 | 29% | −0.3 / +1.2 | 1.0 / 2.1 |
| **position, current** | 82 | 2.9 / 2.7 | +1.0 / +1.4 | 9% | **+2.3 / +1.7** | 2.3 / 1.7 |
| position, exclude last 5 days | 97 | 2.3 / 1.9 | +0.5 / +0.9 | 9% | +2.2 / +1.3 | 2.2 / 1.5 |
| position, exclude last 10 days | 98 | 2.5 / 1.7 | +0.1 / +0.7 | 9% | +0.7 / +1.3 | 1.7 / 1.6 |
| position, carry 10 days | 77 | 2.9 / 2.6 | +0.9 / +1.3 | 9% | +0.9 / +1.8 | 1.9 / 1.8 |

What it says:
- **Excluding the last days adds a handful of signals (one more big move caught for swing) and helps 2026,
  but hurts 2025**; on the shortlist it changes almost nothing, because the extra signals coincide with
  breakouts that were already picked. For position it is worse in both years.
- **Carrying the signal forward adds nothing**: the confluence bonus rarely changes which stocks make the cut.
- **Bigger finding: quiet accumulation on the swing horizon only worked in 2026** (2025: PF 0.6, −1.3 vs the
  basket; 2026: PF 2.3, +1.1). On the **position horizon it worked in both years** (PF 2.9 / 2.7, beats the
  basket by +1.0 / +1.4): the method needs months, not weeks, to pay off.
- **Decision: no change.** Options stay available for `backtest --set` experiments.

### W5: base breakout v2, 2026-10-02 (tested, not adopted)
New `base_breakout` options, all off by default (signals unchanged; a regression test checks this):
`max_dryup_ratio` (10-day volume before the breakout vs the 50 days before that), `follow_through_days` /
`follow_through_closes` (signal on the day the breakout is confirmed by closes above the base high), and
longer `base_days`. Quality stocks, 2 years, net of 1%, "vs bkt" = mean excess over the same-day quality basket.

**Swing (20-day hold)**

| Variant | Every signal: n | Hit % | PF | vs bkt 2025 / 2026 | Breakout recall | Shortlist vs bkt 2025 / 2026 | Shortlist PF 2025 / 2026 | Shortlist recall |
|---|---|---|---|---|---|---|---|---|
| **current (25d base, 10%)** | 249 | 46 | 1.3 | −0.3 / +1.6 | 38% | **−0.1 / +1.3** | 1.1 / 2.1 | **46%** |
| dry-up ≤ 0.8 | 79 | 54 | 1.9 | −0.5 / +1.3 | 19% | −0.2 / +0.7 | 1.1 / 2.3 | 40% |
| dry-up ≤ 0.6 | 40 | 48 | 1.4 | −1.5 / +0.6 | 15% | −0.3 / +0.4 | 1.0 / 2.2 | 37% |
| 40d base, 12% | 131 | 46 | 1.3 | −1.4 / +2.2 | 23% | −0.3 / +1.4 | 0.9 / 3.1 | 35% |
| 60d base, 15% | 92 | 41 | 1.1 | −1.3 / +1.0 | 12% | −0.2 / +0.8 | 1.0 / 2.3 | 31% |
| follow-through 2 of 3 | 186 | 45 | 1.1 | −0.3 / +0.8 | 31% | −0.4 / +0.9 | 0.9 / 2.2 | 40% |
| follow-through 1 of 2 | 217 | 46 | 1.3 | −0.2 / +1.8 | 35% | −0.3 / +1.6 | 1.0 / 2.3 | 44% |
| dry-up 0.8 + FT 2/3 | 61 | 57 | 2.1 | **+1.2 / +1.0** | 13% | −0.2 / +0.8 | 1.0 / 2.6 | 38% |

**Position (60-day hold)**

| Variant | Every signal: n | PF | vs bkt 2025 / 2026 | Shortlist vs bkt 2025 / 2026 | Shortlist PF 2025 / 2026 | Shortlist recall |
|---|---|---|---|---|---|---|
| **current (60d base, 15%)** | 147 | 1.6 | +2.2 / +0.9 | **+2.3 / +1.7** | 2.3 / 1.7 | 18% |
| dry-up ≤ 0.8 | 14 | 2.3 | +1.7 / −3.7 | +0.6 / +2.4 | 2.4 / 2.2 | 9% |
| 40d base, 12% | 203 | 1.7 | +1.3 / +0.9 | −0.2 / +1.3 | 1.7 / 1.5 | 29% |
| 90d base, 20% | 123 | 1.2 | −0.2 / +0.4 | +0.6 / +1.3 | 1.9 / 1.8 | 12% |
| follow-through 2 of 3 | 128 | 1.2 | +1.5 / +0.4 | +1.3 / +0.8 | 1.9 / 1.6 | 18% |

What it says:
- **Volume dry-up raises raw returns but not returns vs the basket** (swing: hit rate 46% → 54%, PF 1.3 → 1.9,
  but mean vs basket 0.8 → 0.5). Quiet-volume breakouts cluster when the whole market is about to rise: market
  timing, not stock picking. And it halves recall. PTL-style dry-up bases are real but rare.
- **Follow-through hurts on DSE**: waiting for confirmation enters later and higher, and failed breakouts are
  already handled better by `second_breakout` (re-entry after the shakeout).
- **Longer bases** help 2026 and hurt 2025 for swing; for position, 40-day bases nearly double recall but
  fail 2025 vs the basket.
- **dry-up + follow-through (swing)** is the only variant positive vs the basket in both years per signal
  (+1.2 / +1.0, PF 2.1, n = 61), but on the shortlist it does worse than the current setup. Worth re-testing
  as a separate "confirmed breakout" strategy once there is another year of data.
- **Decision: no change.** The options stay available (and tested) for experiments with `backtest --set`.

### W1: case-study tool, 2026-10-02
`python -m dse_screener casestudy PTL --from 2025-11-01 [--profile swing] [--shortlist] [--csv out.csv]` and the
dashboard **Case study** page (also linked from each stock page). For any stock, even one that fails the
quality filter: every signal run (incl. those blocked by the RSI/MACD filter), the stock's best score in the run
and the day it cleared the shortlist cut, outcomes for each holding period and exit style, best/worst within the
main hold, return to the last close, and the stock's big moves with which strategies caught them early.

It reproduces the PTL table in section 1 (returns there are gross; the tool shows them net of 1%):
swing base breakout 24 Feb → shortlisted 25 Feb at 82, entry 53.7, +51.5% net to 1 Oct; swing quiet accumulation
1 Apr, entry 55.0, +47.9%; position base breakout 25 Feb / 12 Apr, scores 66 / 70, entries 55.9 / 59.4.
With `--shortlist`, PTL ranks #4 on 25 Feb among the 71 stocks (it was #1 in the old DS30 + PTL universe).

### W4: re-entry after a shakeout (`second_breakout`), 2026-10-01
A base breakout that closes back below the old base high (without closing more than 5% under the base low),
then a close ≥ 1% above that breakout's highest close on ≥ 2× volume, within 40 trading days.
PTL: first breakout 24 Feb, shakeout to 50.2, **second breakout 12 Apr at 59.0 (swing score 89)**.

Every signal, quality-passing stocks, entry next open, net of 1%:

| Profile, hold | Strategy | Signals | Median | Win % | Mean vs basket | Profit factor |
|---|---|---|---|---|---|---|
| swing, 20d | base breakout | 506 | −0.1 | 50 | +0.1 | 1.6 |
| swing, 20d | **second breakout** | 60 | **+3.6** | **60** | **+2.0** | **2.4** |
| position, 60d | base breakout | 184 | −1.3 | 45 | +1.2 | 1.5 |
| position, 60d | second breakout | 20 | −1.2 | 45 | −0.1 | 1.0 |

- Swing: better than first breakouts in both 2025 and 2026. **On**, weight 1.0.
- Position: 2025 poor (n=7), 2026 good (n=13). **Off** until more history.
- **The swing MACD filter works against it**: second breakouts with a MACD cross older than 10 days returned
  +12.5% / +7.4% median (2025 / 2026, n=10 each) vs −3.4% / +0.6% for those passing. Hence `exempt: [second_breakout]`.
- Shortlist backtest (swing, 20d): mean +1.0% → **+1.3%**, median 0.0% → +0.1%, 2025 mean −0.3% → +0.3%,
  2026 unchanged. Picks from second breakout alone: 13 trades, median +7.3%, 85% winners.
- Side finding, not acted on: on today's 71-stock universe the MACD filter's effect on base breakout and quiet
  accumulation **flips between years** (hurt in 2025, helped in 2026). It was validated on DS30; worth re-testing.
  Re-tested with the shortlist backtest (docs/02-mvp-spec.md, "Technical filter re-check"): same flip; nothing
  beat the current rule in both periods, so it is kept.
