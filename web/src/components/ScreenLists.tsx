"use client";

import Link from "next/link";
import { useState } from "react";
import type { ScreenSignal, WatchItem } from "@/lib/types";
import { int, num, pct } from "@/lib/format";
import { Table, Td, Th } from "./Table";
import { Badge, Empty, StrategyChip } from "./ui";

const stockHref = (code: string, profile: string) => `/stocks/${encodeURIComponent(code)}?profile=${profile}`;

const shortDate = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "–";

/** Every strategy hit on the screen day, filterable by strategy. */
export function AllSignals({ signals, profile }: { signals: ScreenSignal[]; profile: string }) {
  const [filter, setFilter] = useState<string>("all");
  const present = [...new Map(signals.map((s) => [s.strategy, s.title])).entries()];
  const shown = filter === "all" ? signals : signals.filter((s) => s.strategy === filter);
  const items = [{ value: "all", label: `All (${signals.length})` },
    ...present.map(([name, title]) => ({ value: name, label: `${title} (${signals.filter((s) => s.strategy === name).length})` }))];

  if (signals.length === 0) return <Empty>No strategy signals on this date.</Empty>;
  return (
    <div className="space-y-3">
      <div className="inline-flex flex-wrap rounded-lg border border-line bg-surface p-0.5 text-sm" role="group" aria-label="Filter by strategy">
        {items.map((it) => (
          <button
            key={it.value}
            type="button"
            aria-pressed={it.value === filter}
            onClick={() => setFilter(it.value)}
            className={`rounded-md px-3 py-1 ${it.value === filter ? "bg-surface-2 font-medium" : "text-ink-2 hover:text-ink"}`}
          >
            {it.label}
          </button>
        ))}
      </div>
      <Table>
        <thead>
          <tr>
            <Th>Stock</Th>
            <Th>Strategy</Th>
            <Th right title="Strategy score 0-100 (before weight, confluence and boosts)">Score</Th>
            <Th>Shortlist</Th>
            <Th>Why</Th>
          </tr>
        </thead>
        <tbody>
          {shown.map((s) => (
            <tr key={`${s.code}-${s.strategy}`}>
              <Td>
                <Link href={stockHref(s.code, profile)} className="font-medium hover:text-accent">{s.code}</Link>
              </Td>
              <Td>
                <StrategyChip name={s.strategy} title={s.title} />
                {s.role !== "primary" && <span className="ml-1.5 text-xs text-muted">confirming</span>}
              </Td>
              <Td right>{Math.round(s.score)}</Td>
              <Td>{s.on_shortlist ? <Badge tone="good">on shortlist</Badge> : <span className="text-muted">below cut</span>}</Td>
              <Td className="min-w-80 whitespace-normal text-ink-2">{s.reasons.join("; ")}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

/** Setups still forming: what each needs to become a signal, closest first. */
export function WatchList({ items, profile }: { items: WatchItem[]; profile: string }) {
  if (items.length === 0) return <Empty>No setups forming on this date.</Empty>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Stock</Th>
          <Th>Strategy</Th>
          <Th right title="Close needed to trigger: the failed breakout's high + the minimum re-break">Needs close ≥</Th>
          <Th right title="From the last close to the trigger">Away</Th>
          <Th right title="Volume needed on that day (re-break volume multiple x the recent average)">Volume needed</Th>
          <Th right title="Trading days left in the window">Days left</Th>
          <Th>First breakout</Th>
          <Th right title="Lowest close of the shakeout vs the old base high">Shakeout</Th>
          <Th right title="The setup is cancelled if a close falls below this (the base broke)">Cancel below</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((w) => {
          const m = w.metrics;
          return (
            <tr key={`${w.code}-${w.strategy}`} title={w.reasons.join("\n")}>
              <Td>
                <Link href={stockHref(w.code, profile)} className="font-medium hover:text-accent">{w.code}</Link>
              </Td>
              <Td><StrategyChip name={w.strategy} title={w.title} /></Td>
              <Td right>{num(m.trigger, 1)}</Td>
              <Td right className={m.to_trigger_pct <= 0 ? "text-up" : ""}>{pct(m.to_trigger_pct)}</Td>
              <Td right>{int(m.volume_needed)}</Td>
              <Td right>{m.days_left}</Td>
              <Td>{shortDate(m.first_date)}</Td>
              <Td right>{pct(m.shake_low_pct)}</Td>
              <Td right>{num(m.floor, 1)}</Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}
