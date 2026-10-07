import { Suspense } from "react";
import { MovesExplorer } from "@/components/MovesExplorer";
import { Card, PageTitle, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import type { MovesView } from "@/lib/types";

export const metadata = { title: "Big moves" };

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const daysBefore = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
};

async function Moves() {
  const d = await api<MovesView>("/api/moves");
  const w = d.winners;
  const primary = (s: string) => s !== "big_hands";
  const caught = d.moves.filter((m) => m.caught_by.some((c) => primary(c.strategy)));
  const qualityMoves = d.moves.filter((m) => d.stocks[m.code]?.quality.length);
  const qualityCaught = qualityMoves.filter((m) => m.caught_by.some((c) => primary(c.strategy)));
  const signalled = d.signals.filter((s) => primary(s.strategy));
  const recent = new Set(signalled.filter((s) => s.date >= daysBefore(d.as_of, 30)).map((s) => s.code));

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Big moves" value={`${d.moves.length}`} hint={`In ${new Set(d.moves.map((m) => m.code)).size} stocks`} />
          <Stat label="Caught early by a strategy" value={`${caught.length} (${d.moves.length ? Math.round((caught.length / d.moves.length) * 100) : 0}%)`}
            hint="Big hands only confirms, so it doesn't count here" />
          <Stat label="Quality-stock moves caught" value={`${qualityCaught.length} / ${qualityMoves.length}`} hint="Stocks passing today's quality filter of any profile" />
          <Stat label="Stocks with a signal" value={`${new Set(signalled.map((s) => s.code)).size}`} hint="Any primary strategy, any profile" />
          <Stat label="Signalled in the last 30 days" value={`${recent.size}`} hint={`Since ${shortDate(daysBefore(d.as_of, 30))}`} />
        </div>
      </Card>
      <MovesExplorer data={d} />
      <div className="space-y-1 text-xs text-muted">
        <p>
          A big move is a close that rises at least {w.min_gain_pct}% within {w.within_days} trading days (prices adjusted for dividends and bonus
          shares), in every stock, not only the ones that pass the quality filter. <b>Caught early</b> = the strategy fired on that stock from{" "}
          {w.before_days} trading days before to {w.after_days} after the move started, at an entry no more than {w.max_entry_premium_pct}% above the
          starting price (the backtest&apos;s recall rule). Each chip shows when it fired and the gain left from that entry to the peak.
        </p>
        <p>
          Signals: each run&apos;s first day, after the profile&apos;s RSI/MACD filter. These are raw strategy hits, before the quality filter and the
          score cut, so the daily shortlist is a subset. Returns from the next day&apos;s open. Click a stock for its case study.
        </p>
        <p>
          Prices up to {shortDate(d.as_of)} · rebuilt by the daily job after the summary, or on the first visit after new prices or a profile change.
          Screening output from your own rules, not investment advice.
        </p>
      </div>
    </div>
  );
}

export default function MovesPage() {
  return (
    <>
      <PageTitle title="Big moves" subtitle="Every big run-up in any DSE stock, which of your strategies caught it early, and every stock they flagged." />
      <Suspense fallback={<div className="py-16 text-center text-sm text-ink-2">Loading… (after new prices this rebuilds the scan, about a minute)</div>}>
        <Moves />
      </Suspense>
    </>
  );
}
