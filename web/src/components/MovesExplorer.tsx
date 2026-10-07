"use client";

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import type { BigMove, MoveSignal, MovesView } from "@/lib/types";
import { num, pct, signClass } from "@/lib/format";
import { Table, Td, Th } from "./Table";
import { Badge, Empty, StrategyChip } from "./ui";

const LIQUID_MN = 3; // = the swing quality filter's liquidity floor (BDT mn per day)
const isPrimary = (strategy: string) => strategy !== "big_hands";
const liquid = (v: number | null) => v !== null && v >= LIQUID_MN;
const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const field = "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm";

type Dir = "asc" | "desc";
type Sort<K extends string> = { key: K; dir: Dir };

function sortBy<T, K extends string>(rows: T[], sort: Sort<K>, get: (r: T, k: K) => string | number | null) {
  const m = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = get(a, sort.key), y = get(b, sort.key);
    if (x === null) return y === null ? 0 : 1;
    if (y === null) return -1;
    return (typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number)) * m;
  });
}

function SortTh<K extends string>({ k, sort, setSort, right, title, children }: {
  k: K; sort: Sort<K>; setSort: (s: Sort<K>) => void; right?: boolean; title?: string; children: ReactNode;
}) {
  const active = sort.key === k;
  return (
    <Th right={right} title={title}>
      <button
        type="button"
        className={`font-medium ${active ? "text-ink" : ""}`}
        onClick={() => setSort({ key: k, dir: active && sort.dir === "desc" ? "asc" : active ? "desc" : k === "code" ? "asc" : "desc" })}
      >
        {children}
        {active ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </Th>
  );
}

function Check({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label htmlFor={id} className="flex items-center gap-1.5 pb-1.5 text-sm">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Segmented<T extends string>({ label, items, value, onChange }: { label: string; items: { value: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm" role="group" aria-label={label}>
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          aria-pressed={it.value === value}
          onClick={() => onChange(it.value)}
          className={`rounded-md px-3 py-1 ${it.value === value ? "bg-surface-2 font-medium" : "text-ink-2 hover:text-ink"}`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function StockCell({ code, data }: { code: string; data: MovesView }) {
  const s = data.stocks[code];
  return (
    <div className="min-w-40">
      <div className="flex items-center gap-1.5">
        <Link className="font-medium underline-offset-2 hover:underline" href={`/casestudy?code=${encodeURIComponent(code)}&from=${data.from}`}>
          {code}
        </Link>
        {s?.category && <span className="text-xs text-muted" title="DSE category">{s.category}</span>}
        {s?.quality.length ? <span title={`Passes today's quality filter for: ${s.quality.join(", ")}`}><Badge tone="good">quality</Badge></span> : null}
      </div>
      <div className="max-w-56 truncate text-xs text-muted" title={s ? `${s.name} · ${s.sector}` : code}>{s?.name ?? code}</div>
    </div>
  );
}

const catchLabel = (data: MovesView, strategy: string, profile: string) => `${data.strategies[strategy] ?? strategy} · ${profile}`;

// --- Big moves -----------------------------------------------------------------

type MoveKey = "code" | "date" | "peak_date" | "peak_gain_pct" | "days" | "avg_value_mn_60" | "caught";

function MovesTab({ data }: { data: MovesView }) {
  const [q, setQ] = useState("");
  const [minGain, setMinGain] = useState(data.winners.min_gain_pct);
  const [from, setFrom] = useState("");
  const [caught, setCaught] = useState<"all" | "yes" | "no">("all");
  const [onlyQuality, setOnlyQuality] = useState(false);
  const [onlyLiquid, setOnlyLiquid] = useState(false);
  const [withBigHands, setWithBigHands] = useState(false);
  const [sort, setSort] = useState<Sort<MoveKey>>({ key: "peak_gain_pct", dir: "desc" });

  const catches = (m: BigMove) => m.caught_by.filter((c) => withBigHands || isPrimary(c.strategy));
  const needle = q.trim().toLowerCase();
  const rows = sortBy(
    data.moves.filter((m) => {
      const s = data.stocks[m.code];
      if (needle && !m.code.toLowerCase().includes(needle) && !s?.name.toLowerCase().includes(needle)) return false;
      if (m.peak_gain_pct < minGain || (from && m.date < from)) return false;
      if ((onlyQuality && !s?.quality.length) || (onlyLiquid && !liquid(m.avg_value_mn_60))) return false;
      const n = catches(m).length;
      return caught === "all" || (caught === "yes" ? n > 0 : n === 0);
    }),
    sort,
    (m, k) => (k === "caught" ? catches(m).length : m[k]),
  );
  const nCaught = rows.filter((m) => catches(m).length).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <label className="text-xs text-muted">
          Stock
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code or name" className={`${field} mt-1 block w-40`} />
        </label>
        <label className="text-xs text-muted">
          Min gain %
          <input type="number" min={data.winners.min_gain_pct} step={10} value={minGain} onChange={(e) => setMinGain(Number(e.target.value) || 0)} className={`${field} mt-1 block w-24`} />
        </label>
        <label className="text-xs text-muted">
          Started from
          <input type="date" value={from} min={data.from} max={data.as_of} onChange={(e) => setFrom(e.target.value)} className={`${field} mt-1 block`} />
        </label>
        <Segmented label="Caught early" value={caught} onChange={setCaught}
          items={[{ value: "all", label: "All" }, { value: "yes", label: "Caught" }, { value: "no", label: "Missed" }]} />
        <Check id="mv-quality" label="Quality stocks only" checked={onlyQuality} onChange={setOnlyQuality} />
        <Check id="mv-liquid" label={`Liquid only (≥ ৳${LIQUID_MN} mn/day)`} checked={onlyLiquid} onChange={setOnlyLiquid} />
        <Check id="mv-bighands" label="Count Big hands as a catch" checked={withBigHands} onChange={setWithBigHands} />
        <span className="ml-auto pb-1.5 text-sm text-ink-2">
          {rows.length} moves · {new Set(rows.map((m) => m.code)).size} stocks · {nCaught} caught
        </span>
      </div>
      {rows.length === 0 ? (
        <Empty>No big moves match these filters.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <SortTh k="code" sort={sort} setSort={setSort}>Stock</SortTh>
              <SortTh k="date" sort={sort} setSort={setSort} title="First day of the move (the close it is measured from)">Start</SortTh>
              <SortTh k="peak_date" sort={sort} setSort={setSort}>Peak</SortTh>
              <Th right>Start → peak</Th>
              <SortTh k="peak_gain_pct" sort={sort} setSort={setSort} right>Gain</SortTh>
              <SortTh k="days" sort={sort} setSort={setSort} right title="Trading days from start to peak">Days</SortTh>
              <SortTh k="avg_value_mn_60" sort={sort} setSort={setSort} right title="Average traded value over the 60 days before the start, BDT mn">Value/day</SortTh>
              <SortTh k="caught" sort={sort} setSort={setSort}>Caught early by</SortTh>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const cs = catches(m);
              return (
                <tr key={`${m.code}-${m.date}`}>
                  <Td><StockCell code={m.code} data={data} /></Td>
                  <Td>{shortDate(m.date)}</Td>
                  <Td>{shortDate(m.peak_date)}</Td>
                  <Td right>{num(m.start)} → {num(m.peak)}</Td>
                  <Td right className="font-semibold text-up">{pct(m.peak_gain_pct, 0)}</Td>
                  <Td right>{m.days}</Td>
                  <Td right className={liquid(m.avg_value_mn_60) ? "" : "text-muted"}>{num(m.avg_value_mn_60)}</Td>
                  <Td className="whitespace-normal">
                    {cs.length ? (
                      <div className="flex min-w-72 flex-wrap gap-1">
                        {cs.map((c) => (
                          <span key={c.key} title={`Fired ${shortDate(c.date)}, ${c.days_from_start} trading days from the start; ${pct(c.gain_left_pct)} left to the peak from that entry`}>
                            <StrategyChip name={c.strategy} title={`${catchLabel(data, c.strategy, c.profile)} ${c.days_from_start > 0 ? "+" : ""}${c.days_from_start}d · ${pct(c.gain_left_pct, 0)}`} />
                          </span>
                        ))}
                      </div>
                    ) : (
                      <Badge tone="bad">missed</Badge>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </div>
  );
}

// --- Strategy detections ---------------------------------------------------------

type DetKey = "code" | "n" | "last" | "median" | "best" | "caught";
type DetRow = { code: string; list: MoveSignal[]; n: number; counts: [string, number][]; last: string; median: number | null; best: number | null; caught: number };

function median(values: (number | null)[]) {
  const v = values.filter((x): x is number => x !== null).sort((a, b) => a - b);
  if (!v.length) return null;
  const i = v.length >> 1;
  return v.length % 2 ? v[i] : (v[i - 1] + v[i]) / 2;
}

function DetectionsTab({ data }: { data: MovesView }) {
  const [q, setQ] = useState("");
  const [strategy, setStrategy] = useState("");
  const [from, setFrom] = useState("");
  const [onlyQuality, setOnlyQuality] = useState(false);
  const [onlyLiquid, setOnlyLiquid] = useState(false);
  const [withBigHands, setWithBigHands] = useState(false);
  const [sort, setSort] = useState<Sort<DetKey>>({ key: "n", dir: "desc" });
  const [open, setOpen] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);

  const keys = useMemo(() => [...new Set(data.signals.map((s) => `${s.profile}:${s.strategy}`))].sort(), [data.signals]);
  const label = (key: string) => { const [p, s] = key.split(":"); return catchLabel(data, s, p); };
  const bigHands = withBigHands || strategy.endsWith(":big_hands");
  const needle = q.trim().toLowerCase();

  const signals = data.signals.filter((s) => (bigHands || isPrimary(s.strategy)) && (!strategy || `${s.profile}:${s.strategy}` === strategy)
    && (!from || s.date >= from) && (!onlyQuality || s.quality) && (!onlyLiquid || liquid(s.avg_value_mn_60))
    && (!needle || s.code.toLowerCase().includes(needle) || data.stocks[s.code]?.name.toLowerCase().includes(needle)));

  const caughtMoves = new Map<string, number>();
  for (const m of data.moves) {
    if (m.caught_by.some((c) => (bigHands || isPrimary(c.strategy)) && (!strategy || c.key === strategy))) caughtMoves.set(m.code, (caughtMoves.get(m.code) ?? 0) + 1);
  }
  const byCode = new Map<string, MoveSignal[]>();
  for (const s of signals) byCode.set(s.code, [...(byCode.get(s.code) ?? []), s]);
  const rows = sortBy<DetRow, DetKey>(
    [...byCode].map(([code, list]) => {
      const counts = new Map<string, number>();
      for (const s of list) counts.set(`${s.profile}:${s.strategy}`, (counts.get(`${s.profile}:${s.strategy}`) ?? 0) + 1);
      const bests = list.map((s) => s.best).filter((x): x is number => x !== null);
      return { code, list, n: list.length, counts: [...counts].sort((a, b) => b[1] - a[1]), last: list[0].date,
        median: median(list.map((s) => s.ret)), best: bests.length ? Math.max(...bests) : null, caught: caughtMoves.get(code) ?? 0 };
    }),
    sort,
    (r, k) => r[k],
  );

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setLimit(100); };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <label className="text-xs text-muted">
          Stock
          <input type="search" value={q} onChange={(e) => reset(setQ)(e.target.value)} placeholder="Code or name" className={`${field} mt-1 block w-40`} />
        </label>
        <label className="text-xs text-muted">
          Strategy
          <select value={strategy} onChange={(e) => reset(setStrategy)(e.target.value)} className={`${field} mt-1 block`}>
            <option value="">All strategies</option>
            {keys.map((k) => <option key={k} value={k}>{label(k)}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">
          Signals from
          <input type="date" value={from} min={data.from} max={data.as_of} onChange={(e) => reset(setFrom)(e.target.value)} className={`${field} mt-1 block`} />
        </label>
        <Check id="dt-quality" label="Passes that profile's quality filter" checked={onlyQuality} onChange={reset(setOnlyQuality)} />
        <Check id="dt-liquid" label={`Liquid only (≥ ৳${LIQUID_MN} mn/day)`} checked={onlyLiquid} onChange={reset(setOnlyLiquid)} />
        <Check id="dt-bighands" label="Include Big hands (confirm only)" checked={withBigHands} onChange={reset(setWithBigHands)} />
        <span className="ml-auto pb-1.5 text-sm text-ink-2">{rows.length} stocks · {signals.length} signals</span>
      </div>
      {rows.length === 0 ? (
        <Empty>No signals match these filters.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <SortTh k="code" sort={sort} setSort={setSort}>Stock</SortTh>
              <SortTh k="n" sort={sort} setSort={setSort} right>Signals</SortTh>
              <Th>Strategies that fired</Th>
              <SortTh k="last" sort={sort} setSort={setSort}>Latest</SortTh>
              <SortTh k="median" sort={sort} setSort={setSort} right title={`Median return from the next day's open to the close ${data.horizon} trading days later, net of costs`}>Median {data.horizon}d</SortTh>
              <SortTh k="best" sort={sort} setSort={setSort} right title={`Best close within ${data.horizon} days of any signal, vs entry`}>Best {data.horizon}d</SortTh>
              <SortTh k="caught" sort={sort} setSort={setSort} right title="Big moves on this stock these strategies caught early">Moves caught</SortTh>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((r) => (
              <Fragment key={r.code}>
                <tr>
                  <Td><StockCell code={r.code} data={data} /></Td>
                  <Td right>{r.n}</Td>
                  <Td className="whitespace-normal">
                    <div className="flex min-w-72 flex-wrap gap-1">
                      {r.counts.map(([k, n]) => {
                        const [p, s] = k.split(":");
                        return <StrategyChip key={k} name={s} title={`${catchLabel(data, s, p)} ×${n}`} />;
                      })}
                    </div>
                  </Td>
                  <Td>
                    {shortDate(r.last)}
                    <div className="text-xs text-muted">{catchLabel(data, r.list[0].strategy, r.list[0].profile)}</div>
                  </Td>
                  <Td right className={signClass(r.median)}>{pct(r.median)}</Td>
                  <Td right className={signClass(r.best)}>{pct(r.best)}</Td>
                  <Td right className={r.caught ? "" : "text-muted"}>{r.caught}</Td>
                  <Td>
                    <button type="button" className="text-xs underline" aria-expanded={open === r.code} onClick={() => setOpen(open === r.code ? null : r.code)}>
                      {open === r.code ? "Hide" : "Show"} signals
                    </button>
                  </Td>
                </tr>
                {open === r.code && (
                  <tr>
                    <td colSpan={8} className="border-b border-line bg-surface-2 p-3">
                      <Table>
                        <thead>
                          <tr>
                            <Th>Date</Th><Th>Strategy</Th><Th right>Score</Th><Th right>Close</Th>
                            <Th right>{data.horizon}d</Th><Th right>Best {data.horizon}d</Th><Th right title="To the last close, net of costs">To today</Th><Th />
                          </tr>
                        </thead>
                        <tbody>
                          {r.list.map((s) => (
                            <tr key={`${s.date}-${s.profile}-${s.strategy}`}>
                              <Td>{shortDate(s.date)}</Td>
                              <Td><StrategyChip name={s.strategy} title={catchLabel(data, s.strategy, s.profile)} /></Td>
                              <Td right>{num(s.score, 0)}</Td>
                              <Td right>{num(s.close)}</Td>
                              <Td right className={signClass(s.ret)}>{pct(s.ret)}</Td>
                              <Td right className={signClass(s.best)}>{pct(s.best)}</Td>
                              <Td right className={signClass(s.to_last)}>{pct(s.to_last)}</Td>
                              <Td>
                                {s.quality && <Badge tone="good">quality</Badge>} {!liquid(s.avg_value_mn_60) && <Badge>illiquid</Badge>}
                              </Td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </Table>
      )}
      {rows.length > limit && (
        <div className="text-center">
          <button type="button" className={`${field} hover:bg-surface-2`} onClick={() => setLimit(limit + 100)}>
            Show more stocks ({rows.length - limit} left)
          </button>
        </div>
      )}
    </div>
  );
}

export function MovesExplorer({ data }: { data: MovesView }) {
  const [tab, setTab] = useState<"moves" | "detections">("moves");
  return (
    <div className="space-y-4">
      <Segmented label="List" value={tab} onChange={setTab}
        items={[{ value: "moves", label: `Big moves (${data.moves.length})` }, { value: "detections", label: "Strategy detections" }]} />
      {tab === "moves" ? <MovesTab data={data} /> : <DetectionsTab data={data} />}
    </div>
  );
}
