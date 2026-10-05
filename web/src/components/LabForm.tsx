"use client";

// Trade lab form: builds a TradePlan (docs/06-trade-lab-plan.md) and puts it in the URL (?p=<json>, plus
// ?grid=<json> for a parameter grid), so a result is shareable and the server page runs it. Lists (stocks, conditions, buy dates) are
// state; number fields are read from the form on submit. Saving writes config/plans/<name>.yaml.
import { useRouter } from "next/navigation";
import { useState, useTransition, type ReactNode } from "react";
import type { Condition, LabMeta, PlanJson } from "@/lib/types";

const field = "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm";
const button = "rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium hover:bg-surface disabled:opacity-60";
const primary = "rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60";

type Row = [string, string, string];
type GridRow = [string, string];
export type Grid = Record<string, (number | string)[]>;

const GRID_PATHS: [string, string][] = [
  ["exit.stop_pct", "Stop loss %"], ["exit.target_pct", "Target %"], ["exit.trail_pct", "Trailing stop %"],
  ["exit.trail_ma", "Close below MA"], ["exit.max_days", "Time limit (days)"], ["hold.min_days", "Can sell after (days)"],
  ["hold.cooldown_days", "Wait after exit (days)"], ["portfolio.max_positions", "Max positions (shared capital)"],
];
const parseValue = (v: string): number | string => (/^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v);
const toRows = (c: Condition[]): Row[] => c.map(([l, o, r]) => [l, o, String(r)]);
const opLabel = (op: string) => op.replace("_", " ");

function Label({ text, hint, children, className = "" }: { text: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`block text-xs text-muted ${className}`} title={hint}>
      {text}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function NumField({ name, label, value, hint, step = "any", placeholder = "off" }: {
  name: string; label: string; value: number | null; hint?: string; step?: string; placeholder?: string;
}) {
  return (
    <Label text={label} hint={hint}>
      <input name={name} type="number" step={step} min="0" defaultValue={value ?? ""} placeholder={placeholder} className={`${field} w-full`} />
    </Label>
  );
}

function Conditions({ rows, onChange, operators, fresh, emptyText }: {
  rows: Row[]; onChange: (r: Row[]) => void; operators: string[]; fresh: Row; emptyText: string;
}) {
  const set = (i: number, k: number, v: string) => onChange(rows.map((r, j) => (j === i ? (r.map((x, m) => (m === k ? v : x)) as Row) : r)));
  return (
    <div className="space-y-1.5">
      {rows.length === 0 && <p className="text-xs text-muted">{emptyText}</p>}
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-1">
          <input aria-label="Column" list="lab-columns" value={r[0]} onChange={(e) => set(i, 0, e.target.value.trim())} className={`${field} w-24 min-w-0 flex-1`} />
          <select aria-label="Operator" value={r[1]} onChange={(e) => set(i, 1, e.target.value)} className={`${field} w-28 px-1.5`}>
            {operators.map((o) => <option key={o} value={o}>{opLabel(o)}</option>)}
          </select>
          <input aria-label="Value or column" list="lab-columns" value={r[2]} onChange={(e) => set(i, 2, e.target.value.trim())} className={`${field} w-24 min-w-0 flex-1`} />
          <button type="button" aria-label="Remove condition" title="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))} className="px-1.5 text-ink-2 hover:text-down">×</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...rows, fresh])} className="text-xs text-accent hover:underline">+ Add condition</button>
    </div>
  );
}

function Chips({ items, onRemove }: { items: string[]; onRemove: (v: string) => void }) {
  return (
    <>
      {items.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-2 py-0.5 text-xs font-medium">
          {v}
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onRemove(v)} className="text-ink-2 hover:text-down">×</button>
        </span>
      ))}
    </>
  );
}

export function LabForm({ meta, initial, codes: universe, initialGrid }: {
  meta: LabMeta; initial: PlanJson; codes: string[]; initialGrid?: Grid | null;
}) {
  const router = useRouter();
  const [base, setBase] = useState(initial);
  const [version, setVersion] = useState(0);           // remounts the uncontrolled fields when a plan is loaded
  const [codes, setCodes] = useState(initial.codes);
  const [codeDraft, setCodeDraft] = useState("");
  const [mode, setMode] = useState<"rules" | "dates">(initial.entry.dates.length ? "dates" : "rules");
  const [strategy, setStrategy] = useState(initial.entry.strategy ?? "");
  const [when, setWhen] = useState(toRows(initial.entry.when));
  const [whenAny, setWhenAny] = useState(toRows(initial.exit.when_any));
  const [dates, setDates] = useState(initial.entry.dates);
  const [dateDraft, setDateDraft] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [uni, setUni] = useState(initial.universe ?? "");
  const [shared, setShared] = useState(initial.portfolio !== null);
  const toGrid = (g?: Grid | null): GridRow[] => {
    const rows: GridRow[] = Object.entries(g ?? {}).map(([k, v]) => [k, v.join(", ")]);
    while (rows.length < 2) rows.push(["", ""]);
    return rows;
  };
  const [grid, setGrid] = useState<GridRow[]>(toGrid(initialGrid));
  const [pending, start] = useTransition();

  const addCode = (raw: string) => {
    const add = raw.split(/[\s,]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
    if (add.length) setCodes((cur) => [...cur, ...add.filter((c) => !cur.includes(c))]);
    setCodeDraft("");
  };

  const load = (name: string) => {
    const saved = meta.plans.find((p) => p.name === name)?.plan;
    if (!saved) return;
    // Take the plan's rules; keep the stocks and dates already picked
    const next = { ...saved, codes: codes.length ? codes : saved.codes, from: base.from ?? saved.from, to: base.to ?? saved.to };
    setBase(next);
    setCodes(next.codes);
    setMode(saved.entry.dates.length ? "dates" : "rules");
    setStrategy(saved.entry.strategy ?? "");
    setWhen(toRows(saved.entry.when));
    setWhenAny(toRows(saved.exit.when_any));
    setDates(saved.entry.dates);
    setUni(saved.universe ?? uni);
    setShared(saved.portfolio !== null);
    setVersion((v) => v + 1);
    setMsg(null);
  };

  const build = (form: HTMLFormElement): PlanJson | null => {
    const f = new FormData(form);
    const str = (k: string) => String(f.get(k) ?? "").trim();
    const num = (k: string) => (str(k) === "" ? null : Number(str(k)));
    const pending = codeDraft.trim() ? codeDraft.split(/[\s,]+/).map((c) => c.toUpperCase()).filter((c) => c && !codes.includes(c)) : [];
    const allCodes = [...codes, ...pending];
    if (!allCodes.length && !uni) {
      setMsg({ ok: false, text: "Pick at least one stock or a universe." });
      return null;
    }
    const rows = (r: Row[]) => r.filter(([l, , v]) => l && v) as Condition[];
    const byDates = mode === "dates";
    return {
      name: base.name,
      description: str("description"),
      codes: allCodes,
      from: str("from") || null,
      to: str("to") || null,
      entry: {
        strategy: byDates ? null : strategy || null,
        profile: byDates || !strategy ? null : str("profile") || null,
        params: byDates || !strategy ? {} : base.entry.params,
        when: byDates ? [] : rows(when),
        dates: byDates ? dates : [],
        fill: str("fill") === "same_close" ? "same_close" : "next_open",
        new_signal_only: f.get("new_signal_only") === "on",
      },
      exit: {
        stop_pct: num("stop_pct"), target_pct: num("target_pct"), trail_pct: num("trail_pct"),
        trail_ma: num("trail_ma"), when_any: rows(whenAny), max_days: num("max_days"),
      },
      hold: { min_days: num("min_days") ?? 0, cooldown_days: num("cooldown_days") ?? 0 },
      costs: { round_trip_pct: num("cost") ?? 0 },
      capital: { start: num("capital") ?? 100000, per_trade_pct: num("size_pct") ?? 100 },
      universe: uni || null,
      quality: str("quality") || null,
      portfolio: shared ? { max_positions: num("max_positions") ?? 5, rank_by: str("rank_by") || null, descending: true } : null,
      liquidity: { max_pct: num("liq_pct") ?? 10, days: base.liquidity.days },
      in_sample_until: str("in_sample_until") || null,
    };
  };

  const save = (form: HTMLFormElement) => {
    const plan = build(form);
    const name = String(new FormData(form).get("save_name") ?? "").trim().toLowerCase();
    if (!plan) return;
    if (!name) return setMsg({ ok: false, text: "Give the plan a name to save it, e.g. ma-pullback." });
    start(async () => {
      setMsg(null);
      const post = (overwrite: boolean) =>
        fetch("/api/plans", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, plan, overwrite }) });
      let res = await post(false);
      if (res.status === 409 && window.confirm(`A plan called "${name}" already exists. Replace it?`)) res = await post(true);
      if (res.status === 409) return;
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return setMsg({ ok: false, text: typeof body.detail === "string" ? body.detail : `Failed (HTTP ${res.status})` });
      setBase((b) => ({ ...b, name }));
      setMsg({ ok: true, text: `Saved as ${body.path}` });
      router.refresh();
    });
  };

  const usable = meta.plans.filter((p) => p.plan);
  return (
    <form
      key={version}
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        const plan = build(e.currentTarget);
        if (!plan) return;
        setMsg(null);
        setCodes(plan.codes);
        setCodeDraft("");
        const g: Grid = {};
        for (const [k, v] of grid) {
          const values = v.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean).map(parseValue);
          if (k.trim() && values.length) g[k.trim()] = values;
        }
        const q = new URLSearchParams({ p: JSON.stringify(plan) });
        if (Object.keys(g).length) q.set("grid", JSON.stringify(g));
        router.push(`/lab?${q}`);
      }}
    >
      <datalist id="grid-paths">
        {GRID_PATHS.map(([p, label]) => <option key={p} value={p}>{label}</option>)}
        {when.map((r, i) => <option key={`w${i}`} value={`entry.when.${i}.2`}>{`Buy condition: ${r[0]} ${opLabel(r[1])} …`}</option>)}
        {whenAny.map((r, i) => <option key={`x${i}`} value={`exit.when_any.${i}.2`}>{`Sell condition: ${r[0]} ${opLabel(r[1])} …`}</option>)}
        {strategy && <option value="entry.params.">{"Strategy parameter: entry.params.<name>"}</option>}
      </datalist>
      <datalist id="lab-columns">
        {meta.columns.map((c) => <option key={c.name} value={c.example}>{c.windowed ? `${c.name}: ${c.description}` : c.description}</option>)}
      </datalist>

      <div className="flex flex-wrap items-end gap-3">
        <Label text="Saved plan" hint="Loads its rules; keeps the stocks and dates you picked">
          <select aria-label="Saved plan" value="" onChange={(e) => load(e.target.value)} className={`${field} w-44`}>
            <option value="">{base.name !== "custom" ? `${base.name} (loaded)` : "Load a plan…"}</option>
            {usable.map((p) => <option key={p.name} value={p.name} title={p.description}>{p.name}</option>)}
          </select>
        </Label>
        <div className="min-w-0 flex-1 text-xs text-muted">
          Stocks
          <div className={`${field} mt-1 flex min-h-[34px] flex-wrap items-center gap-1 py-1`}>
            <Chips items={codes} onRemove={(c) => setCodes(codes.filter((x) => x !== c))} />
            <input
              aria-label="Add a stock"
              list="stock-codes"
              value={codeDraft}
              placeholder={codes.length ? "add another…" : "e.g. PTL (Enter to add)"}
              onChange={(e) => {
                const v = e.target.value;
                // Add on a separator, or when picked from the suggestions (not while typing: GP is a prefix of GPHISPAT)
                const picked = (e.nativeEvent as InputEvent).inputType === "insertReplacementText" || !(e.nativeEvent as InputEvent).inputType;
                if (/[\s,]$/.test(v) || (picked && universe.includes(v.toUpperCase()))) addCode(v);
                else setCodeDraft(v);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && codeDraft.trim()) {
                  e.preventDefault();
                  addCode(codeDraft);
                }
              }}
              className="min-w-24 flex-1 bg-transparent text-sm uppercase text-ink outline-none placeholder:normal-case placeholder:text-muted"
            />
          </div>
        </div>
        <Label text="Or a universe" hint="Also every stock in this list (today's list: stocks that left it are missing)">
          <select aria-label="Universe" value={uni} onChange={(e) => setUni(e.target.value)} className={`${field} w-32`}>
            <option value="">None</option>
            {meta.universes.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </Label>
        <Label text="Quality filter" hint="Keep only stocks passing this profile's quality filter today (uses today's fundamentals)">
          <select name="quality" defaultValue={base.quality ?? ""} className={`${field} w-28`}>
            <option value="">None</option>
            {meta.profiles.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Label>
        <Label text="From" hint={`First signal day (data from ${meta.first_date})`}>
          <input name="from" type="date" min={meta.first_date} max={meta.last_date} defaultValue={base.from ?? ""} className={field} />
        </Label>
        <Label text="To" hint={`End of the test (default: last stored day, ${meta.last_date})`}>
          <input name="to" type="date" min={meta.first_date} max={meta.last_date} defaultValue={base.to ?? ""} className={field} />
        </Label>
        <button type="submit" className={primary}>Run</button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold">Buy</legend>
          <div className="inline-flex rounded-lg border border-line p-0.5 text-sm" role="radiogroup" aria-label="Entry type">
            {(["rules", "dates"] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                className={`rounded-md px-3 py-0.5 ${mode === m ? "bg-surface-2 font-medium" : "text-ink-2 hover:text-ink"}`}>
                {m === "rules" ? "On a signal" : "On dates"}
              </button>
            ))}
          </div>
          {mode === "rules" ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <Label text="Strategy signal" hint="Optional: an existing strategy's signal (AND the conditions below)">
                  <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className={`${field} w-full`}>
                    <option value="">None</option>
                    {meta.strategies.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}
                  </select>
                </Label>
                <Label text="Its settings" hint="Take the strategy's parameters from a profile, or the defaults in strategies/*.py">
                  <select name="profile" defaultValue={base.entry.profile ?? ""} disabled={!strategy} className={`${field} w-full`}>
                    <option value="">Defaults</option>
                    {meta.profiles.map((p) => <option key={p} value={p}>{p} profile</option>)}
                  </select>
                </Label>
              </div>
              <div className="text-xs text-muted">
                <div className="mb-1">Conditions at the close (all must hold)</div>
                <Conditions rows={when} onChange={setWhen} operators={meta.operators} fresh={["close", ">", "sma_50"]}
                  emptyText={strategy ? "None: buy on every strategy signal." : "Add a condition or pick a strategy."} />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name="new_signal_only" defaultChecked={base.entry.new_signal_only} />
                First day of each setup only
              </label>
            </>
          ) : (
            <div className="text-xs text-muted">
              <div className="mb-1">Days you buy on (a non-trading day rolls to the next one)</div>
              <div className="flex flex-wrap items-center gap-1">
                <Chips items={dates} onRemove={(d) => setDates(dates.filter((x) => x !== d))} />
              </div>
              <div className="mt-1.5 flex gap-1">
                <input aria-label="Buy date" type="date" min={meta.first_date} max={meta.last_date} value={dateDraft} onChange={(e) => setDateDraft(e.target.value)} className={field} />
                <button type="button" className={button} onClick={() => {
                  if (dateDraft && !dates.includes(dateDraft)) setDates([...dates, dateDraft].sort());
                  setDateDraft("");
                }}>Add</button>
              </div>
              <input type="hidden" name="new_signal_only" value={base.entry.new_signal_only ? "on" : ""} />
            </div>
          )}
          <Label text={mode === "rules" ? "Buy at" : "Buy at that day's"}>
            <select name="fill" defaultValue={base.entry.fill} className={`${field} w-full`}>
              <option value="next_open">{mode === "rules" ? "next day's open" : "open"}</option>
              <option value="same_close">{mode === "rules" ? "same day's close" : "close"}</option>
            </select>
          </Label>
        </fieldset>

        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold">Sell (first to trigger)</legend>
          <div className="grid grid-cols-2 gap-2">
            <NumField name="stop_pct" label="Stop loss %" value={base.exit.stop_pct} hint="Intraday low this % below the entry; a gap down fills at the open" />
            <NumField name="target_pct" label="Target %" value={base.exit.target_pct} hint="Intraday high this % above the entry; a gap up fills at the open. Stop wins if both hit the same day" />
            <NumField name="trail_pct" label="Trailing stop %" value={base.exit.trail_pct} hint="Close this % below the highest close since entry" />
            <NumField name="trail_ma" label="Close below MA" value={base.exit.trail_ma} step="1" hint="Close below this moving average (days)" />
            <NumField name="max_days" label="Time limit (days)" value={base.exit.max_days} step="1" hint="Sell at the close this many trading days after the signal day" />
          </div>
          <div className="text-xs text-muted">
            <div className="mb-1">Or at the close when any of</div>
            <Conditions rows={whenAny} onChange={setWhenAny} operators={meta.operators} fresh={["rsi_14", ">", "70"]} emptyText="None." />
          </div>
        </fieldset>

        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold">Hold &amp; money</legend>
          <div className="grid grid-cols-2 gap-2">
            <NumField name="min_days" label="Can sell after (days)" value={base.hold.min_days} step="1" placeholder="0"
              hint="No exit before entry + this many trading days (DSE settlement). Stops wait too" />
            <NumField name="cooldown_days" label="Wait after exit (days)" value={base.hold.cooldown_days} step="1" placeholder="0" />
            <NumField name="cost" label="Round-trip cost %" value={base.costs.round_trip_pct} placeholder="0" hint="Brokerage both sides + charges" />
            <NumField name="capital" label="Starting capital" value={base.capital.start} step="1000" placeholder="100000" />
            {!shared && <NumField name="size_pct" label="% of equity per trade" value={base.capital.per_trade_pct} placeholder="100" />}
            <Label text="Tuning period until" hint="Optional: stats split into tuning (up to here) and test periods">
              <input name="in_sample_until" type="date" defaultValue={base.in_sample_until ?? ""} className={`${field} w-full`} />
            </Label>
            <NumField name="liq_pct" label="Flag stake above % of traded value" value={base.liquidity.max_pct} placeholder="10"
              hint={`Flag trades bigger than this % of the stock's ${base.liquidity.days}-day average daily traded value`} />
          </div>
          <label className="flex items-center gap-2 text-sm" title="One pot for all the stocks instead of separate capital per stock">
            <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
            Shared capital across the stocks
          </label>
          {shared && (
            <div className="grid grid-cols-2 gap-2">
              <NumField name="max_positions" label="Max open positions" value={base.portfolio?.max_positions ?? 5} step="1" placeholder="5"
                hint="Each position gets equity / this, capped at the cash left" />
              <Label text="When slots are short, first" hint="Highest first. Default: the strategy's score, else vol_x_20 (volume vs its 20-day average)">
                <input name="rank_by" list="lab-columns" defaultValue={base.portfolio?.rank_by ?? ""} placeholder={strategy ? "score" : "vol_x_20"} className={`${field} w-full`} />
              </Label>
            </div>
          )}
        </fieldset>
      </div>

      <details className="rounded-lg border border-line p-3" open={grid.some(([k]) => k)}>
        <summary className="cursor-pointer text-sm font-semibold">Parameter grid <span className="font-normal text-ink-2">(optional: try several values; Run then compares every combination)</span></summary>
        <div className="mt-3 space-y-2">
          {grid.map(([k, v], i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input aria-label={`Grid parameter ${i + 1}`} list="grid-paths" value={k} placeholder="e.g. exit.stop_pct"
                onChange={(e) => setGrid(grid.map((r, j) => (j === i ? [e.target.value.trim(), r[1]] : r)))} className={`${field} w-64`} />
              <input aria-label={`Grid values ${i + 1}`} value={v} placeholder="e.g. 5, 8, 10"
                onChange={(e) => setGrid(grid.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} className={`${field} w-48`} />
              {(k || v) && <button type="button" onClick={() => setGrid(grid.map((r, j) => (j === i ? ["", ""] : r)))} className="text-xs text-ink-2 hover:text-down">clear</button>}
            </div>
          ))}
          <p className="text-xs text-muted">
            Pick a parameter (or a condition&apos;s number, e.g. entry.when.1.2) and comma-separated values; up to 36 combinations.
            Set a tuning period above: choose on it, and judge on the test period.
          </p>
        </div>
      </details>

      <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
        <Label text="Save as" hint="config/plans/<name>.yaml">
          <input name="save_name" defaultValue={base.name !== "custom" ? base.name : ""} placeholder="e.g. my-breakout" className={`${field} w-40 lowercase placeholder:normal-case`} />
        </Label>
        <Label text="Description" className="min-w-0 flex-1">
          <input name="description" defaultValue={base.description} placeholder="What the plan tries to catch" className={`${field} w-full`} />
        </Label>
        <button type="button" disabled={pending} className={button} onClick={(e) => save(e.currentTarget.form!)}>
          {pending ? "Saving…" : "Save plan"}
        </button>
        {msg && <p className={`w-full text-xs ${msg.ok ? "text-up" : "text-down"}`}>{msg.text}</p>}
      </div>
    </form>
  );
}
