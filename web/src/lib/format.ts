export const num = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const pct = (v: number | null | undefined, digits = 1, signed = true) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const int = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : Math.round(v).toLocaleString("en-US");

export const bn = (mn: number | null | undefined) => (mn === null || mn === undefined ? "–" : `৳${(mn / 1000).toFixed(1)} bn`);

export const day = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

export const signClass = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? "text-ink-2" : v > 0 ? "text-up" : "text-down");
