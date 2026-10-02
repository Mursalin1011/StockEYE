"use client";

// Price (candles + strategy or buy/sell markers + ex-dates + overlay lines), volume, RSI and MACD in
// separate panes that share the date axis. One scale per pane: no dual-axis charts. Colors come from CSS tokens,
// so light/dark each use their own validated palette steps.
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartData } from "@/lib/types";

const SHAPE: Record<string, "circle" | "arrowUp" | "square"> = {
  quiet_accumulation: "circle",
  base_breakout: "arrowUp",
  big_hands: "square",
  second_breakout: "arrowUp",
};
const SLOT: Record<string, string> = { quiet_accumulation: "--s1", base_breakout: "--s2", big_hands: "--s3", second_breakout: "--s2" };

function tokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    ink2: v("--ink-2"), muted: v("--muted"), grid: v("--grid"), axis: v("--axis"),
    up: v("--up"), down: v("--down"), vol: v("--vol"), s1: v("--s1"), s2: v("--s2"), ink: v("--ink"),
    slot: (k: string) => v(SLOT[k] ?? "--muted"), overlay: (i: number) => v(OVERLAY[i] ?? "--muted"),
  };
}

/** Overlay lines (trade lab: MAs etc.) take the categorical slots in fixed order. */
const OVERLAY = ["--s1", "--s3", "--s2"];

/** "#0ca30c" + 0.55 -> "rgba(12,163,12,0.55)" (canvas-safe; no color-mix) */
function alpha(hex: string, a: number) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const fmt = (v: number | null | undefined, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));

export function StockChart({ data, height = 680 }: { data: ChartData; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const lastTime = data.bars.at(-1)?.time ?? "";
  const [hover, setHover] = useState<string>(lastTime);

  const byTime = useMemo(() => {
    const ind = new Map(data.indicators.map((r) => [r.time, r]));
    return new Map(data.bars.map((b) => [b.time, { bar: b, ind: ind.get(b.time) }]));
  }, [data]);
  const markersByTime = useMemo(() => {
    const m = new Map<string, string[]>();
    data.markers.forEach((mk) => m.set(mk.time, [...(m.get(mk.time) ?? []), mk.title]));
    (data.trades ?? []).forEach((t) => m.set(t.time, [...(m.get(t.time) ?? []), t.text]));
    return m;
  }, [data]);
  const isLab = data.trades !== undefined;

  useEffect(() => {
    const el = ref.current;
    if (!el || data.bars.length === 0) return;

    const build = (): IChartApi => {
      const c = tokens();
      const chart = createChart(el, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: c.muted,
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          panes: { separatorColor: c.grid, separatorHoverColor: c.axis, enableResize: true },
          attributionLogo: true,
        },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.axis },
        timeScale: { borderColor: c.axis },
        crosshair: { mode: CrosshairMode.Normal },
        // Mouse wheel scrolls the page, not the chart; zoom by dragging the axes or with the range buttons
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
      });

      // Pane 0: candles + markers
      const candles = chart.addSeries(CandlestickSeries, {
        upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down, borderVisible: false, priceLineVisible: false,
      }, 0);
      candles.setData(data.bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
      const markers: SeriesMarker<Time>[] = [
        ...data.markers.map((m) => ({
          time: m.time as Time, position: "belowBar" as const, color: c.slot(m.strategy), shape: SHAPE[m.strategy] ?? "circle",
          // same shape and colour family as a first breakout, labelled so the two stay distinguishable
          ...(m.strategy === "second_breakout" ? { text: "2nd" } : {}),
        })),
        ...data.ex_dates.map((d) => ({ time: d as Time, position: "aboveBar" as const, color: c.muted, shape: "square" as const, text: "Ex", size: 0.6 })),
        // Trade lab: buy = up arrow under the bar; sell = down arrow above it, coloured by the trade's result
        ...(data.trades ?? []).map((t) =>
          t.side === "buy"
            ? { time: t.time as Time, position: "belowBar" as const, color: c.ink, shape: "arrowUp" as const, text: "B" }
            : { time: t.time as Time, position: "aboveBar" as const, color: (t.ret ?? 0) > 0 ? c.up : c.down, shape: "arrowDown" as const, text: "S" },
        ),
      ].sort((a, b) => String(a.time).localeCompare(String(b.time)));
      createSeriesMarkers(candles, markers);
      (data.overlays ?? []).forEach((o, i) => {
        const line = chart.addSeries(LineSeries, { color: c.overlay(i), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0);
        line.setData(o.points.map((p) => ({ time: p.time as Time, value: p.value })));
      });

      // Pane 1: volume + 20-day average
      const vol = chart.addSeries(HistogramSeries, { color: c.vol, priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
      vol.setData(data.bars.map((b) => ({ time: b.time as Time, value: b.volume ?? 0 })));
      const volAvg = chart.addSeries(LineSeries, { color: c.ink2, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, priceFormat: { type: "volume" } }, 1);
      volAvg.setData(data.indicators.filter((r) => r.vol_avg !== null).map((r) => ({ time: r.time as Time, value: r.vol_avg! })));

      // Pane 2: RSI with 70 / 30 guides
      const rsi = chart.addSeries(LineSeries, { color: c.ink2, lineWidth: 2, priceLineVisible: false }, 2);
      rsi.setData(data.indicators.filter((r) => r.rsi !== null).map((r) => ({ time: r.time as Time, value: r.rsi! })));
      for (const level of [70, 30]) {
        rsi.createPriceLine({ price: level, color: c.muted, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
      }

      // Pane 3: MACD histogram + lines
      const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 3);
      hist.setData(data.indicators.filter((r) => r.hist !== null).map((r) => ({
        time: r.time as Time, value: r.hist!, color: alpha(r.hist! >= 0 ? c.up : c.down, 0.55),
      })));
      const macd = chart.addSeries(LineSeries, { color: c.s1, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 3);
      macd.setData(data.indicators.filter((r) => r.macd !== null).map((r) => ({ time: r.time as Time, value: r.macd! })));
      const sig = chart.addSeries(LineSeries, { color: c.s2, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 3);
      sig.setData(data.indicators.filter((r) => r.signal !== null).map((r) => ({ time: r.time as Time, value: r.signal! })));

      const panes = chart.panes();
      [3.2, 1, 1, 1].forEach((f, i) => panes[i]?.setStretchFactor(f));
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((p) => setHover(p.time ? String(p.time) : lastTime));
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
  }, [data, lastTime]);

  const h = byTime.get(hover) ?? byTime.get(lastTime);
  const sigs = markersByTime.get(hover) ?? [];
  return (
    <div>
      {/* Hover readout + legend: values at the crosshair (latest day when not hovering) */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2 tabular">
        <span className="font-medium text-ink">{h?.bar.time ?? "–"}</span>
        <span>O {fmt(h?.bar.open)} H {fmt(h?.bar.high)} L {fmt(h?.bar.low)} C <span className="font-medium text-ink">{fmt(h?.bar.close)}</span></span>
        <span>Vol {h?.bar.volume?.toLocaleString("en-US") ?? "–"} <span className="text-muted">(20d avg {fmt(h?.ind?.vol_avg, 0)})</span></span>
        <span>RSI {fmt(h?.ind?.rsi)}</span>
        <span>MACD {fmt(h?.ind?.macd, 2)} / signal {fmt(h?.ind?.signal, 2)}</span>
        {sigs.length > 0 && <span className="font-medium text-ink">{isLab ? sigs.join(" · ") : `Signal: ${sigs.join(", ")}`}</span>}
      </div>
      <div ref={ref} style={{ height }} className="w-full" />
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {isLab ? (
          <>
            <span><span className="text-ink">▲ B</span> buy</span>
            <span><span className="text-up">▼ S</span> / <span className="text-down">▼ S</span> sell (gain / loss)</span>
            {(data.overlays ?? []).map((o, i) => (
              <span key={o.name}><span style={{ color: `var(${OVERLAY[i]})` }}>━</span> {o.name}</span>
            ))}
          </>
        ) : (
          <>
            <span><span style={{ color: "var(--s1)" }}>●</span> Quiet accumulation</span>
            <span><span style={{ color: "var(--s2)" }}>▲</span> Base breakout</span>
            <span><span style={{ color: "var(--s2)" }}>▲ 2nd</span> Second breakout</span>
            <span><span style={{ color: "var(--s3)" }}>■</span> Big hands</span>
          </>
        )}
        <span><span className="text-muted">■ Ex</span> dividend/bonus ex-date</span>
        <span>Panes: price · volume (line = 20-day avg) · RSI 14 (dashed 70/30) · MACD 12/26/9 (blue) with signal (orange)</span>
      </div>
    </div>
  );
}
