import Link from "next/link";
import { Suspense } from "react";
import { StockCodesDatalist } from "@/components/Controls";
import { EquityChart } from "@/components/EquityChart";
import { LabForm } from "@/components/LabForm";
import { StockChart } from "@/components/StockChart";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, Empty, LinkTabs, PageTitle, Stat } from "@/components/ui";
import { ApiError, api, apiPost } from "@/lib/api";
import { num, pct, signClass } from "@/lib/format";
import type { LabMeta, LabResultView, LabStock, LabSummaryRow, LabTrade, Meta, PlanJson } from "@/lib/types";

export const metadata = { title: "Trade lab" };

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });

function Ret({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  return <span className={`${signClass(v ?? null)} ${className}`}>{pct(v ?? null)}</span>;
}

/** Fill in anything a hand-edited ?p= plan left out, so the form always has every field. */
function withDefaults(d: PlanJson, p: Partial<PlanJson>): PlanJson {
  return {
    ...d, ...p,
    entry: { ...d.entry, ...p.entry }, exit: { ...d.exit, ...p.exit }, hold: { ...d.hold, ...p.hold },
    costs: { ...d.costs, ...p.costs }, capital: { ...d.capital, ...p.capital },
  };
}

function StockTable({ rows, basket }: { rows: LabStock[]; basket: string | null }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Stock</Th>
          <Th>Window</Th>
          <Th right title="Equity growth with the plan's sizing, net of costs">Plan</Th>
          <Th right title="Bought at the window's first open, held to its last close, less one round trip">Buy &amp; hold</Th>
          {basket && <Th right title={`Equal-weight basket (${basket}) held over the same window`}>Basket held</Th>}
          <Th right title="Largest fall of the plan's equity from a high">Plan max DD</Th>
          <Th right title="Largest fall of the stock's close from a high">Stock max DD</Th>
          <Th right title="Share of days with a position">In market</Th>
          <Th right>Trades</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.code}>
            <Td className="font-medium">{s.code}</Td>
            <Td className="text-ink-2">{shortDate(s.start)} → {shortDate(s.end)}</Td>
            <Td right className="font-medium"><Ret v={s.plan_pct} /></Td>
            <Td right><Ret v={s.buy_hold_pct} /></Td>
            {basket && <Td right><Ret v={s.basket_hold_pct} /></Td>}
            <Td right className="text-down">{pct(s.plan_max_dd_pct)}</Td>
            <Td right className="text-down">{pct(s.buy_hold_max_dd_pct)}</Td>
            <Td right>{pct(s.in_market_pct, 0, false)}</Td>
            <Td right>{s.trades}{s.open ? <span className="text-muted"> ({s.open} open)</span> : null}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function TradesTable({ rows, multi, basket }: { rows: LabTrade[]; multi: boolean; basket: boolean }) {
  const adjusted = rows.some((t) => Math.abs(t.entry_actual - t.entry) > 1e-6 || Math.abs(t.exit_actual - t.exit) > 1e-6);
  return (
    <Table>
      <thead>
        <tr>
          {multi && <Th>Stock</Th>}
          <Th title="Day the entry rule held (after the close)">Signal</Th>
          <Th>Bought</Th>
          <Th right title={adjusted ? "Adjusted for bonus/rights (actual traded price below)" : undefined}>At</Th>
          <Th>Sold</Th>
          <Th right>At</Th>
          <Th>Why</Th>
          <Th right title="Trading days from signal to exit">Days</Th>
          <Th right title="Net of the round-trip cost">Return</Th>
          {basket && <Th right title="Return minus the basket's over the same dates">Vs basket</Th>}
          <Th right title="Highest high / lowest low while held, vs the entry">Best / worst</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={`${t.code}-${t.entry_date}`} className={t.why === "open" ? "text-ink-2" : ""}>
            {multi && <Td className="font-medium">{t.code}</Td>}
            <Td className="text-ink-2">{shortDate(t.signal_date)}</Td>
            <Td>{shortDate(t.entry_date)}</Td>
            <Td right>
              {num(t.entry)}
              {adjusted && Math.abs(t.entry_actual - t.entry) > 1e-6 && <div className="text-xs text-muted">actual {num(t.entry_actual)}</div>}
            </Td>
            <Td>{t.why === "open" ? <Badge>still held</Badge> : shortDate(t.exit_date)}</Td>
            <Td right>
              {num(t.exit)}
              {adjusted && Math.abs(t.exit_actual - t.exit) > 1e-6 && <div className="text-xs text-muted">actual {num(t.exit_actual)}</div>}
            </Td>
            <Td>
              {t.why}
              {t.flags && <span className="ml-1 cursor-help text-down" title={t.flags}>⚠</span>}
            </Td>
            <Td right>{t.days}</Td>
            <Td right className="font-medium"><Ret v={t.ret_pct} /></Td>
            {basket && <Td right><Ret v={t.excess_pct} /></Td>}
            <Td right><Ret v={t.best_pct} /> / <Ret v={t.worst_pct} /></Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function SummaryTable({ rows, basket }: { rows: LabSummaryRow[]; basket: boolean }) {
  const label = (s: string) => s.trim().replace("exit: ", "sold on: ").replace("in-sample", "tuning period").replace("out-of-sample", "test period");
  return (
    <Table>
      <thead>
        <tr>
          <Th>Segment</Th>
          <Th right>Trades</Th>
          <Th right>Win rate</Th>
          <Th right title="Average return per trade, net of costs">Mean</Th>
          <Th right>Median</Th>
          <Th right>Avg win</Th>
          <Th right>Avg loss</Th>
          <Th right title="Profit factor: gross wins / gross losses. Above 1 makes money">PF</Th>
          {basket && <Th right title="Average of (trade return - basket return over the same dates)">Vs basket</Th>}
          {basket && <Th right title="Share of trades that beat the basket">Beat basket</Th>}
          <Th right>Best</Th>
          <Th right>Worst</Th>
          <Th right title="Median trading days from signal to exit">Days</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.segment} className={r.segment.startsWith(" ") ? "text-ink-2" : "font-medium"}>
            <Td>{r.segment.startsWith(" ") ? <span className="pl-3">{label(r.segment)}</span> : label(r.segment)}</Td>
            <Td right>{r.trades}</Td>
            <Td right>{pct(r.win_rate, 0, false)}</Td>
            <Td right><Ret v={r.mean_ret} /></Td>
            <Td right><Ret v={r.median_ret} /></Td>
            <Td right className="text-up">{pct(r.avg_win)}</Td>
            <Td right className="text-down">{pct(r.avg_loss)}</Td>
            <Td right className={r.profit_factor === null ? "text-ink-2" : r.profit_factor >= 1.5 ? "text-up" : r.profit_factor < 1 ? "text-down" : ""}>{num(r.profit_factor)}</Td>
            {basket && <Td right><Ret v={r.mean_excess} /></Td>}
            {basket && <Td right>{pct(r.beat_basket, 0, false)}</Td>}
            <Td right className="text-up">{pct(r.best)}</Td>
            <Td right className="text-down">{pct(r.worst)}</Td>
            <Td right>{num(r.median_days, 0)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

async function Result({ plan, chart }: { plan: PlanJson; chart: string }) {
  let r: LabResultView;
  try {
    r = await apiPost<LabResultView>("/api/simulate", { plan, chart_code: chart || null });
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) {
      return (
        <Card>
          <div className="text-sm font-medium text-down">Check the plan</div>
          <pre className="mt-1 text-sm whitespace-pre-wrap text-ink-2">{e.message}</pre>
        </Card>
      );
    }
    throw e;
  }
  const all = r.summary.find((s) => s.segment === "all");
  const closed = r.trades.filter((t) => t.why !== "open");
  const multi = r.plan.codes.length > 1;
  const one = r.stocks.length === 1 ? r.stocks[0] : null;
  const hasBasket = Boolean(r.basket) && r.trades.some((t) => t.basket_pct !== null && t.basket_pct !== undefined);
  const p = JSON.stringify(r.plan);

  return (
    <div className="space-y-4">
      <Card>
        <ul className="space-y-0.5 text-sm text-ink-2">
          {r.describe.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Trades" value={`${closed.length}${r.trades.length > closed.length ? ` + ${r.trades.length - closed.length} open` : ""}`} hint="Closed trades are in the stats; open ones are marked at the window's last close" />
          <Stat label="Win rate" value={pct(all?.win_rate ?? null, 0, false)} />
          <Stat label="Average per trade" value={<Ret v={all?.mean_ret} />} hint={`Median ${pct(all?.median_ret ?? null)}`} />
          <Stat label="Profit factor" value={num(all?.profit_factor ?? null)} hint="Gross wins / gross losses. Above 1 makes money" />
          {one ? (
            <Stat label="Plan vs buy & hold" value={<><Ret v={one.plan_pct} /> <span className="text-base font-normal text-ink-2">vs</span> <Ret v={one.buy_hold_pct} /></>}
              hint={`Max drawdown ${pct(one.plan_max_dd_pct)} vs ${pct(one.buy_hold_max_dd_pct)}`} />
          ) : (
            <Stat label="Stocks" value={`${r.stocks.length}`} />
          )}
          {hasBasket ? (
            <Stat label="Vs basket, per trade" value={<Ret v={all?.mean_excess} />} hint={`Average of (trade - ${r.basket} over the same dates); beat it ${pct(all?.beat_basket ?? null, 0, false)} of the time`} />
          ) : (
            <Stat label="Max drawdown" value={one ? <span className={one.plan_max_dd_pct < 0 ? "text-down" : "text-ink-2"}>{pct(one.plan_max_dd_pct)}</span> : "–"} />
          )}
        </div>
      </Card>

      {(r.pending.length > 0 || r.warnings.length > 0) && (
        <Card>
          {r.pending.map((line) => (
            <p key={line} className="mb-2 text-sm font-medium"><Badge tone="good">Signal now</Badge> {line}</p>
          ))}
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-2">
            {r.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </Card>
      )}

      <Card>
        <h2 className="mb-2 font-semibold">Per stock</h2>
        {r.stocks.length ? <StockTable rows={r.stocks} basket={hasBasket ? r.basket : null} /> : <Empty>No prices for these stocks in the window.</Empty>}
      </Card>

      {r.chart && r.chart_code && (
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">{r.chart_code}: trades on the chart</h2>
            {multi && (
              <LinkTabs items={r.stocks.map((s) => ({ value: s.code, label: s.code }))} active={r.chart_code}
                hrefFor={(c) => `/lab?${new URLSearchParams({ p, chart: c })}`} />
            )}
          </div>
          <StockChart data={r.chart} height={600} />
          <p className="mt-2 text-xs text-muted">
            Prices adjusted for bonus/rights{r.chart.overlays?.length ? "; lines are the price-level columns the plan uses" : ""}. The chart starts 60 trading days before the window.
            Hover a marker&apos;s day for the trade. <Link className="underline" href={`/casestudy?code=${encodeURIComponent(r.chart_code)}`}>Case study →</Link>
          </p>
        </Card>
      )}

      {r.chart_code && r.equity[r.chart_code]?.length > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">{r.chart_code}: equity, plan vs buy &amp; hold</h2>
          <EquityChart points={r.equity[r.chart_code]} start={r.plan.capital.start} />
          <p className="mt-2 text-xs text-muted">
            Plan: {r.plan.capital.per_trade_pct}% of equity per trade, the rest in cash; cost charged at each exit. Buy &amp; hold: the same starting money in the stock from the window&apos;s first open.
          </p>
        </Card>
      )}

      <Card>
        <h2 className="mb-2 font-semibold">Trades</h2>
        {r.trades.length ? <TradesTable rows={r.trades} multi={multi} basket={hasBasket} /> : <Empty>No trades: the entry rule never held in the window (see the notes above).</Empty>}
        {r.trades.some((t) => t.flags) && <p className="mt-2 text-xs text-muted">⚠ = the fill may not have been possible (e.g. a day locked at the price limit); hover it for details.</p>}
      </Card>

      {r.summary.length > 0 && all && all.trades > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">Summary</h2>
          <SummaryTable rows={r.summary} basket={hasBasket} />
          <p className="mt-2 text-xs text-muted">
            Closed trades, net of {r.plan.costs.round_trip_pct}% round-trip cost{hasBasket ? `; basket = ${r.basket}, bought and sold on the same days` : ""}.
            {r.plan.in_sample_until ? ` Tuning period = signals up to ${r.plan.in_sample_until}; judge the plan on the test period.` : ""}
          </p>
        </Card>
      )}
    </div>
  );
}

export default async function LabPage(props: PageProps<"/lab">) {
  const sp = await props.searchParams;
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const [lab, meta] = await Promise.all([api<LabMeta>("/api/lab"), api<Meta>("/api/meta")]);

  let plan: PlanJson | null = null;
  let error = "";
  if (get("p")) {
    try {
      plan = withDefaults(lab.default_plan, JSON.parse(get("p")));
    } catch {
      error = "The plan in the link couldn't be read. Build it again below.";
    }
  } else if (get("plan")) {
    const saved = lab.plans.find((s) => s.name === get("plan"))?.plan;
    if (saved) plan = get("code") ? { ...saved, codes: [get("code").toUpperCase()] } : saved;
    else error = `No saved plan called "${get("plan")}".`;
  }
  const initial = plan ?? { ...lab.default_plan, codes: get("code") ? [get("code").toUpperCase()] : [] };
  const chart = get("chart").toUpperCase();

  return (
    <>
      <PageTitle title="Trade lab" subtitle="Your own entry, exit and hold rules on any stock and period: every trade, against buy & hold and the basket." />
      <Card className="mb-4">
        <LabForm key={get("p") || get("plan")} meta={lab} initial={initial} codes={meta.universe} />
        <StockCodesDatalist codes={meta.universe} />
      </Card>
      {error && <p className="mb-4 text-sm text-down">{error}</p>}
      {plan ? (
        <Suspense key={`${get("p")}-${get("plan")}-${chart}`} fallback={<div className="py-16 text-center text-sm text-ink-2">Simulating {plan.codes.join(", ")}…</div>}>
          <Result plan={plan} chart={chart} />
        </Suspense>
      ) : (
        <Empty>
          Pick a stock, set the rules, and run. Or start from a saved plan:{" "}
          {lab.plans.filter((s) => s.plan).map((s, i) => (
            <span key={s.name}>
              {i > 0 && " · "}
              <Link className="underline" href={`/lab?plan=${s.name}`} title={s.description}>{s.name}</Link>
            </span>
          ))}
          . Conditions use columns like <code>close</code>, <code>sma_50</code>, <code>rsi_14</code>, <code>high_20</code> (previous 20 days&apos; highest close) and <code>vol_x_20</code>.
        </Empty>
      )}
    </>
  );
}
