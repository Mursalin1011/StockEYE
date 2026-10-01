import Link from "next/link";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, LinkTabs, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import type { Meta, QualityView } from "@/lib/types";

export const metadata = { title: "Quality" };

const COLS: { key: string; label: string; digits?: number; text?: boolean }[] = [
  { key: "category", label: "Cat", text: true },
  { key: "sector", label: "Sector", text: true },
  { key: "market_cap_mn", label: "Mcap (mn)", digits: 0 },
  { key: "dividend_streak", label: "Div streak", digits: 0 },
  { key: "cash_dividend_years_5", label: "Cash 5y", digits: 0 },
  { key: "eps_positive_years_5", label: "EPS+ 5y", digits: 0 },
  { key: "eps_cagr_3y", label: "EPS 3y %" },
  { key: "pe", label: "P/E" },
  { key: "p_nav", label: "P/NAV", digits: 2 },
  { key: "dividend_yield", label: "Yield %" },
  { key: "strategic_pct", label: "Strategic %" },
  { key: "institute_change_pp", label: "Inst. chg" },
];

function ruleText(r: QualityView["rules"][string]) {
  const parts = [];
  if (r.in) parts.push(`in ${r.in.join(", ")}`);
  if (r.not_in) parts.push(`not ${r.not_in.join(", ")}`);
  if (r.min !== undefined) parts.push(`≥ ${r.min}`);
  if (r.max !== undefined) parts.push(`≤ ${r.max}`);
  return parts.join(", ");
}

export default async function QualityPage(props: PageProps<"/quality">) {
  const sp = await props.searchParams;
  const profile = typeof sp.profile === "string" ? sp.profile : "swing";
  const [meta, q] = await Promise.all([api<Meta>("/api/meta"), api<QualityView>(`/api/quality/${profile}`)]);
  const passed = q.rows.filter((r) => r.passed).length;
  return (
    <>
      <PageTitle title="Quality filter" subtitle={`${passed}/${q.rows.length} pass the ${profile} profile's “good business” rules`}>
        <LinkTabs items={meta.profiles.map((p) => ({ value: p.name, label: p.name }))} active={profile} hrefFor={(v) => `/quality?profile=${v}`} />
      </PageTitle>
      <Card className="mb-4">
        <div className="text-sm font-medium">Rules (config/profiles/{profile}.yaml → filters.quality.rules)</div>
        <ul className="mt-2 grid gap-1 text-sm text-ink-2 sm:grid-cols-2">
          {Object.entries(q.rules).map(([k, r]) => (
            <li key={k}>
              <code className="rounded bg-surface-2 px-1">{k}</code> {ruleText(r)}{" "}
              <span className="text-muted">· {q.metrics[k] ?? ""}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Table>
        <thead>
          <tr>
            <Th>Code</Th>
            <Th>Result</Th>
            {COLS.map((c) => (
              <Th key={c.key} right={!c.text} title={q.metrics[c.key]}>{c.label}</Th>
            ))}
            <Th>Why not</Th>
          </tr>
        </thead>
        <tbody>
          {q.rows.map((r) => (
            <tr key={r.code} className="hover:bg-surface-2">
              <Td><Link href={`/stocks/${encodeURIComponent(r.code)}?profile=${profile}`} className="font-medium hover:text-accent">{r.code}</Link></Td>
              <Td>{r.passed ? <Badge tone="good">✓ pass</Badge> : <Badge tone="bad">✗ fail</Badge>}</Td>
              {COLS.map((c) => (
                <Td key={c.key} right={!c.text} className={c.text ? "text-ink-2" : ""}>
                  {c.text ? String(r[c.key] ?? "–") : num(r[c.key] as number | null, c.digits ?? 1)}
                </Td>
              ))}
              <Td className="whitespace-normal text-xs text-down">{r.failures.join("; ")}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}
