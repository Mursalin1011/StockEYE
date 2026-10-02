import Link from "next/link";
import { StockChart } from "@/components/StockChart";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, LinkTabs, PageTitle, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { bn, num, pct, signClass } from "@/lib/format";
import type { ChartData, Meta, StockDetail } from "@/lib/types";

const RANGES = [
  { value: "125", label: "6M" },
  { value: "250", label: "1Y" },
  { value: "500", label: "2Y" },
];

export async function generateMetadata(props: PageProps<"/stocks/[code]">) {
  const { code } = await props.params;
  return { title: decodeURIComponent(code) };
}

export default async function StockPage(props: PageProps<"/stocks/[code]">) {
  const { code: raw } = await props.params;
  const sp = await props.searchParams;
  const code = decodeURIComponent(raw);
  const profile = typeof sp.profile === "string" ? sp.profile : "swing";
  const days = typeof sp.days === "string" ? sp.days : "250";

  const [meta, detail, chart] = await Promise.all([
    api<Meta>("/api/meta"),
    api<StockDetail>(`/api/stocks/${encodeURIComponent(code)}`),
    api<ChartData>(`/api/stocks/${encodeURIComponent(code)}/chart?profile=${profile}&days=${days}`),
  ]);
  const c = detail.company;
  const m = detail.metrics;
  const last = chart.bars.at(-1);
  const prev = chart.bars.at(-2);
  const chg = last && prev ? (last.close / prev.close - 1) * 100 : null;
  const href = (o: Record<string, string>) => `/stocks/${encodeURIComponent(code)}?${new URLSearchParams({ profile, days, ...o })}`;

  return (
    <>
      <PageTitle
        title={code}
        subtitle={
          <>
            {String(c.name ?? "")} · {String(c.sector ?? "")} · Category {String(c.category ?? "–")}
          </>
        }
      >
        <div className="text-right">
          <div className="text-2xl font-semibold tabular">{num(last?.close)}</div>
          <div className={`text-sm tabular ${signClass(chg)}`}>{pct(chg, 2)} · {last?.time}</div>
        </div>
      </PageTitle>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm text-ink-2">
            Signals from
            <LinkTabs items={meta.profiles.map((p) => ({ value: p.name, label: p.name }))} active={profile} hrefFor={(v) => href({ profile: v })} />
          </div>
          <div className="flex items-center gap-3">
            <Link className="text-sm underline" href={`/casestudy?${new URLSearchParams({ code, profile })}`}>
              Case study →
            </Link>
            <LinkTabs items={RANGES} active={days} hrefFor={(v) => href({ days: v })} />
          </div>
        </div>
        <StockChart data={chart} />
        <p className="mt-2 text-xs text-muted">
          Prices adjusted for dividends and bonus shares. Markers show the first day of each signal from the {profile} profile&apos;s strategies.
        </p>
      </Card>

      <Card className="mt-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Market cap" value={bn(c.market_cap_mn as number)} />
          <Stat label="P/E (trailing)" value={num(m.pe as number)} />
          <Stat label="Price / NAV" value={num(m.p_nav as number, 2)} />
          <Stat label="Dividend yield" value={pct(m.dividend_yield as number, 1, false)} />
          <Stat label="Dividend streak" value={`${m.dividend_streak ?? "–"} yrs`} />
          <Stat label="EPS growth (3y)" value={pct(m.eps_cagr_3y as number)} hint="Per year, restated EPS" />
          <Stat label="Sponsor + govt" value={pct(m.strategic_pct as number, 1, false)} />
          <Stat label="Institutions" value={<span className={signClass(m.institute_change_pp as number)}>{num(m.institute_change_pp as number)} pts</span>} hint="Change across stored monthly snapshots" />
          <Stat label="Cash dividends (5y)" value={`${m.cash_dividend_years_5 ?? "–"}/5`} />
          <Stat label="Profitable (5y)" value={`${m.eps_positive_years_5 ?? "–"}/5`} />
          <Stat label="Short-term loans" value={bn(c.short_loan_mn as number)} />
          <Stat label="Long-term loans" value={bn(c.long_loan_mn as number)} />
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold">Shareholding (%)</h2>
          <Table>
            <thead>
              <tr><Th>As of</Th><Th right>Sponsor</Th><Th right>Govt</Th><Th right>Institute</Th><Th right>Foreign</Th><Th right>Public</Th></tr>
            </thead>
            <tbody>
              {detail.shareholding.map((s) => (
                <tr key={s.as_of}>
                  <Td>{s.as_of}</Td><Td right>{num(s.sponsor, 2)}</Td><Td right>{num(s.govt, 2)}</Td>
                  <Td right>{num(s.institute, 2)}</Td><Td right>{num(s.foreign_pct, 2)}</Td><Td right>{num(s.public, 2)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>

          <h2 className="mt-5 mb-2 font-semibold">Dividends &amp; bonus (adjustment events)</h2>
          <Table>
            <thead>
              <tr><Th>Record date</Th><Th>Ex-date</Th><Th right>Cash %</Th><Th right>Stock %</Th><Th /></tr>
            </thead>
            <tbody>
              {detail.corporate_actions.map((a) => (
                <tr key={a.record_date}>
                  <Td>{a.record_date}</Td><Td>{a.ex_date ?? "upcoming"}</Td>
                  <Td right>{num(a.cash_pct)}</Td><Td right>{num(a.stock_pct)}</Td>
                  <Td>{a.revised ? <Badge>AGM revised</Badge> : null}</Td>
                </tr>
              ))}
            </tbody>
          </Table>

          <h2 className="mt-5 mb-2 font-semibold">Annual results</h2>
          <Table>
            <thead>
              <tr><Th>Year</Th><Th right>EPS</Th><Th right>NAV</Th><Th right>Profit (mn)</Th><Th right>P/E</Th><Th>Dividend</Th><Th right>Yield</Th></tr>
            </thead>
            <tbody>
              {detail.annual.map((a) => (
                <tr key={a.year}>
                  <Td>{a.year}</Td><Td right>{num(a.eps, 2)}</Td><Td right>{num(a.nav, 2)}</Td><Td right>{num(a.profit_mn, 0)}</Td>
                  <Td right>{num(a.pe)}</Td><Td>{a.dividend_text ?? "–"}</Td><Td right>{pct(a.dividend_yield, 1, false)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>

        <Card>
          <h2 className="mb-2 font-semibold">News</h2>
          <ul className="max-h-[52rem] space-y-3 overflow-y-auto pr-1">
            {detail.news.map((n, i) => (
              <li key={`${n.post_date}-${i}`} className="border-b border-line pb-3 last:border-0">
                <div className="text-xs text-muted">{n.post_date}</div>
                <div className="text-sm font-medium">{n.title.split(": ").slice(1).join(": ") || n.title}</div>
                <p className="mt-0.5 text-sm text-ink-2">{n.body}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
