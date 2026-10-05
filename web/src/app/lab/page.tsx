import Link from "next/link";
import { Suspense } from "react";
import { ParamSelect, StockCodesDatalist } from "@/components/Controls";
import { EquityChart } from "@/components/EquityChart";
import { LabForm, type Grid } from "@/components/LabForm";
import { StockChart } from "@/components/StockChart";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, Empty, LinkTabs, PageTitle, Stat } from "@/components/ui";
import { ApiError, api, apiPost } from "@/lib/api";
import { int, num, pct, signClass } from "@/lib/format";
import type { LabMeta, LabResultView, LabStock, LabSummaryRow, LabTrade, Meta, PlanJson, SweepRow, SweepView } from "@/lib/types";

export const metadata = { title: "Trade lab" };

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const MAX_STOCK_ROWS = 25;
const MAX_TRADE_ROWS = 300;

function Ret({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  return <span className={`${signClass(v ?? null)} ${className}`}>{pct(v ?? null)}</span>;
}

function Money({ v }: { v: number | null | undefined }) {
  return <span className={signClass(v ?? null)}>{v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${int(v)}`}</span>;
}

/** Fill in anything a hand-edited ?p= plan left out, so the form always has every field. */
function withDefaults(d: PlanJson, p: Partial<PlanJson>): PlanJson {
  return {
    ...d, ...p,
    // the default plan's starter condition is for the empty form only: a link without conditions has none
    entry: { ...d.entry, when: [], dates: [], ...p.entry }, exit: { ...d.exit, when_any: [], ...p.exit }, hold: { ...d.hold, ...p.hold },
    costs: { ...d.costs, ...p.costs }, capital: { ...d.capital, ...p.capital }, liquidity: { ...d.liquidity, ...p.liquidity },
  };
}

/** plan with data[path] = value, e.g. exit.stop_pct or entry.when.1.2 (numbers index lists). */
function withValue(plan: PlanJson, path: string, value: unknown): PlanJson {
  const out = structuredClone(plan) as unknown as Record<string, unknown>;
  const keys = path.split(".");
  let node: Record<string, unknown> | unknown[] = out;
  for (const k of keys.slice(0, -1)) {
    const cur = node as Record<string, unknown>;
    if (cur[k] === null || cur[k] === undefined) cur[k] = {};
    node = cur[k] as Record<string, unknown>;
  }
  (node as Record<string, unknown>)[keys.at(-1)!] = value;
  return out as unknown as PlanJson;
}

function PlanError({ message }: { message: string }) {
  return (
    <Card>
      <div className="text-sm font-medium text-down">Check the plan</div>
      <pre className="mt-1 text-sm whitespace-pre-wrap text-ink-2">{message}</pre>
    </Card>
  );
}

function StockTable({ rows, basket, shared }: { rows: LabStock[]; basket: string | null; shared: boolean }) {
  const shown = rows.length > MAX_STOCK_ROWS ? rows.filter((s) => s.trades > 0).slice(0, MAX_STOCK_ROWS) : rows;
  return (
    <>
      <Table>
        <thead>
          <tr>
            <Th>Stock</Th>
            <Th>Window</Th>
            <Th right>Trades</Th>
            <Th right title="Money made or lost on this stock's trades, net of costs">P/L</Th>
            {!shared && <Th right title="Equity growth with the plan's sizing, net of costs">Plan</Th>}
            <Th right title="Bought at the window's first open, held to its last close, less one round trip">Buy &amp; hold</Th>
            {basket && <Th right title={`Equal-weight basket (${basket}) held over the same window`}>Basket held</Th>}
            {!shared && <Th right title="Largest fall of the plan's equity from a high">Plan max DD</Th>}
            <Th right title="Largest fall of the stock's close from a high">Stock max DD</Th>
            <Th right title="Share of days with a position in this stock">In market</Th>
          </tr>
        </thead>
        <tbody>
          {shown.map((s) => (
            <tr key={s.code}>
              <Td className="font-medium">{s.code}</Td>
              <Td className="text-ink-2">{shortDate(s.start)} → {shortDate(s.end)}</Td>
              <Td right>{s.trades}{s.open ? <span className="text-muted"> ({s.open} open)</span> : null}</Td>
              <Td right><Money v={s.pnl} /></Td>
              {!shared && <Td right className="font-medium"><Ret v={s.plan_pct} /></Td>}
              <Td right><Ret v={s.buy_hold_pct} /></Td>
              {basket && <Td right><Ret v={s.basket_hold_pct} /></Td>}
              {!shared && <Td right className="text-down">{pct(s.plan_max_dd_pct)}</Td>}
              <Td right className="text-down">{pct(s.buy_hold_max_dd_pct)}</Td>
              <Td right>{pct(s.in_market_pct, 0, false)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {shown.length < rows.length && (
        <p className="mt-2 text-xs text-muted">
          Showing the {shown.length} stocks with the most trades; {rows.length - shown.length} more ({rows.filter((s) => !s.trades).length} without a trade).
        </p>
      )}
    </>
  );
}

function TradesTable({ rows, multi, basket, shared }: { rows: LabTrade[]; multi: boolean; basket: boolean; shared: boolean }) {
  const adjusted = rows.some((t) => Math.abs(t.entry_actual - t.entry) > 1e-6 || Math.abs(t.exit_actual - t.exit) > 1e-6);
  const shown = rows.slice(-MAX_TRADE_ROWS);
  return (
    <>
      {shown.length < rows.length && <p className="mb-2 text-xs text-muted">The latest {shown.length} of {rows.length} trades.</p>}
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
            {shared && <Th right title="Money put into the trade">Stake</Th>}
            <Th right title="Net of the round-trip cost">Return</Th>
            {basket && <Th right title="Return minus the basket's over the same dates">Vs basket</Th>}
            <Th right title="Highest high / lowest low while held, vs the entry">Best / worst</Th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => (
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
              {shared && <Td right>{int(t.stake)}</Td>}
              <Td right className="font-medium"><Ret v={t.ret_pct} /></Td>
              {basket && <Td right><Ret v={t.excess_pct} /></Td>}
              <Td right><Ret v={t.best_pct} /> / <Ret v={t.worst_pct} /></Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
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
            <Td right className={pfClass(r.profit_factor)}>{num(r.profit_factor)}</Td>
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

const pfClass = (v: number | null | undefined) => (v === null || v === undefined ? "text-ink-2" : v >= 1.5 ? "text-up" : v < 1 ? "text-down" : "");

async function Result({ plan, chart }: { plan: PlanJson; chart: string }) {
  let r: LabResultView;
  try {
    r = await apiPost<LabResultView>("/api/simulate", { plan, chart_code: chart || null });
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) return <PlanError message={e.message} />;
    throw e;
  }
  const all = r.summary.find((s) => s.segment === "all");
  const closed = r.trades.filter((t) => t.why !== "open");
  const multi = r.codes.length > 1;
  const one = r.stocks.length === 1 ? r.stocks[0] : null;
  const pf = r.portfolio;
  const hasBasket = Boolean(r.basket) && r.trades.some((t) => t.basket_pct !== null && t.basket_pct !== undefined);
  const p = JSON.stringify(r.plan);
  const equityKey = pf ? "portfolio" : r.chart_code;
  const points = equityKey ? r.equity[equityKey] ?? [] : [];

  return (
    <div className="space-y-4">
      <Card>
        <ul className="space-y-0.5 text-sm text-ink-2">
          {r.describe.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Trades" value={`${closed.length}${r.trades.length > closed.length ? ` + ${r.trades.length - closed.length} open` : ""}`}
            hint="Closed trades are in the stats; open ones are marked at the window's last close" />
          <Stat label="Win rate" value={pct(all?.win_rate ?? null, 0, false)} />
          <Stat label="Average per trade" value={<Ret v={all?.mean_ret} />} hint={`Median ${pct(all?.median_ret ?? null)}`} />
          <Stat label="Profit factor" value={num(all?.profit_factor ?? null)} hint="Gross wins / gross losses. Above 1 makes money" />
          {pf ? (
            <Stat label="Portfolio vs held" value={<><Ret v={pf.return_pct} /> <span className="text-base font-normal text-ink-2">vs</span> <Ret v={pf.bench_pct} /></>}
              hint={`The pot vs the same money split equally over the ${pf.stocks} stocks and held. Max drawdown ${pct(pf.max_dd_pct)} vs ${pct(pf.bench_max_dd_pct)}`} />
          ) : one ? (
            <Stat label="Plan vs buy & hold" value={<><Ret v={one.plan_pct} /> <span className="text-base font-normal text-ink-2">vs</span> <Ret v={one.buy_hold_pct} /></>}
              hint={`Max drawdown ${pct(one.plan_max_dd_pct)} vs ${pct(one.buy_hold_max_dd_pct)}`} />
          ) : (
            <Stat label="Stocks" value={`${r.stocks.length}`} hint={`${r.stocks.filter((s) => s.trades).length} with trades`} />
          )}
          {hasBasket ? (
            <Stat label="Vs basket, per trade" value={<Ret v={all?.mean_excess} />} hint={`Average of (trade - ${r.basket} over the same dates); beat it ${pct(all?.beat_basket ?? null, 0, false)} of the time`} />
          ) : (
            <Stat label="Max drawdown" value={one?.plan_max_dd_pct != null ? <span className={one.plan_max_dd_pct < 0 ? "text-down" : "text-ink-2"}>{pct(one.plan_max_dd_pct)}</span> : "–"} />
          )}
        </div>
        {pf && (
          <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Portfolio max drawdown" value={<span className="text-down">{pct(pf.max_dd_pct)}</span>} hint={`Held: ${pct(pf.bench_max_dd_pct)}`} />
            <Stat label="End equity" value={int(pf.end_equity)} hint={`Started with ${int(r.plan.capital.start)}`} />
            <Stat label="Average positions" value={`${num(pf.avg_positions)} / ${pf.max_positions}`} hint={`Invested on ${pct(pf.in_market_pct, 0, false)} of days`} />
            <Stat label="Signals skipped" value={int(pf.skipped)} hint="All slots were full (or no cash was left)" />
            {pf.basket_hold_pct != null && <Stat label="Basket held" value={<Ret v={pf.basket_hold_pct} />} hint={`${r.basket}, held over the window`} />}
          </div>
        )}
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

      {points.length > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">{pf ? `Portfolio equity vs the ${pf.stocks} stocks held` : `${equityKey}: equity, plan vs buy & hold`}</h2>
          <EquityChart points={points} start={r.plan.capital.start} labels={pf ? { plan: "Portfolio", hold: "Stocks held" } : undefined} />
          <p className="mt-2 text-xs text-muted">
            {pf
              ? `Shared capital: up to ${pf.max_positions} positions, each 1/${pf.max_positions} of equity; marked at each close, cost charged at each exit. Held: the same money split equally over the stocks at their first open.`
              : `Plan: ${r.plan.capital.per_trade_pct}% of equity per trade, the rest in cash; cost charged at each exit. Buy & hold: the same starting money in the stock from the window's first open.`}
          </p>
        </Card>
      )}

      <Card>
        <h2 className="mb-2 font-semibold">Per stock</h2>
        {r.stocks.length ? <StockTable rows={r.stocks} basket={hasBasket ? r.basket : null} shared={Boolean(pf)} /> : <Empty>No prices for these stocks in the window.</Empty>}
      </Card>

      {r.chart && r.chart_code && (
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">{r.chart_code}: trades on the chart</h2>
            {multi && r.stocks.length <= 8 ? (
              <LinkTabs items={r.stocks.map((s) => ({ value: s.code, label: s.code }))} active={r.chart_code}
                hrefFor={(c) => `/lab?${new URLSearchParams({ p, chart: c })}`} />
            ) : multi ? (
              <ParamSelect label="Stock to chart" value={r.chart_code} query={new URLSearchParams({ p }).toString()} param="chart"
                options={r.stocks.map((s) => ({ value: s.code, label: `${s.code}${s.trades ? ` (${s.trades} trades)` : ""}` }))} />
            ) : null}
          </div>
          <StockChart data={r.chart} height={600} />
          <p className="mt-2 text-xs text-muted">
            Prices adjusted for bonus/rights{r.chart.overlays?.length ? "; lines are the price-level columns the plan uses" : ""}. The chart starts 60 trading days before the window.
            Hover a marker&apos;s day for the trade. <Link className="underline" href={`/casestudy?code=${encodeURIComponent(r.chart_code)}`}>Case study →</Link>
          </p>
        </Card>
      )}

      <Card>
        <h2 className="mb-2 font-semibold">Trades</h2>
        {r.trades.length ? <TradesTable rows={r.trades} multi={multi} basket={hasBasket} shared={Boolean(pf)} /> : <Empty>No trades: the entry rule never held in the window (see the notes above).</Empty>}
        {r.trades.some((t) => t.flags) && <p className="mt-2 text-xs text-muted">⚠ = the fill may not have been possible (a day locked at the price limit, or a stake big for the stock&apos;s trading); hover it for details.</p>}
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

/** A cell shaded by the sign and size of a return: up/down hue, stronger for bigger moves, neutral near 0. */
function Heat({ v, max }: { v: number | null | undefined; max: number }) {
  if (v === null || v === undefined) return <td className="border border-line px-3 py-2 text-center text-ink-2">–</td>;
  const share = Math.min(Math.abs(v) / (max || 1), 1);
  const bg = `color-mix(in srgb, var(${v >= 0 ? "--up" : "--down"}) ${Math.round(8 + share * 40)}%, transparent)`;
  return <td className="border border-line px-3 py-2 text-center tabular font-medium" style={{ background: bg }}>{pct(v)}</td>;
}

function HeatTable({ title, rows, a, b, metric }: { title: string; rows: SweepRow[]; a: string; b: string; metric: string }) {
  const order = (x: unknown, y: unknown) => (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y)));
  const va = [...new Set(rows.map((r) => r[a]))].sort(order);
  const vb = [...new Set(rows.map((r) => r[b]))].sort(order);
  const at = (x: unknown, y: unknown) => rows.find((r) => r[a] === x && r[b] === y)?.[metric] as number | null | undefined;
  const max = Math.max(...rows.map((r) => Math.abs((r[metric] as number) ?? 0)));
  return (
    <div className="min-w-0">
      <div className="mb-1 text-sm font-medium">{title}</div>
      <div className="overflow-x-auto">
        <table className="border-collapse text-sm">
          <thead>
            <tr>
              <th className="px-3 py-1 text-left text-xs font-medium text-ink-2">{a} ↓ / {b} →</th>
              {vb.map((y) => <th key={String(y)} className="px-3 py-1 text-xs font-medium text-ink-2">{String(y)}</th>)}
            </tr>
          </thead>
          <tbody>
            {va.map((x) => (
              <tr key={String(x)}>
                <th className="px-3 py-1 text-right text-xs font-medium text-ink-2">{String(x)}</th>
                {vb.map((y) => <Heat key={String(y)} v={at(x, y)} max={max} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

async function SweepResult({ plan, grid }: { plan: PlanJson; grid: Grid }) {
  let r: SweepView;
  try {
    r = await apiPost<SweepView>("/api/sweep", { plan, grid });
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) return <PlanError message={e.message} />;
    throw e;
  }
  const paths = Object.keys(r.grid);
  const key = r.split ? "in_mean" : "all_mean";
  const rows = [...r.rows].sort((x, y) => ((y[key] as number) ?? -Infinity) - ((x[key] as number) ?? -Infinity));
  const segs = r.split ? [["in", "Tuning period"], ["out", "Test period"]] : [["all", "All trades"]];
  const basket = rows.some((x) => x.all_vs_basket !== undefined && x.all_vs_basket !== null);
  const open = (row: SweepRow) => {
    let p2 = r.plan;
    for (const path of paths) p2 = withValue(p2, path, row[path]);
    return `/lab?${new URLSearchParams({ p: JSON.stringify(p2) })}`;
  };

  return (
    <div className="space-y-4">
      <Card>
        <ul className="space-y-0.5 text-sm text-ink-2">
          {r.describe.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <p className="mt-3 text-sm">
          {rows.length} combinations of {paths.join(" × ")} on {r.stocks} stock(s), ranked by the mean return per trade
          {r.split ? " in the tuning period. Choose on the tuning period; the test period is the honest check: a setting that only wins in tuning is curve-fitted." : ". Set a tuning period to split the results into tuning and test."}
        </p>
      </Card>

      {paths.length === 2 && (
        <Card>
          <div className="grid gap-6 md:grid-cols-2">
            {segs.map(([k, label]) => <HeatTable key={k} title={`${label}: mean return per trade`} rows={rows} a={paths[0]} b={paths[1]} metric={`${k}_mean`} />)}
            <HeatTable title={plan.portfolio ? "Portfolio return" : "Average stock's return"} rows={rows} a={paths[0]} b={paths[1]} metric="return_pct" />
          </div>
          <p className="mt-3 text-xs text-muted">Green = made money, red = lost; stronger = bigger. Look for a setting that is green in both periods, with green neighbours (robust), not a single bright cell.</p>
        </Card>
      )}

      <Card>
        <Table>
          <thead>
            <tr>
              {paths.map((pth) => <Th key={pth}>{pth}</Th>)}
              {segs.map(([k, label]) => [
                <Th key={`${k}t`} right title={`${label}: closed trades`}>{label} trades</Th>,
                <Th key={`${k}m`} right title={`${label}: mean return per trade`}>Mean</Th>,
                <Th key={`${k}w`} right>Win</Th>,
                <Th key={`${k}p`} right title="Profit factor">PF</Th>,
                ...(basket ? [<Th key={`${k}b`} right title="Mean of (trade - basket over the same dates)">Vs basket</Th>] : []),
              ])}
              <Th right title={plan.portfolio ? "Portfolio return over the window" : "Average stock's plan return"}>Return</Th>
              <Th right title={plan.portfolio ? "Portfolio max drawdown" : "Worst stock's max drawdown"}>Max DD</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={paths.map((pth) => String(row[pth])).join("|")} className={i === 0 ? "bg-surface-2" : ""}>
                {paths.map((pth) => <Td key={pth} className="font-medium">{String(row[pth])}</Td>)}
                {segs.map(([k]) => [
                  <Td key={`${k}t`} right>{(row[`${k}_trades`] as number) ?? 0}</Td>,
                  <Td key={`${k}m`} right className="font-medium"><Ret v={row[`${k}_mean`] as number | null} /></Td>,
                  <Td key={`${k}w`} right>{pct(row[`${k}_win`] as number | null, 0, false)}</Td>,
                  <Td key={`${k}p`} right className={pfClass(row[`${k}_pf`] as number | null)}>{num(row[`${k}_pf`] as number | null)}</Td>,
                  ...(basket ? [<Td key={`${k}b`} right><Ret v={row[`${k}_vs_basket`] as number | null} /></Td>] : []),
                ])}
                <Td right><Ret v={row.return_pct as number | null} /></Td>
                <Td right className="text-down">{pct(row.max_dd_pct as number | null)}</Td>
                <Td><Link className="text-xs underline" href={open(row)}>Open →</Link></Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-2 text-xs text-muted">Closed trades, net of {plan.costs.round_trip_pct}% round-trip cost. Top row = best in the {r.split ? "tuning period" : "whole window"}. &quot;Open&quot; runs that combination with its trades and charts.</p>
      </Card>
    </div>
  );
}

export default async function LabPage(props: PageProps<"/lab">) {
  const sp = await props.searchParams;
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const [lab, meta] = await Promise.all([api<LabMeta>("/api/lab"), api<Meta>("/api/meta")]);

  let plan: PlanJson | null = null;
  let grid: Grid | null = null;
  let error = "";
  if (get("p")) {
    try {
      plan = withDefaults(lab.default_plan, JSON.parse(get("p")));
      grid = get("grid") ? (JSON.parse(get("grid")) as Grid) : null;
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
  const busy = plan ? (plan.universe ? `every ${plan.universe} stock` : plan.codes.join(", ")) : "";

  return (
    <>
      <PageTitle title="Trade lab" subtitle="Your own entry, exit and hold rules on any stocks and period: every trade, against buy & hold and the basket." />
      <Card className="mb-4">
        <LabForm key={`${get("p") || get("plan")}-${get("grid")}`} meta={lab} initial={initial} codes={meta.universe} initialGrid={grid} />
        <StockCodesDatalist codes={meta.universe} />
      </Card>
      {error && <p className="mb-4 text-sm text-down">{error}</p>}
      {plan && grid ? (
        <Suspense key={`${get("p")}-${get("grid")}`} fallback={<div className="py-16 text-center text-sm text-ink-2">Running every combination on {busy}…</div>}>
          <SweepResult plan={plan} grid={grid} />
        </Suspense>
      ) : plan ? (
        <Suspense key={`${get("p")}-${get("plan")}-${chart}`} fallback={<div className="py-16 text-center text-sm text-ink-2">Simulating {busy}…</div>}>
          <Result plan={plan} chart={chart} />
        </Suspense>
      ) : (
        <Empty>
          Pick a stock (or a universe), set the rules, and run. Or start from a saved plan:{" "}
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
