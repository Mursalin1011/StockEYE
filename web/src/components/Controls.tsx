"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

export function DateSelect({ dates, value }: { dates: string[]; value: string }) {
  const router = useRouter();
  return (
    <select
      aria-label="Screen date"
      className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
      value={value}
      onChange={(e) => router.push(`/?date=${e.target.value}`)}
    >
      {dates.map((d) => (
        <option key={d} value={d}>
          {new Date(`${d}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}
        </option>
      ))}
    </select>
  );
}

export function RunScreenButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex items-center gap-2">
      <button
        className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
        disabled={pending}
        title="Screen all profiles on the latest stored day and save the result"
        onClick={() =>
          start(async () => {
            setError(null);
            const res = await fetch("/api/screens/run", { method: "POST" });
            if (!res.ok) setError(`Failed (HTTP ${res.status})`);
            router.push("/");
            router.refresh();
          })
        }
      >
        {pending ? "Screening…" : "Run screen now"}
      </button>
      {error && <span className="text-xs text-down">{error}</span>}
    </div>
  );
}

export function StockSearch({ codes }: { codes: string[] }) {
  const router = useRouter();
  return (
    <input
      list="stock-codes"
      placeholder="Go to stock…"
      aria-label="Go to stock"
      className="w-40 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
      onChange={(e) => {
        const v = e.target.value.toUpperCase();
        if (codes.includes(v)) router.push(`/stocks/${encodeURIComponent(v)}`);
      }}
    />
  );
}

/** Case study form: stock + period. Navigates to /casestudy?code=&from=&to= (keeps the profile). */
export function CaseStudyForm({ code, from, to, profile }: { code: string; from: string; to: string; profile: string }) {
  const router = useRouter();
  const field = "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm";
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        const q = new URLSearchParams({ profile });
        const c = String(f.get("code") ?? "").trim().toUpperCase();
        if (!c) return;
        q.set("code", c);
        if (f.get("from")) q.set("from", String(f.get("from")));
        if (f.get("to")) q.set("to", String(f.get("to")));
        router.push(`/casestudy?${q}`);
      }}
    >
      <label className="text-xs text-muted">
        Stock
        <input name="code" list="stock-codes" defaultValue={code} placeholder="e.g. PTL" required className={`${field} mt-1 block w-32 uppercase`} />
      </label>
      <label className="text-xs text-muted">
        From
        <input name="from" type="date" defaultValue={from} className={`${field} mt-1 block`} />
      </label>
      <label className="text-xs text-muted">
        To
        <input name="to" type="date" defaultValue={to} className={`${field} mt-1 block`} />
      </label>
      <button type="submit" className="rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium hover:bg-surface">
        Analyse
      </button>
    </form>
  );
}

export function StockCodesDatalist({ codes }: { codes: string[] }) {
  return (
    <datalist id="stock-codes">
      {codes.map((c) => (
        <option key={c} value={c} />
      ))}
    </datalist>
  );
}

/** A select that navigates: picks `param` in the current query (e.g. the trade lab's chart stock). */
export function ParamSelect({ label, options, value, query, param }: {
  label: string; options: { value: string; label: string }[]; value: string; query: string; param: string;
}) {
  const router = useRouter();
  return (
    <select
      aria-label={label}
      className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
      value={value}
      onChange={(e) => {
        const q = new URLSearchParams(query);
        q.set(param, e.target.value);
        router.push(`?${q}`, { scroll: false });
      }}
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
