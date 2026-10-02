"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

const field = "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm";
const button = "rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium hover:bg-surface disabled:opacity-60";

async function errorText(res: Response) {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

/** Add a research PDF by link (https). */
export function AddLinkForm({ types }: { types: string[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const f = new FormData(form);
        start(async () => {
          setMsg(null);
          const res = await fetch("/api/research/docs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: String(f.get("url") ?? ""), doc_type: String(f.get("doc_type") ?? "") || null }),
          });
          if (!res.ok) return setMsg({ ok: false, text: await errorText(res) });
          const d = await res.json();
          setMsg({ ok: true, text: `${d.created ? "Added" : "Already stored"}: #${d.doc_id} ${d.doc_type}, ${d.published}, ${d.codes.length} stocks mentioned` });
          form.reset();
          router.refresh();
        });
      }}
    >
      <label className="min-w-0 flex-1 text-xs text-muted">
        PDF link
        <input name="url" type="url" required placeholder="https://…/SSL-Newsflash-October-2-2026-….pdf" className={`${field} mt-1 block w-full`} />
      </label>
      <label className="text-xs text-muted">
        Type
        <select name="doc_type" defaultValue="" className={`${field} mt-1 block`}>
          <option value="">Auto (sources.yaml)</option>
          {types.map((t) => (
            <option key={t} value={t}>{t.replace("_", " ")}</option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={pending} className={button}>{pending ? "Downloading…" : "Add"}</button>
      {msg && <p className={`w-full text-xs ${msg.ok ? "text-up" : "text-down"}`}>{msg.text}</p>}
    </form>
  );
}

export function ImportInboxButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      <button
        className={button}
        disabled={pending}
        onClick={() =>
          start(async () => {
            const res = await fetch("/api/research/inbox", { method: "POST" });
            if (!res.ok) return setMsg(await errorText(res));
            const d: { created: boolean }[] = await res.json();
            setMsg(`${d.filter((x) => x.created).length} new, ${d.filter((x) => !x.created).length} already stored`);
            router.refresh();
          })
        }
      >
        {pending ? "Importing…" : "Import inbox folder"}
      </button>
      {msg && <span className="text-xs text-ink-2">{msg}</span>}
    </span>
  );
}

/** Starts a background review and polls until it finishes (1-3 minutes). */
export function RunReviewButton({ disabled, runningJob }: { disabled: boolean; runningJob?: string }) {
  const router = useRouter();
  const [job, setJob] = useState<string | null>(runningJob ?? null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!job) return;
    const t0 = Date.now();
    const timer = setInterval(async () => {
      setElapsed(Math.round((Date.now() - t0) / 1000));
      const res = await fetch(`/api/research/jobs/${job}`);
      if (!res.ok) return;
      const d = await res.json();
      if (d.status === "done") {
        clearInterval(timer);
        setJob(null);
        router.push(`/research?review=${d.review_id}`);
        router.refresh();
      } else if (d.status === "error") {
        clearInterval(timer);
        setJob(null);
        setError(d.error);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [job, router]);

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button
        className={`${button} border-accent`}
        disabled={disabled || !!job}
        onClick={async () => {
          setError(null);
          const res = await fetch("/api/research/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          if (!res.ok) return setError(await errorText(res));
          setJob((await res.json()).job_id);
        }}
      >
        {job ? `Reviewing… ${elapsed}s` : "Run AI review"}
      </button>
      {error && <span className="text-xs text-down">{error}</span>}
    </span>
  );
}
