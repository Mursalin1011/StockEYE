import Link from "next/link";
import type { Pick } from "@/lib/types";
import { StrategyChip } from "./ui";

/** Reasons come as "Quiet accumulation (72): a; b; c" blocks plus "+10 ..." / "Note: ..." extras. */
function splitReasons(reasons: string[]) {
  const blocks: { head: string; lines: string[] }[] = [];
  const extras: string[] = [];
  let tech: string | null = null;
  for (const r of reasons) {
    if (r.startsWith("Tech: ")) {
      tech = r.slice(6);
      continue;
    }
    const i = r.indexOf("): ");
    if (/^[+-]\d/.test(r) || r.startsWith("Note:") || i < 0) extras.push(r);
    else blocks.push({ head: r.slice(0, i + 1), lines: r.slice(i + 3).split("; ") });
  }
  return { blocks, extras, tech };
}

export function PickCard({ pick, profile, strategies }: { pick: Pick; profile: string; strategies: Record<string, string> }) {
  const { blocks, extras, tech } = splitReasons(pick.reasons);
  return (
    <article className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted tabular">#{pick.rank}</span>
        <Link href={`/stocks/${encodeURIComponent(pick.code)}?profile=${profile}`} className="text-lg font-semibold hover:text-accent">
          {pick.code}
        </Link>
        <span className="rounded-md bg-surface-2 px-2 py-0.5 text-sm font-medium tabular" title="Final score: best strategy score x weight, plus confluence and boosts">
          score {Math.round(pick.final_score)}
        </span>
        <div className="flex flex-wrap gap-1.5">
          {pick.strategies.map((s) => (
            <StrategyChip key={s} name={s} title={strategies[s] ?? s} />
          ))}
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {blocks.map((b) => (
          <div key={b.head}>
            <div className="text-sm font-medium">{b.head}</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-2">
              {b.lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {extras.length > 0 && <div className="mt-3 text-sm text-ink-2">{extras.join(" · ")}</div>}
      {tech && <div className="mt-1 text-sm text-ink-2">📈 {tech}</div>}
      {pick.news.length > 0 && (
        <ul className="mt-3 space-y-0.5 border-t border-line pt-2 text-sm text-ink-2">
          {pick.news.map((n) => (
            <li key={n}>📰 {n}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
