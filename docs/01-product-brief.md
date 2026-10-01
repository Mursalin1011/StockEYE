# DSE Stock Screener — Product Brief

_Status: Draft v0.1 · 2026-09-30_

## 1. Vision

A configurable, multi-strategy screening assistant for the Dhaka Stock Exchange.
Each trading day it goes through the market the way an experienced investor would,
applies one or more **strategies expressed as editable rules**, and sends a short,
explained shortlist around 3pm.

It is used personally first and built so it can become a product later.

## 2. Problem

- Scanning charts by eye across 30 to 390+ stocks takes a lot of time, is inconsistent, and is easy to skip on busy days.
- Good setups, such as quiet accumulation, show up in the numbers before they are obvious on a chart.
- Existing DSE sites (amarstock, stocknow, LankaBangla) show data but **don't let you encode your own method**, combine methods, or check whether a method has worked before.

## 3. Users

| Persona | Now / Later | Needs |
|---|---|---|
| **Owner-investor** (you): active retail investor who uses fundamentals + price/volume and can tweak Python | Now | Daily shortlist from own rules, reasons for each pick, easy tuning |
| Retail investors | Later | Ready-made strategies, simple UI, alerts |
| Brokerage / asset-manager analysts | Later | Custom strategies, backtests, exports |

## 4. Core concepts

- **Universe**: which stocks to scan (MVP: DS30, then all listed).
- **Filter**: pass/fail gate, e.g. "Category A or B", "not Z", "min market cap".
- **Strategy**: a named set of rules plus parameters that produces a **score (0–100)** and **reasons** per stock.
  Several strategies run every day.
- **Confluence**: a stock flagged by more than one strategy is ranked higher.
- **Profile**: a saved set of strategies, parameters and a universe. Later, one per user.

## 5. The first strategy: quiet accumulation (owner's method)

1. **Quality**: good reputation and business (Category A/B, dividend history, profitable, sponsor holding).
2. **Stable price**: price moves in a narrow range over N weeks.
3. **Rising volume**: recent volume is well above the stock's own baseline.
4. **Divergence**: volume growth is much larger than price growth. This is the signal.

DSE-specific risk: the same pattern in weak, low-float stocks is often **syndicate or
manipulation activity**. The quality filter and a red-flag filter are required, not optional.

## 6. Differentiators (for the product later)

1. **Strategy-as-config**: users tune numbers and combine strategies without code.
2. **Explainability**: each pick says *why* (e.g. "Vol 20d/60d = 2.1×, price range 6%, avg trade size +35%").
3. **Built-in backtest**: "when this fired before, what happened in the next 20/60 days?"
4. **DSE-aware data**: adjustment for bonus/rights issues, category, trade-count analytics, floor-price periods excluded.

## 7. Success metrics (MVP)

| Metric | Target |
|---|---|
| Daily run succeeds without manual fixes | ≥ 95% of trading days |
| Summary delivered | by 15:15 BST |
| Your daily review time | ≤ 15 min |
| Agreement: picks you'd have chosen yourself (first 4 weeks) | ≥ 60% |
| Backtest of the core strategy available | Yes, for 2+ years of history |

## 8. "Product later": decisions to make now

- **Data licensing.** Scraping public sites is acceptable for personal use. **A commercial product needs licensed data**:
  a DSE data-vendor agreement, or agreements with amarstock/LankaBangla. The code must therefore
  put every data source behind a replaceable adapter.
- **Regulation.** Publishing buy/sell signals to others may fall under BSEC rules for research
  analysts/advisers. Get legal advice before any public launch. Position the product as a *screening tool, not advice*.
- **Multi-user readiness.** Keep the engine, strategies and user config separate, so profiles can become per-user later.

## 9. Key risks

| Risk | Impact | Mitigation |
|---|---|---|
| DSE site changes (already happened: dsebd.org → dse.com.bd) | Pipeline breaks | Adapter per source, a second source as fallback, alert on failure |
| Limited free history (DSE archive keeps ~2 years) | Weak backtests | **Start collecting and storing now**, get older history from other sources |
| Bonus/rights issues distort history | False signals | Adjustment factors (see MVP spec §4.3) |
| Manipulated stocks look like accumulation | Bad picks | Quality + red-flag filters, weighting by trade size |
| Overfitting thresholds | False confidence | Backtest with out-of-sample periods |
