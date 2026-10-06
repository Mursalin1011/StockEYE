import Link from "next/link";
import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface p-4 ${className}`}>{children}</section>;
}

export function PageTitle({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-0.5 truncate text-xl font-semibold">{value}</div>
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "bad" }) {
  const cls =
    tone === "good" ? "bg-[color-mix(in_srgb,var(--up)_14%,transparent)] text-up"
    : tone === "bad" ? "bg-[color-mix(in_srgb,var(--down)_14%,transparent)] text-down"
    : "bg-surface-2 text-ink-2";
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

/** Tabs as links (?param=value) so the selection is shareable and server-rendered. */
export function LinkTabs({ items, active, hrefFor }: { items: { value: string; label: string }[]; active: string; hrefFor: (v: string) => string }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
      {items.map((it) => (
        <Link
          key={it.value}
          href={hrefFor(it.value)}
          className={`rounded-md px-3 py-1 ${it.value === active ? "bg-surface-2 font-medium" : "text-ink-2 hover:text-ink"}`}
        >
          {it.label}
        </Link>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-2">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="font-medium text-down">Couldn&apos;t load data</div>
      <div className="mt-1 text-ink-2">{msg}</div>
    </div>
  );
}

/** Strategy legend chip: color + shape, so identity never relies on color alone. */
export const STRATEGY_STYLE: Record<string, { color: string; shape: string }> = {
  quiet_accumulation: { color: "var(--s1)", shape: "●" },
  base_breakout: { color: "var(--s2)", shape: "▲" },
  big_hands: { color: "var(--s3)", shape: "■" },
  second_breakout: { color: "var(--s2)", shape: "▲▲" },
  ma_cross: { color: "var(--s3)", shape: "✕" },
};

export function StrategyChip({ name, title }: { name: string; title: string }) {
  const st = STRATEGY_STYLE[name] ?? { color: "var(--muted)", shape: "●" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
      <span style={{ color: st.color }} aria-hidden>
        {st.shape}
      </span>
      {title}
    </span>
  );
}
