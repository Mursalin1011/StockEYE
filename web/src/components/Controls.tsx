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

export function StockCodesDatalist({ codes }: { codes: string[] }) {
  return (
    <datalist id="stock-codes">
      {codes.map((c) => (
        <option key={c} value={c} />
      ))}
    </datalist>
  );
}
