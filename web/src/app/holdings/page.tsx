import Link from "next/link";
import { DeleteEntryButton, TradeForm, UndoButton } from "@/components/HoldingsControls";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, Empty, PageTitle, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { int, num, pct, signClass } from "@/lib/format";
import type { HoldingCheck, HoldingsView, LedgerEntry } from "@/lib/types";

export const metadata = { title: "Holdings" };

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const taka = (v: number | null | undefined, signed = false) =>
  v === null || v === undefined ? "–" : `${signed && v > 0 ? "+" : v < 0 ? "−" : ""}৳${int(Math.abs(v))}`;
/** Where a level sits relative to the close, e.g. "8.2% below". */
const away = (level: number | null, close: number | null) => {
  if (level === null || !close) return "";
  const p = (level / close - 1) * 100;
  return `${Math.abs(p).toFixed(1)}% ${p > 0 ? "above" : "below"}`;
};
const ACTION_TEXT = { buy: "bought", sell: "sold", stop: "stop" } as const;

function entryText(e: LedgerEntry) {
  if (e.action === "stop") return `${e.code} stop ${e.price ? num(e.price, 2) : "reset to default"}`;
  return `${e.code} ${ACTION_TEXT[e.action]}${e.qty ? ` ${int(e.qty)}` : ""} @ ${num(e.price, 2)} on ${shortDate(e.date)}`;
}

/** Two rows per position: the numbers, then its checks across the full width (so warnings stay visible on narrow screens). */
function PositionRow({ p }: { p: HoldingCheck }) {
  const stopHit = p.close !== null && p.close <= p.stop;
  const nb = "!border-b-0";
  const quiet = p.warnings.length === 0 && p.notes.length === 0 && p.news.length === 0;
  return (
    <>
      <tr className="align-top">
        <Td className={`font-medium ${nb}`}>
          <Link className="underline" href={`/stocks/${p.code}`}>{p.code}</Link>
          <div className="mt-1 flex gap-2 text-xs font-normal">
            <Link className="text-ink-2 underline hover:text-ink" href={`/holdings?action=sell&code=${p.code}#add`}>sell</Link>
            <Link className="text-ink-2 underline hover:text-ink" href={`/holdings?action=stop&code=${p.code}#add`}>stop</Link>
          </div>
        </Td>
        <Td right className={nb}>{p.sized ? int(p.shares) : <span className="text-muted" title="Entered without a share count">{p.buys} buy{p.buys > 1 ? "s" : ""}</span>}</Td>
        <Td right className={nb}>
          {num(p.cost, 2)}
          <div className="text-xs text-muted">since {shortDate(p.opened)}</div>
        </Td>
        <Td right className={nb}>
          {num(p.close, 2)}
          <div className={`text-xs ${signClass(p.day_pct)}`}>{p.traded_today ? `${pct(p.day_pct)} today` : "not traded"}</div>
        </Td>
        <Td right className={`font-semibold ${signClass(p.pnl_pct)} ${nb}`}>
          {pct(p.pnl_pct)}
          <div className="text-xs font-normal">{p.pnl_amount !== null ? taka(p.pnl_amount, true) : ""}</div>
        </Td>
        <Td right className={nb}>
          {p.days_held}d
          <div className="text-xs text-muted" title={`Highest close since the buy: ${num(p.peak, 2)}`}>
            {p.peak && p.close !== null && p.close < p.peak ? `${pct((p.close / p.peak - 1) * 100)} from high` : "at high"}
          </div>
        </Td>
        <Td right className={`${stopHit ? "text-down" : ""} ${nb}`}>
          {num(p.stop, 2)}
          <div className="text-xs text-muted">{p.default_stop ? "default · " : ""}{away(p.stop, p.close)}</div>
        </Td>
        <Td right className={nb}>
          {num(p.ma, 2)}
          <div className="text-xs text-muted">{away(p.ma, p.close)}</div>
        </Td>
      </tr>
      <tr>
        <td colSpan={8} className="border-b border-line px-3 pb-3 text-sm">
          <div className="sticky left-3 max-w-[calc(100vw-5rem)] space-y-0.5">
            {quiet && <span className="text-muted">Nothing to flag</span>}
            {p.warnings.map((w, i) => <div key={i} className="text-down">{w}</div>)}
            {p.notes.map((n, i) => <div key={i} className="text-ink-2">{n}</div>)}
            {p.news.map((n, i) => <div key={i} className="text-xs text-muted">📰 {n}</div>)}
          </div>
        </td>
      </tr>
    </>
  );
}

export default async function HoldingsPage(props: PageProps<"/holdings">) {
  const sp = await props.searchParams;
  const d = await api<HoldingsView>("/api/holdings");
  const action = sp.action === "sell" || sp.action === "stop" ? sp.action : undefined;
  const code = typeof sp.code === "string" ? sp.code.toUpperCase() : undefined;
  const flagged = d.positions.filter((p) => p.warnings.length > 0).length;
  const s = d.settings;

  return (
    <>
      <PageTitle
        title="Holdings"
        subtitle={<>Your positions at the {shortDate(d.as_of)} close, checked the same way as the 3pm Telegram summary. Entries from Telegram (<code>/bought PTL 53.7 500</code>) show up here too.</>}
      />

      <Card className="mb-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Open positions" value={`${d.positions.length}`} />
          <Stat label="Need a look" value={<span className={flagged ? "text-down" : ""}>{flagged}</span>} hint="Stop hit or close, below the moving average, heavy selling" />
          <Stat label="Value" value={d.totals ? taka(d.totals.value) : "–"} hint={d.totals ? `Cost ${taka(d.totals.cost)}` : "Shown when every position has a share count"} />
          <Stat
            label={d.totals ? `P/L · ${pct(d.totals.pnl_pct)}` : "P/L"}
            value={d.totals ? <span className={signClass(d.totals.pnl)}>{taka(d.totals.pnl, true)}</span> : "–"}
            hint="Open positions, against the average cost adjusted for dividends and bonus shares"
          />
        </div>
      </Card>

      <Card className="mb-4">
        <h2 className="mb-3 font-semibold">Add an entry</h2>
        <TradeForm
          key={`${action ?? ""}-${code ?? ""}`}
          codes={d.codes}
          openCodes={d.positions.map((p) => p.code)}
          lastClose={d.last_close}
          today={d.today}
          defaultStopPct={s.default_stop_pct}
          initial={{ action, code }}
        />
      </Card>

      <Card className="mb-4">
        <h2 className="mb-2 font-semibold">Open positions</h2>
        {d.positions.length === 0 ? (
          <Empty>No open positions. Add a buy above, or send <code>/bought PTL 53.7 500</code> to your Telegram bot.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Stock</Th><Th right>Shares</Th>
                <Th right title="Average cost per share, adjusted for dividends and bonus shares since the buy">Avg cost</Th>
                <Th right>Close</Th><Th right>P/L</Th><Th right title="Trading days since the first buy">Held</Th>
                <Th right title={`Yours, or ${s.default_stop_pct}% below the average cost`}>Stop</Th>
                <Th right title="Moving average of the close">MA{s.trail_ma}</Th>
              </tr>
            </thead>
            <tbody>{d.positions.map((p) => <PositionRow key={p.code} p={p} />)}</tbody>
          </Table>
        )}
      </Card>

      {d.reentries.length > 0 && (
        <Card className="mb-4">
          <h2 className="mb-2 font-semibold">🔁 Signalling again after you sold</h2>
          <ul className="space-y-2 text-sm">
            {d.reentries.map((r) => (
              <li key={r.code}>
                <Link className="font-medium underline" href={`/stocks/${r.code}`}>{r.code}</Link>{" "}
                <span className="text-ink-2">sold {shortDate(r.closed!)} at {num(r.exit_price, 2)} (<span className={signClass(r.realized_pct)}>{pct(r.realized_pct)}</span>)</span>
                {r.what.map((w, i) => <div key={i} className="text-ink-2">{w}</div>)}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">Entries</h2>
            <UndoButton disabled={d.ledger.length === 0} />
          </div>
          {d.ledger.length === 0 ? (
            <Empty>No entries yet.</Empty>
          ) : (
            <Table>
              <thead>
                <tr><Th>Date</Th><Th>Stock</Th><Th>Entry</Th><Th right>Price</Th><Th right>Shares</Th><Th>From</Th><Th /></tr>
              </thead>
              <tbody>
                {d.ledger.map((e) => (
                  <tr key={e.id}>
                    <Td>{shortDate(e.date)}</Td>
                    <Td className="font-medium">{e.code}</Td>
                    <Td><Badge tone={e.action === "buy" ? "good" : e.action === "sell" ? "bad" : "neutral"}>{ACTION_TEXT[e.action]}</Badge></Td>
                    <Td right>{e.action === "stop" && !e.price ? "default" : num(e.price, 2)}</Td>
                    <Td right>{e.qty ? int(e.qty) : <span className="text-muted">{e.action === "sell" ? "all" : "–"}</span>}</Td>
                    <Td className="text-xs text-muted">{e.source}</Td>
                    <Td><DeleteEntryButton id={e.id} what={entryText(e)} /></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card className="min-w-0">
          <h2 className="mb-2 font-semibold">Closed positions</h2>
          {d.closed.length === 0 ? (
            <Empty>None yet.</Empty>
          ) : (
            <Table>
              <thead>
                <tr><Th>Stock</Th><Th>Held</Th><Th right>Avg cost</Th><Th right>Sold at</Th><Th right>Result</Th></tr>
              </thead>
              <tbody>
                {d.closed.map((c, i) => (
                  <tr key={`${c.code}-${i}`}>
                    <Td className="font-medium"><Link className="underline" href={`/stocks/${c.code}`}>{c.code}</Link></Td>
                    <Td>{shortDate(c.opened)} → {shortDate(c.closed!)}</Td>
                    <Td right>{num(c.cost, 2)}</Td>
                    <Td right>{num(c.exit_price, 2)}</Td>
                    <Td right className={signClass(c.realized_pct)}>{pct(c.realized_pct)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <p className="mt-2 text-xs text-muted">
            For {s.reentry_days} days after a sell, a new signal in that stock shows above and in the 3pm message.
            Prices are adjusted to today for dividends and bonus shares, so they can differ from what you paid.
          </p>
        </Card>
      </div>
    </>
  );
}
