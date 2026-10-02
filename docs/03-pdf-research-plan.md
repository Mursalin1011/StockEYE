# Daily PDF research: integration plan

_Status: v0.2 · 2026-10-02 · R0–R3 built as the "AI research review" (see below); R4 (email) and R5 (evaluation) open_

## Status 2026-10-02: what was built

Samples received: Shanta Securities **Newsflash** (morning, 5 pages: macro, sectors, company news),
**Daily Market Review** (evening, 5 pages: index, breadth, top turnover/gainers/losers, sector table,
top 30 by market cap, block trades, declarations, T-bond yields) and a **Monetary Policy Review**
(19 chart-heavy pages; text extraction is poor, e.g. "9 . 50 %").

Instead of fixed parsers per report (section 3.2), the PDFs go **directly to Claude** (document blocks:
it reads tables and charts), together with StockEYE's data on every mentioned stock, and the
analyst follows a written guide. This handles any new publisher without new parsing code.

| Piece | Where |
|---|---|
| Analyst guide (the "CLAUDE.md" for the AI) | `config/research/ANALYST.md` |
| Source recognition (publisher, type, ignore list) | `config/research/sources.yaml` |
| Add / inbox / text + stock detection | `research/documents.py`; `research add`, `research inbox`, dashboard |
| StockEYE context (quality, price/volume, signals, record dates, track record) | `research/context.py` |
| Review (structured JSON, validated; unknown codes dropped) | `research/review.py`; `research review`, dashboard |
| Prediction ledger + scoring vs the quality basket | `research/ledger.py`; `research score`, daily job |
| Telegram summary | `research/render.py` |

Stock detection on the samples: the newsflash's CSE50 list and company news map correctly by name
(One Bank → ONEBANKPLC, Ibn Sina → IBNSINA, Heidelberg → HEIDELBCEM); the market review yields 82 codes
from its tables. "BBS" (Bureau of Statistics) is on the ignore list.

Still open: R4 (fetch from email automatically), R5 (after ~3 months of scored calls: is the AI's
confidence calibrated, and do its calls add to StockEYE's signals?). Rules that use AI calls in the
screen itself (boosts, filters, section 3.4) wait for R5 evidence.

## 1. Goal

Each trading day, read the PDFs you receive by email (and their links), pull out what matters per
stock (ratings, target prices, news, events, market views), and use it in the screen:
as **filters**, as **score boosts**, and as **context** in the Telegram summary and the dashboard.
Everything stays configurable in YAML and is stored, so it can be backtested once enough history
has built up.

## 2. What these PDFs usually contain (to confirm with your samples)

DSE broker and research houses typically send a daily market update with:

| Section | Example content | How we'd use it |
|---|---|---|
| Market summary | DSEX move, turnover, breadth, sector leaders | Market context line; market regime flag |
| News / price-sensitive information | dividend declarations, board meetings, regulator queries, credit ratings | Filters (e.g. skip stocks under a regulatory query), news lines per pick |
| Recommendations / top picks | stock, Buy/Hold/Sell, target price, horizon | Boost or confirmation; upside to target |
| Technical views | support/resistance, trend calls | Context; maybe confirmation |
| Block trades, foreign/institutional flows | who traded what, in size | Strong fit for your "big hands" idea |

## 3. Pipeline

```
 Email / link / drop folder
          │  1. Acquire (daily, before the 2:45pm screen)
          ▼
 data/inbox/pdf/<date>/<source>.pdf  ── stored once (hash), never re-downloaded
          │  2. Extract text + tables (pdfplumber; OCR only if a PDF is scanned)
          ▼
 Raw text per page
          │  3. Structure: fixed-layout tables -> deterministic parser
          │                narrative (news, views) -> LLM extraction into a strict JSON schema
          ▼
 Validated items: code ∈ DSE list, numbers cross-checked with our prices, page + quote kept
          │  4. Use (rules in config/profiles/*.yaml)
          ▼
 Screen: filters · boosts · "research_view" confirmation strategy · news/context lines
          │  5. Deliver
          ▼
 Telegram summary · dashboard (pick card + document viewer with the exact quote)
```

### 3.1 Acquire: options

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Link** | Fetch the PDF URL with a new source adapter, like the DSE ones | Simplest, fully automatic | Only if the link is stable or predictable and not behind a login |
| **B1. Outlook on this PC** | Python reads new mail from a sender/folder via Outlook desktop automation and saves the attachments | No admin rights or IT approval; runs in the daily job | Outlook desktop must be installed and signed in |
| B2. Microsoft Graph API | App registration with mail-read permission | Clean, works without Outlook open | Needs your org's IT/admin consent |
| B3. Power Automate | Flow saves attachments to a OneDrive folder | No code | Needs a licence; OneDrive sync folder |
| **C. Drop folder** | You save the PDF into `data/inbox/pdf/` | Always works | Manual |

**Recommendation:** start with **C + A** so parsing can begin immediately, then add **B1** for hands-free daily runs.

### 3.2 Extract and structure

- **Text and tables:** `pdfplumber` (keeps the table layout); OCR with Tesseract only for scanned pages.
- **Two kinds of parsers:**
  - **Deterministic** for fixed-layout tables (e.g. a "Top picks" table with code / rating / target). Exact, free, fast.
  - **LLM extraction** (Claude API) for narrative text, with a strict JSON schema: per item `code, type
    (rating | target | news | event | technical_view | flow | market_view), rating, target_price, horizon,
    sentiment (-2..+2), summary, quote, page, confidence`.
- **Validation:**
  - Trading codes must exist on DSE.
  - Quoted prices must be within a few % of our stored close for that day.
  - Every item keeps the **exact quote and page**, so you can check it in one click.
  - Low-confidence items go to a review list in the dashboard instead of into the screen.
- **Safety:** PDF text is treated as data only. Extraction can only fill the schema; nothing in a PDF
  can trigger an action.

### 3.3 Storage (new tables)

- `documents(id, date, source, url, file_path, sha256, pages, received_at, status)`
- `doc_items(doc_id, code, type, rating, target_price, horizon, sentiment, summary, quote, page, confidence, reviewed)`
- `doc_market_notes(doc_id, date, kind, text)`

### 3.4 Use in the screen (all configurable per profile)

```yaml
filters:
  research:                      # exclude on negative items in the last N days
    enabled: true
    lookback_days: 5
    exclude_types: [regulatory_query, z_category_move]
    min_sentiment: -1
ranking:
  boosts:
    - { metric: research_rating, when: { in: [Buy] }, points: 5, label: "broker Buy" }
    - { metric: target_upside_pct, when: { min: 15 }, points: 5, label: "target upside" }
strategies:
  research_view: { role: confirm, weight: 0.5 }   # counts as agreement, never a pick alone
```

Your own **criteria** (the rules you apply when reading these PDFs) become rules in this same format
once you describe them.

### 3.5 Delivery

- Telegram, under each pick: `📄 <source> 01 Oct: Buy, target 250 (+15%) — "quote…"`.
- A short **market note** line from the day's PDFs at the top of the summary.
- Dashboard: a **Research** page (daily documents, extracted items, review queue) and a research panel on each stock page.

### 3.6 Measure

Every extracted item is stored from day one. After about 3 months:
- **Backtest:** does "broker Buy + our signal" beat the quality-stock basket?
- **Per-source accuracy:** hit rate of each broker's ratings and targets. This is valuable for the platform later.

## 4. Daily timing

| When | What |
|---|---|
| PDF arrives (time to confirm) | Acquire + extract + structure (a few minutes) |
| Optional ~09:45 | Pre-market Telegram brief: what the PDFs say about your watchlist and yesterday's picks |
| 14:45 | Existing screen, now using the day's research items |

## 5. Risks and constraints

- **Copyright and redistribution:** broker research is usually for clients only. Fine for personal use;
  a product needs permission or licensed feeds.
- **Privacy:** LLM extraction sends PDF text to the Claude API. A local-only mode (deterministic parsers
  only) is possible if you prefer, but it handles narrative text worse.
- **Cost:** small per day. I'll estimate it from your actual PDFs (pages and tokens) before turning it on.
- **Layout changes:** deterministic parsers break when a broker redesigns a PDF. The LLM path plus validation and
  the review queue absorb this; a failed parse alerts you on Telegram.
- **Email access:** a company mailbox may restrict automation. B1 avoids most of this.

## 6. Milestones

| # | Milestone | Done when |
|---|---|---|
| R0 | Samples and criteria (you) | 2–3 PDFs from different days, the link(s), and your criteria |
| R1 | Ingest | Drop folder + link fetcher; PDFs stored with hash; text extracted for every sample |
| R2 | Structure | Parsers + LLM extraction + validation; ≥ 95% of codes and ratings match a manual read of the samples |
| R3 | Integrate | Research filter, boosts, confirmation strategy; Telegram lines; dashboard Research page |
| R4 | Automate email | B1 (or B2) fetches daily with no manual step; alerts if a PDF is missing |
| R5 | Evaluate | After ~3 months: backtest + per-source accuracy; tune or drop rules |

## 7. What I need from you

1. **2–3 sample PDFs from different days** (drop them in `data/inbox/pdf/`) and the **link(s)**.
2. **Senders / sources** and roughly **what time** they arrive.
3. **Your criteria:** what you look for in them, e.g. "if a broker lists it as a top pick and our volume
   signal fires, rank it higher" or "ignore anything with a regulator query".
4. **LLM extraction:** OK to use the Claude API (needs an API key), or local-only parsing?
5. **Email access:** Outlook desktop automation (B1) on this PC is fine? I can also look at the emails
   through the Outlook connector in this session if you'd like me to find the samples myself.
