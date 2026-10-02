"""Review -> Telegram HTML and plain text."""

from __future__ import annotations

import html

from .review import Review

ARROW = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
DISCLAIMER = "AI review of research documents and StockEYE data. Probabilistic views, not investment advice."


def _e(s) -> str:
    return html.escape(str(s), quote=False)


def telegram_html(review: Review, as_of: str, doc_titles: list[str], max_calls: int = 6) -> str:
    mv = review.market_view
    lines = [
        f"<b>🤖 AI review · data to {as_of}</b>",
        f"<i>{_e(review.headline)}</i>",
        "",
        f"<b>Market</b> {ARROW[mv.stance]} {mv.stance}, {mv.horizon_days}d, {mv.confidence:.0f}% · {_e(mv.summary)}",
    ]
    if mv.risks:
        lines.append("⚠️ " + _e("; ".join(mv.risks[:3])))
    if review.calls:
        lines += ["", "<b>Calls</b>"]
        for c in sorted(review.calls, key=lambda c: -c.confidence)[:max_calls]:
            lines.append(f"{ARROW[c.stance]} <b>{_e(c.code)}</b> {c.stance} · {c.horizon_days}d · {c.confidence:.0f}% · "
                         f"StockEYE {c.stockeye_view}")
            lines.append(f"   {_e(c.thesis)}")
            lines.append(f"   ✋ wrong if: {_e(c.invalidation)}")
    if review.watch:
        lines += ["", "<b>Watch</b>"] + [f"👀 <b>{_e(w.code)}</b> {_e(w.what_to_watch)}" for w in review.watch[:5]]
    sectors = [s for s in review.sectors if s.stance != "neutral"]
    if sectors:
        lines += ["", "<b>Sectors</b> " + _e(" · ".join(f"{s.sector} {s.stance}" for s in sectors[:6]))]
    lines += ["", "📄 " + _e("; ".join(doc_titles)), f"<i>{_e(DISCLAIMER)}</i>"]
    return "\n".join(lines)


def text(review: Review, as_of: str) -> str:
    mv = review.market_view
    out = [f"AI review (StockEYE data to {as_of})", review.headline, "",
           f"MARKET: {mv.stance}, {mv.horizon_days} days, confidence {mv.confidence:.0f}%", mv.summary]
    out += [f"  + {d}" for d in mv.drivers] + [f"  ! {r}" for r in mv.risks]
    if review.macro:
        out += ["", "MACRO / NEWS"] + [f"  [{m.impact}] {m.topic}: {m.summary} (sectors: {', '.join(m.sectors) or '-'}; {m.source})"
                                       for m in review.macro]
    if review.sectors:
        out += ["", "SECTORS"] + [f"  {s.sector}: {s.stance} ({s.confidence:.0f}%) - {s.rationale}" for s in review.sectors]
    out += ["", "CALLS" if review.calls else "CALLS: none today"]
    for c in review.calls:
        out += [f"  {c.code} ({c.company}): {c.stance}, {c.horizon_days}d, {c.confidence:.0f}% | priced in: {c.priced_in} | "
                f"StockEYE {c.stockeye_view}: {c.stockeye_note}",
                f"    {c.thesis}"] + [f"    - {e}" for e in c.evidence] + [f"    wrong if: {c.invalidation}"]
    if review.watch:
        out += ["", "WATCH"] + [f"  {w.code}: {w.what_to_watch}" for w in review.watch]
    if review.noise:
        out += ["", "NOISE (not market-moving)"] + [f"  {n}" for n in review.noise]
    if review.data_gaps:
        out += ["", "DATA GAPS"] + [f"  {g}" for g in review.data_gaps]
    out += ["", DISCLAIMER]
    return "\n".join(out)
