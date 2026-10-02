import Link from "next/link";
import { Suspense } from "react";
import { CaseStudyForm, StockCodesDatalist } from "@/components/Controls";
import { StockChart } from "@/components/StockChart";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, Empty, LinkTabs, PageTitle, Stat, StrategyChip } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, signClass } from "@/lib/format";
import type { CaseSignal, CaseStudyView, Meta } from "@/lib/types";

export const metadata = { title: "Case study" };

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });

function Ret({ v }: { v: number | null | undefined }) {
  return <span className={signClass(v ?? null)}>{pct(v ?? null)}</span>;
}

function SignalRow({ s, cs, titles }: { s: CaseSignal; cs: CaseStudyView; titles: Record<string, string> }) {
  const blocked = s.status === "blocked";
  return (
    <tr className={blocked ? "text-muted" : ""}>
      <Td>{shortDate(s.date)}</Td>
      <Td>
        <span title={s.reasons.join("\n")}>
          <StrategyChip name={s.strategy} title={titles[s.strategy] ?? s.title} />
        </span>
        {s.role === "confirm" && <span className="ml-1 text-xs text-muted">confirming</span>}
      </Td>
      <Td>
        {blocked ? (
          <span title={s.blocked_by.join("\n")}>Blocked by RSI/MACD filter</span>
        ) : s.cut_date ? (
          <span>
            Shortlisted {shortDate(s.cut_date)}
            {cs.shortlist && (s.shortlist_rank ? <b> · #{s.shortlist_rank}</b> : <span className="text-muted"> · not in that day&apos;s top picks</span>)}
          </span>
        ) : s.role === "confirm" ? (
          <span className="text-muted">Confirming only</span>
        ) : (
          <span className="text-muted">Below the cut</span>
        )}
      </Td>
      <Td right>{s.days_on}</Td>
      <Td right>{num(s.best_score, 0)}</Td>
      <Td right>{num(s.entry)}</Td>
      {cs.horizons.map((h) => (
        <Td key={h} right><Ret v={s[`ret_${h}`] as number | null} /></Td>
      ))}
      <Td right><Ret v={s.best} /> / <Ret v={s.worst} /></Td>
      {cs.exits.map((ex) => (
        <Td key={ex.name} right>
          <Ret v={s[`ret_${ex.name}`] as number | null} />
          <span className="ml-1 text-xs text-muted">
            {String(s[`why_${ex.name}`] ?? "")} {s[`days_${ex.name}`] != null ? `${s[`days_${ex.name}`]}d` : ""}
          </span>
        </Td>
      ))}
      <Td right className="font-medium"><Ret v={s.to_last} /></Td>
    </tr>
  );
}

async function Result({ code, profile, from, to, shortlist }: { code: string; profile: string; from: string; to: string; shortlist: boolean }) {
  const q = new URLSearchParams({ profile, ...(from && { start: from }), ...(to && { end: to }), ...(shortlist && { shortlist: "true" }) });
  const [cs, meta] = await Promise.all([api<CaseStudyView>(`/api/casestudy/${encodeURIComponent(code)}?${q}`), api<Meta>("/api/meta")]);
  const w = cs.window;
  const signals = cs.signals.filter((s) => s.status === "signal");
  const shortlisted = signals.filter((s) => s.cut_date && s.role === "primary");
  const caught = cs.moves.filter((m) => m.caught_by.length).length;
  const base = { code, profile, ...(from && { from }), ...(to && { to }) };

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label={`${shortDate(cs.start)} → ${shortDate(cs.end)}`} value={<Ret v={w.change_pct} />} hint={`Close ${num(w.first_close)} → ${num(w.last_close)}`} />
          <Stat label="Low → high" value={`${num(w.low)} → ${num(w.high)}`} hint={`Low ${w.low_date}, high ${w.high_date}`} />
          <Stat label="Quality filter today" value={cs.quality_passed ? <Badge tone="good">Passes</Badge> : <Badge tone="bad">Fails</Badge>} hint={cs.quality_failures.join("\n")} />
          <Stat label="Signals" value={`${signals.length}`} hint="First day of each run, not blocked by the RSI/MACD filter" />
          <Stat label="Shortlisted runs" value={`${shortlisted.length}`} hint={`Runs where the stock's score reached ${cs.min_score}`} />
          <Stat label="Big moves caught early" value={`${caught} / ${cs.moves.length}`} />
        </div>
        {!cs.quality_passed && (
          <p className="mt-3 text-sm text-down">
            Fails today&apos;s quality filter ({cs.quality_failures.join("; ")}), so the daily screen wouldn&apos;t show it. Signals below are what the
            strategies alone saw.
          </p>
        )}
      </Card>

      <Card>
        <StockChart data={cs.chart} />
        <p className="mt-2 text-xs text-muted">
          Markers: first day of each {profile} signal in the period (blocked ones not shown). The chart starts 60 trading days early so the base is
          visible. <Link className="underline" href={`/stocks/${encodeURIComponent(code)}?profile=${profile}`}>Stock page →</Link>
        </p>
      </Card>

      <Card>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Signals and outcomes</h2>
          {!cs.shortlist && (
            <Link className="text-sm underline" href={`/casestudy?${new URLSearchParams({ ...base, shortlist: "1" })}`}>
              Show rank among all stocks (runs the backtest, ~20 s the first time)
            </Link>
          )}
        </div>
        {cs.signals.length === 0 ? (
          <Empty>No {profile} signals in this period.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Signal</Th>
                <Th>Strategy</Th>
                <Th title={`Shortlisted = the stock's ranking score reached ${cs.min_score} on some day of the run`}>Screen</Th>
                <Th right title="Consecutive days the signal stayed on">Days</Th>
                <Th right title="Best ranking score during the run">Score</Th>
                <Th right title="Next day's open">Entry</Th>
                {cs.horizons.map((h) => (
                  <Th key={h} right title={`Sell at the close ${h} trading days after the signal`}>{h}d</Th>
                ))}
                <Th right title={`Best / worst close within ${cs.primary_horizon} days, vs entry`}>Best / worst {cs.primary_horizon}d</Th>
                {cs.exits.map((ex) => (
                  <Th key={ex.name} right title={ex.label}>{ex.name}</Th>
                ))}
                <Th right title={`To the last close (${cs.last_date}: ${num(cs.last_close)})`}>To last</Th>
              </tr>
            </thead>
            <tbody>
              {cs.signals.map((s) => (
                <SignalRow key={`${s.date}-${s.strategy}-${s.status}`} s={s} cs={cs} titles={meta.strategies} />
              ))}
            </tbody>
          </Table>
        )}
        <p className="mt-2 text-xs text-muted">
          Returns from the next day&apos;s open, net of {cs.cost_pct}% round-trip cost. Exit styles: {cs.exits.map((e) => `${e.name} = ${e.label}`).join("; ")}
          {cs.exits.length ? " (open = still held at the last close)." : ""} Hover a strategy for its reasons.
        </p>
      </Card>

      <Card>
        <h2 className="mb-2 font-semibold">Big moves in this period</h2>
        {cs.moves.length === 0 ? (
          <Empty>No run-ups of +50% or more started in this period.</Empty>
        ) : (
          <ul className="space-y-2 text-sm">
            {cs.moves.map((m) => (
              <li key={m.date} className="flex flex-wrap items-center gap-2">
                <span className="tabular">
                  {shortDate(m.date)} at {num(m.start)} → peak {shortDate(m.peak_date)} <b className="text-up">+{m.peak_gain_pct.toFixed(0)}%</b>
                </span>
                {m.caught_by.length ? (
                  <>
                    <span className="text-ink-2">caught early by</span>
                    {m.caught_by.map((st) => <StrategyChip key={st} name={st} title={meta.strategies[st] ?? st} />)}
                  </>
                ) : (
                  <Badge tone="bad">not caught early</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default async function CaseStudyPage(props: PageProps<"/casestudy">) {
  const sp = await props.searchParams;
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const code = get("code").toUpperCase();
  const profile = get("profile") || "swing";
  const from = get("from");
  const to = get("to");
  const shortlist = get("shortlist") === "1";
  const meta = await api<Meta>("/api/meta");
  const tabHref = (p: string) => `/casestudy?${new URLSearchParams({ profile: p, ...(code && { code }), ...(from && { from }), ...(to && { to }) })}`;

  return (
    <>
      <PageTitle title={code ? `Case study: ${code}` : "Case study"} subtitle="What would StockEYE have done on this stock? Every signal, with outcomes.">
        <LinkTabs items={meta.profiles.map((p) => ({ value: p.name, label: p.name }))} active={profile} hrefFor={tabHref} />
      </PageTitle>
      <Card className="mb-4">
        <CaseStudyForm key={`${code}-${from}-${to}`} code={code} from={from} to={to} profile={profile} />
        <StockCodesDatalist codes={meta.universe} />
      </Card>
      {code ? (
        <Suspense key={`${code}-${profile}-${from}-${to}-${shortlist}`} fallback={<div className="py-16 text-center text-sm text-ink-2">Analysing {code}…</div>}>
          <Result code={code} profile={profile} from={from} to={to} shortlist={shortlist} />
        </Suspense>
      ) : (
        <Empty>
          Pick any stock and period (default: the last year). Try{" "}
          <Link className="underline" href="/casestudy?code=PTL&from=2025-11-01&profile=swing">PTL from Nov 2025</Link>.
        </Empty>
      )}
    </>
  );
}
