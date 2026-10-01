import Link from "next/link";
import { StockCodesDatalist, StockSearch } from "@/components/Controls";
import { Table, Td, Th } from "@/components/Table";
import { Badge, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { bn, num, pct, signClass } from "@/lib/format";
import type { Meta, StockRow } from "@/lib/types";

export const metadata = { title: "Stocks" };

export default async function StocksPage() {
  const [meta, rows] = await Promise.all([api<Meta>("/api/meta"), api<StockRow[]>("/api/stocks")]);
  const profiles = meta.profiles.map((p) => p.name);
  return (
    <>
      <PageTitle title="Stocks" subtitle={`${rows.length} stocks in the universe · latest close ${rows[0]?.date ?? "–"}`}>
        <StockSearch codes={meta.universe} />
        <StockCodesDatalist codes={meta.universe} />
      </PageTitle>
      <Table>
        <thead>
          <tr>
            <Th>Code</Th>
            <Th>Name</Th>
            <Th>Sector</Th>
            <Th right>Close</Th>
            <Th right>Chg</Th>
            <Th right>Mcap</Th>
            <Th right title="Trailing P/E">P/E</Th>
            <Th right>Yield</Th>
            <Th right title="Consecutive years with a dividend">Div streak</Th>
            <Th right title="Sponsor + government holding">Strategic</Th>
            <Th right title="Change in institutional holding over stored snapshots">Inst. chg</Th>
            {profiles.map((p) => (
              <Th key={p}>{p}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code} className="hover:bg-surface-2">
              <Td>
                <Link href={`/stocks/${encodeURIComponent(r.code)}`} className="font-medium hover:text-accent">
                  {r.code}
                </Link>
              </Td>
              <Td className="max-w-56 truncate text-ink-2">{r.name}</Td>
              <Td className="text-ink-2">{r.sector}</Td>
              <Td right>{num(r.close)}</Td>
              <Td right className={signClass(r.change_pct)}>{pct(r.change_pct)}</Td>
              <Td right>{bn(r.market_cap_mn)}</Td>
              <Td right>{num(r.pe)}</Td>
              <Td right>{pct(r.dividend_yield, 1, false)}</Td>
              <Td right>{r.dividend_streak ?? "–"}</Td>
              <Td right>{pct(r.strategic_pct, 1, false)}</Td>
              <Td right className={signClass(r.institute_change_pp)}>{num(r.institute_change_pp)}</Td>
              {profiles.map((p) => (
                <Td key={p}>{r[`pass_${p}`] ? <Badge tone="good">✓ pass</Badge> : <Badge tone="bad">✗</Badge>}</Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}
