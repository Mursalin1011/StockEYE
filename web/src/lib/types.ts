// Shapes returned by the Python API (src/dse_screener/api/app.py).

export type ProfileMeta = { name: string; description: string };

export type Meta = {
  prices_from: string;
  prices_to: string;
  profiles: ProfileMeta[];
  strategies: Record<string, string>;
  universe: string[];
  disclaimer: string;
};

export type Pick = {
  rank: number;
  code: string;
  final_score: number;
  strategies: string[];
  reasons: string[];
  news: string[];
};

export type ProfileScreen = {
  profile: string;
  description: string;
  run_id: number;
  run_at: string;
  universe_size: number;
  passed_quality: number;
  signals: number;
  picks: Pick[];
};

export type Market = { turnover_cr: number; advances: number; declines: number; unchanged: number; traded: number };

export type Screen = { as_of: string; market: Market; profiles: ProfileScreen[] };

export type Run = { run_id: number; run_at: string; as_of: string; profile: string; universe_size: number; passed_quality: number };

export type StockRow = {
  code: string;
  name: string | null;
  sector: string | null;
  category: string | null;
  market_cap_mn: number | null;
  date: string | null;
  close: number | null;
  change_pct: number | null;
  volume: number | null;
  pe: number | null;
  p_nav: number | null;
  dividend_yield: number | null;
  dividend_streak: number | null;
  strategic_pct: number | null;
  institute_change_pp: number | null;
  eps_cagr_3y: number | null;
  [key: `pass_${string}`]: boolean | null;
};

export type Bar = { time: string; open: number; high: number; low: number; close: number; volume: number };
export type IndicatorRow = {
  time: string;
  rsi: number | null;
  vol_avg: number | null;
  macd: number | null;
  signal: number | null;
  hist: number | null;
};
export type Marker = { time: string; strategy: string; title: string; score: number };
export type ChartData = { code: string; profile: string; bars: Bar[]; indicators: IndicatorRow[]; markers: Marker[]; ex_dates: string[] };

export type StockDetail = {
  company: Record<string, string | number | null>;
  metrics: Record<string, string | number | null>;
  shareholding: { as_of: string; sponsor: number; govt: number; institute: number; foreign_pct: number; public: number }[];
  annual: { year: number; eps: number | null; nav: number | null; profit_mn: number | null; pe: number | null; dividend_text: string | null; dividend_yield: number | null }[];
  dividends: { year: number; cash_pct: number; stock_pct: number }[];
  corporate_actions: { record_date: string; ex_date: string | null; cash_pct: number; stock_pct: number; revised: number; ex_open: number | null }[];
  news: { post_date: string; title: string; body: string }[];
};

export type QualityView = {
  profile: string;
  rules: Record<string, { min?: number; max?: number; in?: string[]; not_in?: string[] }>;
  metrics: Record<string, string>;
  rows: (Record<string, string | number | boolean | null> & { code: string; passed: boolean; failures: string[] })[];
};

export type SummaryRow = {
  segment: string;
  trades: number;
  median_ret: number | null;
  mean_ret: number | null;
  hit_rate: number | null;
  median_bench: number | null;
  median_excess: number | null;
  mean_excess: number | null;
  beat_bench: number | null;
  worst: number | null;
  best: number | null;
};

export type BacktestView = {
  profile: string;
  start: string;
  end: string;
  in_sample_until: string | null;
  cost_pct: number;
  primary_horizon: number;
  horizons: number[];
  universe_size: number;
  summary: Record<string, SummaryRow[]>;
  trades: (Record<string, string | number | null> & { date: string; code: string; strategies: string })[];
};

export type HistoryRow = { as_of: string; profile: string; rank: number; code: string; final_score: number; strategies: string[] };

export type ProfileFile = { name: string; path: string; yaml: string };
