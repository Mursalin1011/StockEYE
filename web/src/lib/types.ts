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
  all_signals: ScreenSignal[];
  watch: WatchItem[];
};

/** One strategy hit on the screen day, including those below the shortlist cut. */
export type ScreenSignal = {
  code: string;
  strategy: string;
  title: string;
  role: string;
  score: number;
  weighted: number;
  reasons: string[];
  on_shortlist: boolean;
};

/** A setup still forming (e.g. a second breakout waiting for its re-break). */
export type WatchItem = {
  code: string;
  strategy: string;
  title: string;
  reasons: string[];
  metrics: {
    first_date: string;
    days_from_first: number;
    days_left: number;
    pivot: number;
    failed_high: number;
    trigger: number;
    close: number;
    to_trigger_pct: number;
    shake_low_pct: number;
    floor: number;
    volume_needed: number;
  };
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
/** Trade lab: a buy or sell on the chart (sell carries the trade's net return). */
export type TradeMark = { time: string; side: "buy" | "sell"; price: number; ret?: number; text: string };
/** A price-unit column drawn over the candles, e.g. sma_50. */
export type Overlay = { name: string; points: { time: string; value: number }[] };
export type ChartData = {
  code: string;
  profile: string;
  bars: Bar[];
  indicators: IndicatorRow[];
  markers: Marker[];
  ex_dates: string[];
  trades?: TradeMark[];
  overlays?: Overlay[];
};

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
  avg_win: number | null;
  avg_loss: number | null;
  profit_factor: number | null;
  median_days: number | null;
};

export type ExitStyle = { name: string; label: string; open?: number };

export type RecallRow = {
  segment: string;
  moves: number;
  caught: number;
  recall_pct: number | null;
  signals: number;
  signals_per_catch: number | null;
  median_days_after_start: number | null;
};

export type WinnersConfig = {
  min_gain_pct: number;
  within_days: number;
  before_days: number;
  after_days: number;
  max_entry_premium_pct: number;
};

export type BacktestView = {
  profile: string;
  start: string;
  end: string;
  in_sample_until: string | null;
  cost_pct: number;
  primary_horizon: number;
  horizons: number[];
  exits: ExitStyle[];
  universe_size: number;
  summary: Record<string, SummaryRow[]>;
  recall: RecallRow[];
  winners: WinnersConfig;
  trades: (Record<string, string | number | null> & { date: string; code: string; strategies: string })[];
};

export type CaseSignal = Record<string, string | number | boolean | string[] | null> & {
  date: string;
  strategy: string;
  title: string;
  role: "primary" | "confirm";
  status: "signal" | "blocked";
  score: number;
  days_on: number;
  best_score: number | null;
  clears_cut: boolean;
  cut_date: string | null;
  shortlist_rank: number | null;
  tech: string;
  blocked_by: string[];
  reasons: string[];
  close: number;
  entry: number | null;
  best: number | null;
  worst: number | null;
  to_last: number | null;
};

export type CaseMove = { date: string; i: number; start: number; peak_date: string; peak_gain_pct: number; caught_by: string[] };

export type CaseStudyView = {
  code: string;
  profile: string;
  name: string | null;
  start: string;
  end: string;
  last_date: string;
  last_close: number;
  window: { first_close: number; last_close: number; change_pct: number; low: number; low_date: string; high: number; high_date: string };
  quality_passed: boolean;
  quality_failures: string[];
  horizons: number[];
  primary_horizon: number;
  cost_pct: number;
  min_score: number;
  exits: ExitStyle[];
  shortlist: boolean;
  signals: CaseSignal[];
  moves: CaseMove[];
  chart: ChartData;
};

export type HistoryRow = { as_of: string; profile: string; rank: number; code: string; final_score: number; strategies: string[] };

export type ProfileFile = { name: string; path: string; yaml: string };

export type Stance = "bullish" | "bearish" | "neutral";

export type ResearchDoc = {
  id: number;
  url: string | null;
  filename: string;
  source: string | null;
  publisher: string | null;
  doc_type: string;
  published: string | null;
  pages: number | null;
  codes: string[];
  added_at: string;
  reviewed: boolean;
};

export type ReviewSummary = { id: number; created_at: string; as_of: string; model: string; doc_ids: number[]; headline: string; calls: number };

export type CalibrationRow = { confidence: string; calls: number; expected_hit_pct: number | null; actual_hit_pct: number | null; avg_excess_pct: number | null };

export type ResearchOverview = {
  has_api_key: boolean;
  model: string;
  guide: string;
  sources: string;
  inbox: string;
  docs: ResearchDoc[];
  reviews: ReviewSummary[];
  track_record: { calls_made: number; calls_scored: number; hit_rate_pct?: number; avg_excess_vs_basket_pct?: number; note?: string };
  calibration: CalibrationRow[];
  running: { id: string; started: number }[];
};

export type StockCall = {
  code: string;
  company: string;
  stance: Stance;
  horizon_days: number;
  confidence: number;
  thesis: string;
  evidence: string[];
  invalidation: string;
  stockeye_view: "agrees" | "disagrees" | "silent";
  stockeye_note: string;
  priced_in: "no" | "partly" | "yes" | "unknown";
};

export type ReviewBody = {
  headline: string;
  market_view: { stance: Stance; confidence: number; horizon_days: number; summary: string; drivers: string[]; risks: string[] };
  macro: { topic: string; summary: string; impact: "positive" | "negative" | "mixed" | "neutral"; sectors: string[]; source: string }[];
  sectors: { sector: string; stance: Stance; confidence: number; rationale: string }[];
  calls: StockCall[];
  watch: { code: string; what_to_watch: string }[];
  noise: string[];
  data_gaps: string[];
  sources_used: { document: string; key_points: string[] }[];
};

export type ReviewDetail = {
  id: number;
  created_at: string;
  as_of: string;
  model: string;
  usage: Record<string, number | string | null> | null;
  review: ReviewBody;
  docs: { id: number; source: string | null; filename: string; doc_type: string; published: string | null; url: string | null }[];
  scores: { code: string; stance: Stance; horizon_days: number; confidence: number; ret: number | null; bench: number | null; excess: number | null; correct: number | null }[];
};

// --- trade lab (docs/06-trade-lab-plan.md) -------------------------------------

/** [left column, operator, right column or number], e.g. ["rsi_14", "<", 40] */
export type Condition = [string, string, number | string];

export type PlanJson = {
  name: string;
  description: string;
  codes: string[];
  from: string | null;
  to: string | null;
  entry: {
    strategy: string | null;
    profile: string | null;
    params: Record<string, unknown>;
    when: Condition[];
    dates: string[];
    fill: "next_open" | "same_close";
    new_signal_only: boolean;
  };
  exit: {
    stop_pct: number | null;
    target_pct: number | null;
    trail_pct: number | null;
    trail_ma: number | null;
    when_any: Condition[];
    max_days: number | null;
  };
  hold: { min_days: number; cooldown_days: number };
  costs: { round_trip_pct: number };
  capital: { start: number; per_trade_pct: number };
  universe: string | null;
  quality: string | null;
  portfolio: { max_positions: number; rank_by: string | null; descending: boolean } | null;
  liquidity: { max_pct: number; days: number };
  in_sample_until: string | null;
};

export type LabColumn = { name: string; example: string; description: string; windowed: boolean };

export type SavedPlan = { name: string; description?: string; plan?: PlanJson; describe?: string[]; error?: string };

export type LabMeta = {
  plans: SavedPlan[];
  columns: LabColumn[];
  operators: string[];
  strategies: { name: string; title: string }[];
  profiles: string[];
  first_date: string;
  last_date: string;
  universes: string[];
  default_plan: PlanJson;
};

export type LabTrade = {
  code: string;
  signal_date: string;
  entry_date: string;
  entry: number;
  entry_actual: number;
  exit_date: string;
  exit: number;
  exit_actual: number;
  why: string;
  days: number;
  ret_pct: number;
  best_pct: number | null;
  worst_pct: number | null;
  flags: string;
  stake: number;
  pnl: number;
  value_pct: number | null;
  basket_pct?: number | null;
  excess_pct?: number | null;
};

export type LabSummaryRow = {
  segment: string;
  trades: number;
  win_rate: number | null;
  mean_ret: number | null;
  median_ret: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  profit_factor: number | null;
  best: number | null;
  worst: number | null;
  median_days: number | null;
  mean_basket?: number | null;
  mean_excess?: number | null;
  median_excess?: number | null;
  beat_basket?: number | null;
};

export type LabStock = {
  code: string;
  start: string;
  end: string;
  first_close: number;
  last_close: number;
  buy_hold_pct: number;
  buy_hold_max_dd_pct: number;
  in_market_pct: number;
  trades: number;
  open: number;
  pnl: number;
  plan_pct: number | null;
  plan_max_dd_pct: number | null;
  end_equity: number | null;
  basket_hold_pct?: number | null;
};

/** Shared capital (plan.portfolio): the whole pot vs the same money split over its stocks and held. */
export type LabPortfolio = {
  return_pct: number;
  max_dd_pct: number;
  bench_pct: number;
  bench_max_dd_pct: number;
  avg_positions: number;
  max_positions: number;
  in_market_pct: number;
  skipped: number;
  end_equity: number;
  stocks: number;
  basket_hold_pct?: number | null;
};

export type EquityPoint = { time: string; plan: number; hold: number };

export type LabResultView = {
  plan: PlanJson;
  describe: string[];
  codes: string[];
  portfolio: LabPortfolio | null;
  trades: LabTrade[];
  summary: LabSummaryRow[];
  stocks: LabStock[];
  warnings: string[];
  pending: string[];
  basket: string | null;
  equity: Record<string, EquityPoint[]>;
  chart_code: string | null;
  chart: ChartData | null;
};

/** One parameter-grid combination: the grid values (by path) and the stats (see simulate.sweep). */
export type SweepRow = Record<string, number | string | null>;

export type SweepView = {
  plan: PlanJson;
  describe: string[];
  grid: Record<string, (number | string)[]>;
  stocks: number;
  split: boolean;
  rows: SweepRow[];
};
