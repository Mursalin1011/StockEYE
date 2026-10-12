"use client";

// Holdings page controls. Entries go through the same parser and checks as the Telegram bot
// (POST /api/holdings/trades builds the command text), so both always agree.
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

const field = "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm";
const button = "rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium hover:bg-surface disabled:opacity-60";
const primary = "rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60";

type Action = "buy" | "sell" | "stop";
const ACTIONS: { value: Action; label: string; submit: string }[] = [
  { value: "buy", label: "Bought", submit: "Add buy" },
  { value: "sell", label: "Sold", submit: "Add sell" },
  { value: "stop", label: "Stop", submit: "Set stop" },
];

async function errorText(res: Response) {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

const numOrNull = (v: FormDataEntryValue | null) => (v === null || String(v).trim() === "" ? null : Number(v));

export function TradeForm({ codes, openCodes, lastClose, today, defaultStopPct, initial }: {
  codes: string[];
  openCodes: string[];
  lastClose: Record<string, number>;
  today: string;
  defaultStopPct: number;
  initial?: { action?: Action; code?: string };
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [action, setAction] = useState<Action>(initial?.action ?? "buy");
  const [code, setCode] = useState(initial?.code ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const upper = code.trim().toUpperCase();
  const close = lastClose[upper];
  const list = action === "buy" ? "holding-codes-all" : "holding-codes-open";

  return (
    <form
      id="add"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const f = new FormData(form);
        start(async () => {
          setMsg(null);
          const res = await fetch("/api/holdings/trades", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action,
              code: upper,
              price: numOrNull(f.get("price")),
              qty: action === "stop" ? null : numOrNull(f.get("qty")),
              date: action === "stop" ? null : String(f.get("date") || "") || null,
              stop: action === "buy" ? numOrNull(f.get("stop")) : null,
            }),
          });
          if (!res.ok) return setMsg({ ok: false, text: await errorText(res) });
          setMsg({ ok: true, text: (await res.json()).reply });
          form.reset();
          setCode("");
          router.refresh();
        });
      }}
    >
      <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm" role="radiogroup" aria-label="Entry type">
        {ACTIONS.map((a) => (
          <button
            key={a.value}
            type="button"
            role="radio"
            aria-checked={action === a.value}
            onClick={() => setAction(a.value)}
            className={`rounded-md px-3 py-1 ${action === a.value ? "bg-surface-2 font-medium" : "text-ink-2 hover:text-ink"}`}
          >
            {a.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-muted">
          Stock
          <input
            required
            list={list}
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="PTL"
            autoComplete="off"
            className={`${field} mt-1 block w-32 uppercase`}
          />
        </label>
        <label className="text-xs text-muted">
          {action === "stop" ? "Stop price" : "Price"}
          <input
            name="price"
            type="number"
            step="any"
            min="0"
            required={action !== "stop"}
            placeholder={action === "stop" ? `empty = ${defaultStopPct}% below cost` : close ? `last ${close}` : ""}
            className={`${field} mt-1 block w-40`}
          />
        </label>
        {action !== "stop" && (
          <>
            <label className="text-xs text-muted" title="Optional. Without it only % P/L is shown; a sell without shares closes the whole position.">
              Shares
              <input name="qty" type="number" step="1" min="1" placeholder={action === "sell" ? "all" : "optional"} className={`${field} mt-1 block w-28`} />
            </label>
            <label className="text-xs text-muted">
              Date
              <input name="date" type="date" defaultValue={today} max={today} className={`${field} mt-1 block`} />
            </label>
          </>
        )}
        {action === "buy" && (
          <label className="text-xs text-muted" title={`Optional. Default: ${defaultStopPct}% below your average cost`}>
            Stop
            <input name="stop" type="number" step="any" min="0" placeholder={`default −${defaultStopPct}%`} className={`${field} mt-1 block w-32`} />
          </label>
        )}
        <button type="submit" disabled={pending} className={primary}>
          {pending ? "Saving…" : ACTIONS.find((a) => a.value === action)!.submit}
        </button>
      </div>
      {upper && close !== undefined && <p className="text-xs text-muted">{upper} last close: {close}</p>}
      {msg && <p className={`whitespace-pre-line text-sm ${msg.ok ? "text-ink" : "text-down"}`}>{msg.text}</p>}

      <datalist id="holding-codes-all">
        {codes.map((c) => <option key={c} value={c} />)}
      </datalist>
      <datalist id="holding-codes-open">
        {openCodes.map((c) => <option key={c} value={c} />)}
      </datalist>
    </form>
  );
}

export function UndoButton({ disabled }: { disabled: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      <button
        className={button}
        disabled={disabled || pending}
        title="Remove the latest entry (from here, Telegram or the command line)"
        onClick={() =>
          start(async () => {
            const res = await fetch("/api/holdings/undo", { method: "POST" });
            setMsg(res.ok ? (await res.json()).reply : await errorText(res));
            router.refresh();
          })
        }
      >
        {pending ? "Undoing…" : "Undo last entry"}
      </button>
      {msg && <span className="text-xs text-ink-2">{msg}</span>}
    </span>
  );
}

export function DeleteEntryButton({ id, what }: { id: number; what: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button
      aria-label={`Delete entry ${what}`}
      title="Delete this entry"
      disabled={pending}
      className="px-1.5 text-ink-2 hover:text-down disabled:opacity-50"
      onClick={() => {
        if (!confirm(`Delete this entry?\n${what}\n\nPositions are recalculated from the remaining entries.`)) return;
        start(async () => {
          const res = await fetch(`/api/holdings/trades/${id}`, { method: "DELETE" });
          if (!res.ok) alert(await errorText(res));
          router.refresh();
        });
      }}
    >
      {pending ? "…" : "×"}
    </button>
  );
}
