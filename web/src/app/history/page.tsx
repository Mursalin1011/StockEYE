import Link from "next/link";
import { Table, Td, Th } from "@/components/Table";
import { Empty, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import type { HistoryRow, Meta } from "@/lib/types";

export const metadata = { title: "History" };

export default async function HistoryPage() {
  const [meta, rows] = await Promise.all([api<Meta>("/api/meta"), api<HistoryRow[]>("/api/history")]);
  const profiles = meta.profiles.map((p) => p.name);
  const byDate = new Map<string, Record<string, HistoryRow[]>>();
  for (const r of rows) {
    const d = byDate.get(r.as_of) ?? {};
    (d[r.profile] ??= []).push(r);
    byDate.set(r.as_of, d);
  }
  return (
    <>
      <PageTitle title="History" subtitle="Latest saved screen per day. The Backtest page shows what happened after picks like these." />
      {byDate.size === 0 ? (
        <Empty>No saved screens yet.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Date</Th>
              {profiles.map((p) => (
                <Th key={p}>{p}</Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...byDate.entries()].map(([d, byProfile]) => (
              <tr key={d}>
                <Td>
                  <Link href={`/?date=${d}`} className="hover:text-accent">{day(d)}</Link>
                </Td>
                {profiles.map((p) => (
                  <Td key={p} className="whitespace-normal">
                    {(byProfile[p] ?? []).map((r) => (
                      <Link key={r.code} href={`/stocks/${encodeURIComponent(r.code)}?profile=${p}`} className="mr-3 hover:text-accent">
                        {r.code} <span className="text-muted">({Math.round(r.final_score)})</span>
                      </Link>
                    ))}
                    {!byProfile[p]?.length && <span className="text-muted">–</span>}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </>
  );
}
