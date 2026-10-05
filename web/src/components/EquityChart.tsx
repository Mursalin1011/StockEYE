"use client";

// Trade lab equity: the plan's money vs buying and holding the same stock with the same money.
// One pane, one money axis. Plan = first categorical slot; buy & hold = neutral reference line.
import { ColorType, CrosshairMode, LineSeries, LineStyle, createChart, type IChartApi, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EquityPoint } from "@/lib/types";

const money = (v: number | undefined) => (v === undefined ? "–" : Math.round(v).toLocaleString("en-US"));

export function EquityChart({ points, start, height = 260, labels = { plan: "Plan", hold: "Buy & hold" } }: {
  points: EquityPoint[]; start: number; height?: number; labels?: { plan: string; hold: string };
}) {
  const ref = useRef<HTMLDivElement>(null);
  const last = points.at(-1)?.time ?? "";
  const [hover, setHover] = useState(last);
  const byTime = useMemo(() => new Map(points.map((p) => [p.time, p])), [points]);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const build = (): IChartApi => {
      const s = getComputedStyle(document.documentElement);
      const v = (n: string) => s.getPropertyValue(n).trim();
      const chart = createChart(el, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: v("--muted"), fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif', attributionLogo: true },
        grid: { vertLines: { visible: false }, horzLines: { color: v("--grid") } },
        rightPriceScale: { borderColor: v("--axis") },
        timeScale: { borderColor: v("--axis") },
        crosshair: { mode: CrosshairMode.Normal },
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
        localization: { priceFormatter: (p: number) => Math.round(p).toLocaleString("en-US") },
      });
      const hold = chart.addSeries(LineSeries, { color: v("--ink-2"), lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, title: labels.hold });
      hold.setData(points.map((p) => ({ time: p.time as Time, value: p.hold })));
      const plan = chart.addSeries(LineSeries, { color: v("--s1"), lineWidth: 2, priceLineVisible: false, title: labels.plan });
      plan.setData(points.map((p) => ({ time: p.time as Time, value: p.plan })));
      plan.createPriceLine({ price: start, color: v("--muted"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((p) => setHover(p.time ? String(p.time) : last));
      return chart;
    };
    let chart = build();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const rebuild = () => {
      chart.remove();
      chart = build();
    };
    mq.addEventListener("change", rebuild);
    return () => {
      mq.removeEventListener("change", rebuild);
      chart.remove();
    };
  }, [points, start, last, labels.plan, labels.hold]);

  const h = byTime.get(hover) ?? byTime.get(last);
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2 tabular">
        <span className="font-medium text-ink">{h?.time ?? "–"}</span>
        <span><span style={{ color: "var(--s1)" }}>━</span> {labels.plan} <span className="font-medium text-ink">{money(h?.plan)}</span></span>
        <span><span className="text-ink-2">┅</span> {labels.hold} <span className="font-medium text-ink">{money(h?.hold)}</span></span>
        <span className="text-muted">dotted line = starting capital {money(start)}</span>
      </div>
      <div ref={ref} style={{ height }} className="w-full" />
    </div>
  );
}
