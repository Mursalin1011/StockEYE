import { Suspense } from "react";
import { Table, Td, Th } from "@/components/Table";
import { Card, LinkTabs, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, signClass } from "@/lib/format";
import type { BacktestView, Meta, SummaryRow } from "@/lib/types";

export const metadata = { title: "Backtest" };

function SummaryTable({ rows }: { rows: SummaryRow[] }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Segment</Th>
          <Th right>Trades</Th>
          <Th right title="Median return per trade, net of costs">Median</Th>
          <Th right title="Share of trades with a positive return">Hit rate</Th>
          <Th right title="Median return of the quality basket bought the same day">Basket</Th>
          <Th right title="Median of (pick return - basket return)">Vs basket</Th>
          <Th right title="Share of trades that beat the basket">Beat basket</Th>
          <Th right>Worst</Th>
          <Th right>Best</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.segment} className={r.segment.startsWith(" ") ? "text-ink-2" : "font-medium"}>
            <Td>{r.segment.trim().replaceAll("+", " + ").replaceAll("_", " ")}</Td>
            <Td right>{r.trades}</Td>
            <Td right className={signClass(r.median_ret)}>{pct(r.median_ret)}</Td>
            <Td right>{pct(r.hit_rate, 0, false)}</Td>
            <Td right>{pct(r.median_bench)}</Td>
            <Td right className={signClass(r.median_excess)}>{pct(r.median_excess)}</Td>
            <Td right>{pct(r.beat_bench, 0, false)}</Td>
            <Td right className="text-down">{pct(r.worst)}</Td>
            <Td right className="text-up">{pct(r.best)}</Td>
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
            Holding {h} days: picks returned a median <b className={signClass(all.median_ret)}>{pct(all.median_ret)}</b> vs the basket&apos;s{" "}
            <b>{pct(all.median_bench)}</b>, beating it in <b>{pct(all.beat_bench, 0, false)}</b> of {all.trades} trades.
            {oos && <> In the test period: {pct(oos.median_excess)} vs the basket over {oos.trades} trades.</>}
          </p>
        )}
      </Card>
      {bt.horizons.map((hz) => (
        <Card key={hz}>
          <h2 className="mb-2 font-semibold">Holding {hz} trading days</h2>
          <SummaryTable rows={bt.summary[String(hz)]} />
        </Card>
      ))}
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
                <Td className="text-ink-2">{t.strategies.replaceAll("+", " + ").replaceAll("_", " ")}</Td>
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
        Caveats: today&apos;s fundamentals and today&apos;s DS30 list are applied to past dates (look-ahead and survivorship bias). Small
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
      <Suspense key={profile} fallback={<div className="py-16 text-center text-sm text-ink-2">Running the backtest (about 15 seconds the first time)…</div>}>
        <Results profile={profile} />
      </Suspense>
    </>
  );
}
