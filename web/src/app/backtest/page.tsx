import { Suspense } from "react";
import { Table, Td, Th } from "@/components/Table";
import { Card, LinkTabs, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, signClass } from "@/lib/format";
import type { BacktestView, Meta, RecallRow, SummaryRow } from "@/lib/types";

export const metadata = { title: "Backtest" };

const mix = (s: string) => s.trim().replaceAll("+", " + ").replaceAll("_", " ");

/** Profit factor: gross wins / gross losses. Above 1.5 is the bar we set (docs/05). */
function pfClass(v: number | null) {
  if (v === null) return "text-ink-2";
  return v >= 1.5 ? "text-up" : v < 1 ? "text-down" : "";
}

function SummaryTable({ rows, days = false }: { rows: SummaryRow[]; days?: boolean }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Segment</Th>
          <Th right>Trades</Th>
          <Th right title="Median return per trade, net of costs">Median</Th>
          <Th right title="Average return per trade, net of costs">Mean</Th>
          <Th right title="Share of trades with a positive return">Hit rate</Th>
          <Th right title="Average return of the winning trades">Avg win</Th>
          <Th right title="Average return of the losing trades">Avg loss</Th>
          <Th right title="Profit factor: gross wins / gross losses. Above 1 makes money; we aim for 1.5+">PF</Th>
          <Th right title="Median of (pick return - basket return)">Vs basket</Th>
          <Th right title="Average of (pick return - basket return). Trend strategies earn from a few big winners, which the median hides">Vs basket (avg)</Th>
          <Th right title="Share of trades that beat the basket">Beat basket</Th>
          <Th right>Worst</Th>
          <Th right>Best</Th>
          {days && <Th right title="Median trading days from signal to exit">Days</Th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.segment} className={r.segment.startsWith(" ") ? "text-ink-2" : "font-medium"}>
            <Td>{mix(r.segment)}</Td>
            <Td right>{r.trades}</Td>
            <Td right className={signClass(r.median_ret)}>{pct(r.median_ret)}</Td>
            <Td right className={signClass(r.mean_ret)}>{pct(r.mean_ret)}</Td>
            <Td right>{pct(r.hit_rate, 0, false)}</Td>
            <Td right className="text-up">{pct(r.avg_win)}</Td>
            <Td right className="text-down">{pct(r.avg_loss)}</Td>
            <Td right className={pfClass(r.profit_factor)}>{num(r.profit_factor)}</Td>
            <Td right className={signClass(r.median_excess)}>{pct(r.median_excess)}</Td>
            <Td right className={signClass(r.mean_excess)}>{pct(r.mean_excess)}</Td>
            <Td right>{pct(r.beat_bench, 0, false)}</Td>
            <Td right className="text-down">{pct(r.worst)}</Td>
            <Td right className="text-up">{pct(r.best)}</Td>
            {days && <Td right>{num(r.median_days, 0)}</Td>}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function RecallTable({ rows }: { rows: RecallRow[] }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Caught by</Th>
          <Th right>Big moves</Th>
          <Th right>Caught early</Th>
          <Th right>Recall</Th>
          <Th right title="Picks (shortlist) or first-day signals (strategies) in the period">Signals</Th>
          <Th right title="Signals spent per big move caught: lower = fewer false alarms">Signals per catch</Th>
          <Th right title="Median trading days from the move's start to the first catching signal (negative = before)">Days after start</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.segment} className={r.segment.startsWith(" ") ? "text-ink-2" : "font-medium"}>
            <Td>{mix(r.segment)}</Td>
            <Td right>{r.moves}</Td>
            <Td right>{r.caught}</Td>
            <Td right>{pct(r.recall_pct, 0, false)}</Td>
            <Td right>{r.signals}</Td>
            <Td right>{num(r.signals_per_catch)}</Td>
            <Td right>{num(r.median_days_after_start, 0)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

async function Results({ profile }: { profile: string }) {
  const bt = await api<BacktestView>(`/api/backtest/${profile}`);
  const h = String(bt.primary_horizon);
  const main = bt.summary[h];
  const all = main.find((r) => r.segment === "all");
  const oos = main.find((r) => r.segment === "out-of-sample");
  const w = bt.winners;
  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-ink-2">
          {bt.start} → {bt.end} · {bt.universe_size} quality stocks · buy next day&apos;s open, sell after N trading days ·{" "}
          {bt.cost_pct}% round-trip cost · compared with an equal-weight basket of all quality stocks bought the same day.
          {bt.in_sample_until && <> Tuning period up to {bt.in_sample_until}; later dates are the untouched test.</>}
        </p>
        {all && (
          <p className="mt-2 text-sm">
            Holding {h} days: picks returned a median <b className={signClass(all.median_ret)}>{pct(all.median_ret)}</b> and an average{" "}
            <b className={signClass(all.mean_ret)}>{pct(all.mean_ret)}</b> (profit factor <b>{num(all.profit_factor)}</b>), beating the basket in{" "}
            <b>{pct(all.beat_bench, 0, false)}</b> of {all.trades} trades.
            {oos && <> In the test period: {pct(oos.mean_excess)} vs the basket on average over {oos.trades} trades.</>}
          </p>
        )}
      </Card>
      {bt.horizons.map((hz) => (
        <Card key={hz}>
          <h2 className="mb-2 font-semibold">Holding {hz} trading days</h2>
          <SummaryTable rows={bt.summary[String(hz)]} />
        </Card>
      ))}
      {bt.exits.map((ex) => (
        <Card key={ex.name}>
          <h2 className="font-semibold">Exit: {ex.label}</h2>
          <p className="mb-2 text-xs text-muted">
            Same entries as above. Stop checked on the day&apos;s low (a gap down fills at the open), trailing average on the close.
            {ex.open ? ` ${ex.open} trade(s) still open are left out.` : ""}
          </p>
          <SummaryTable rows={bt.summary[ex.name]} days />
        </Card>
      ))}
      <Card>
        <h2 className="font-semibold">Recall: big winners caught early</h2>
        <p className="mb-2 text-xs text-muted">
          A big move = the close rises {w.min_gain_pct}% or more within {w.within_days} trading days (one move per run-up). Caught = a pick or
          signal from {w.before_days} days before to {w.after_days} days after the move started, at no more than +{w.max_entry_premium_pct}% above
          its starting price.
        </p>
        <RecallTable rows={bt.recall} />
      </Card>
      <Card>
        <h2 className="mb-2 font-semibold">Most recent trades ({h}-day hold)</h2>
        <Table>
          <thead>
            <tr><Th>Signal date</Th><Th>Code</Th><Th>Strategies</Th><Th right>Score</Th><Th right>Return</Th><Th right>Basket</Th><Th right>Vs basket</Th></tr>
          </thead>
          <tbody>
            {bt.trades.slice(0, 60).map((t) => (
              <tr key={`${t.date}-${t.code}`}>
                <Td>{t.date}</Td>
                <Td className="font-medium">{t.code}</Td>
                <Td className="text-ink-2">{mix(t.strategies)}</Td>
                <Td right>{num(t.final_score as number, 0)}</Td>
                <Td right className={signClass(t[`ret_${h}`] as number)}>{pct(t[`ret_${h}`] as number)}</Td>
                <Td right>{pct(t[`bench_${h}`] as number)}</Td>
                <Td right className={signClass(t[`excess_${h}`] as number)}>{pct(t[`excess_${h}`] as number)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-2 text-xs text-muted">Trades still open (not enough days after the signal) show “–”.</p>
      </Card>
      <p className="text-xs text-muted">
        Caveats: today&apos;s fundamentals and today&apos;s universe are applied to past dates (look-ahead and survivorship bias). Small
        samples: treat differences of a point or two as noise.
      </p>
    </div>
  );
}

export default async function BacktestPage(props: PageProps<"/backtest">) {
  const sp = await props.searchParams;
  const profile = typeof sp.profile === "string" ? sp.profile : "swing";
  const meta = await api<Meta>("/api/meta");
  return (
    <>
      <PageTitle title="Backtest" subtitle="What if you had bought each day's shortlist?">
        <LinkTabs items={meta.profiles.map((p) => ({ value: p.name, label: p.name }))} active={profile} hrefFor={(v) => `/backtest?profile=${v}`} />
      </PageTitle>
      <Suspense key={profile} fallback={<div className="py-16 text-center text-sm text-ink-2">Running the backtest (about 20 seconds the first time)…</div>}>
        <Results profile={profile} />
      </Suspense>
    </>
  );
}
