"""Load and validate YAML config. All tunable numbers live in config/, not in code."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from .rules import Rule

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class Paths(BaseModel):
    db: Path
    raw: Path


class HttpConfig(BaseModel):
    user_agent: str
    timeout_s: float = 120
    delay_s: float = 2.0
    retries: int = 3


class SourceUrl(BaseModel):
    base_url: str


class Sources(BaseModel):
    dse_archive: SourceUrl
    dse_company: SourceUrl
    dse_news: SourceUrl
    dse_market: SourceUrl = SourceUrl(base_url="https://old.dsebd.org/market-statistics.php")
    dse_market_summary: SourceUrl = SourceUrl(base_url="https://www.dse.com.bd/api/live/data-archive/market-summary")


class IngestConfig(BaseModel):
    backfill_years: int = 2
    chunk_days: int = 31
    min_rows_per_day: int = 300


class AdjustmentConfig(BaseModel):
    adjust_cash_dividends: bool = True   # DSE also lowers the reference price for cash dividends


WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


class DailyConfig(BaseModel):
    trading_weekdays: list[Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]] = [
        "Sun", "Mon", "Tue", "Wed", "Thu"
    ]
    not_before: time = time(14, 45)
    retry_every_min: float = 5
    give_up_at: time = time(16, 30)
    refresh_news: bool = True
    refresh_company_pages_every_days: int = 7
    company_pages_per_day: int = 60      # cap, so the 3pm job stays fast; stalest pages first

    def is_trading_weekday(self, d: date) -> bool:
        return d.weekday() in {WEEKDAYS[w] for w in self.trading_weekdays}


class ReportConfig(BaseModel):
    profiles: list[str] | None = None    # which profiles to run/show, in order (None = all, alphabetical)
    news_lookback_days: int = 14
    max_news_per_pick: int = 2
    max_reasons_per_pick: int = 4


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""


class ResearchConfig(BaseModel):
    """AI review of research documents (broker PDFs etc.). See config/research/ANALYST.md."""

    guide: Path = Path("config/research/ANALYST.md")     # the analyst's standing instructions
    sources: Path = Path("config/research/sources.yaml")  # how documents are recognised
    inbox: Path = Path("data/inbox/pdf")                 # drop PDFs here; `research inbox` imports them
    store: Path = Path("data/research")                  # imported copies (git-ignored, never published)
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = 64000
    max_docs_per_review: int = 6
    max_pdf_mb: float = 25.0             # per document; the API takes up to 32 MB per request
    lookback_days: int = 4               # a review covers unreviewed documents published this recently
    max_context_stocks: int = 60         # StockEYE data for at most this many mentioned stocks
    send_telegram: bool = True           # `research review` sends the summary to Telegram


class AnthropicConfig(BaseModel):
    api_key: str = ""    # from config/secrets.yaml or ANTHROPIC_API_KEY; empty = SDK default credentials


class Settings(BaseModel):
    timezone: str = "Asia/Dhaka"
    paths: Paths
    http: HttpConfig
    sources: Sources
    ingest: IngestConfig = IngestConfig()
    adjustments: AdjustmentConfig = AdjustmentConfig()
    daily: DailyConfig = DailyConfig()
    report: ReportConfig = ReportConfig()
    telegram: TelegramConfig = TelegramConfig()
    research: ResearchConfig = ResearchConfig()
    anthropic: AnthropicConfig = AnthropicConfig()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def today(self) -> date:
        """Today's date in Dhaka, regardless of the machine's clock timezone."""
        return datetime.now(self.tz).date()

    def resolve(self, path: Path) -> Path:
        """Config paths are relative to the project root."""
        return path if path.is_absolute() else PROJECT_ROOT / path


class UniverseQuery(BaseModel):
    """Resolved from stored company pages at run time, so new listings join automatically."""

    instrument_types: list[str] = ["Equity"]
    active_only: bool = True
    exclude: list[str] = []


class Universe(BaseModel):
    name: str
    as_of: date | None = None
    codes: list[str] = []            # a fixed list (e.g. ds30) ...
    query: UniverseQuery | None = None   # ... or a query over the companies table (e.g. all_equities)


class FilterConfig(BaseModel):
    enabled: bool = True
    rules: dict[str, Rule] = {}
    params: dict = {}            # e.g. technical filter: rsi_window, macd_fast/slow/signal
    exempt: list[str] = []       # technical filter: strategies it doesn't apply to

    def applies_to(self, strategy: str) -> bool:
        return strategy not in self.exempt


class StrategyConfig(BaseModel):
    enabled: bool = True
    weight: float = 1.0          # multiplies the strategy's 0-100 score when ranking
    # primary: can put a stock on the shortlist by itself
    # confirm: only adds the confluence bonus when a primary strategy also fires
    role: Literal["primary", "confirm"] = "primary"
    params: dict = {}            # overrides the strategy's defaults (see strategies/*.py Params)


class Boost(BaseModel):
    """Extra ranking points when a quality metric meets a condition."""

    metric: str
    when: Rule
    points: float
    label: str
    detail: str | None = None    # e.g. "holding {value:+.1f} pts"; default shows "metric = value"


class RankingConfig(BaseModel):
    top_n: int = 10
    min_score: float = 50.0      # final score needed to make the shortlist
    confluence_bonus: float = 10.0   # per additional strategy flagging the same stock
    boosts: list[Boost] = []
    # Volume around a record date is dividend-driven (buying to qualify), not accumulation.
    record_date_window_days: int = 15    # calendar days before/after the screening date
    record_date_penalty: float = 20.0


class ExitRule(BaseModel):
    """A rule-based exit, tested on the same entries as the fixed holding periods.

    Checked each trading day after entry, in this order: stop (intraday low), trailing MA
    (close below it), time limit (close `max_days` trading days after the signal).
    """

    label: str = ""
    stop_pct: float | None = None       # sell if the low falls this % below the entry price
    trail_ma: int | None = None         # sell at the close when the close is below this moving average
    max_days: int = 60                  # sell at the close this many trading days after the signal


class WinnersConfig(BaseModel):
    """'Big winner' moves for recall: from day t, the close rises min_gain_pct within within_days."""

    min_gain_pct: float = 50.0
    within_days: int = 120
    # caught = a pick/signal from `before_days` before to `after_days` after the move's first day,
    # with an entry no more than max_entry_premium_pct above the move's starting price
    before_days: int = 20
    after_days: int = 60
    max_entry_premium_pct: float = 20.0


class BacktestConfig(BaseModel):
    horizons: list[int] = [5, 10, 20]   # trading days held after entry
    primary_horizon: int = 20           # used for non-overlapping trades and tuning
    cost_pct: float = 1.0               # round trip: brokerage both sides + CDBL/other charges
    in_sample_until: date | None = None # tune on dates up to here; later dates are the out-of-sample test
    exits: dict[str, ExitRule] = {}     # extra exit styles, e.g. stop + trailing MA, on the same entries
    winners: WinnersConfig = WinnersConfig()

    @field_validator("exits")
    @classmethod
    def _exit_names(cls, v: dict[str, ExitRule]) -> dict[str, ExitRule]:
        for name in v:
            if name.isdigit():
                raise ValueError(f"exit name '{name}' must not be a number (numbers are holding periods)")
        return v


class Profile(BaseModel):
    """A saved combination of universe, filters, strategies and ranking."""

    name: str
    description: str = ""
    universe: str = "ds30"
    filters: dict[str, FilterConfig] = {}
    strategies: dict[str, StrategyConfig] = {}
    ranking: RankingConfig = RankingConfig()
    backtest: BacktestConfig = BacktestConfig()


# --- trade lab plans (docs/06-trade-lab-plan.md) -------------------------------

OPERATORS = (">", "<", ">=", "<=", "crosses_above", "crosses_below")


def _parse_condition(v):
    """'close > sma_50' or [close, '>', sma_50] -> (left, op, right); a numeric right side becomes a float."""
    if isinstance(v, str):
        parts = v.split()
        if len(parts) != 3:
            raise ValueError(f"condition '{v}': expected 'left op right', e.g. 'close > sma_50' or 'rsi_14 < 40'")
        v = parts
    if isinstance(v, (list, tuple)) and len(v) == 3 and isinstance(v[2], str):
        try:
            v = (v[0], v[1], float(v[2]))
        except ValueError:
            pass
    return v


# (left column, operator, right column or number); columns: see features.py
Condition = Annotated[tuple[str, Literal[OPERATORS], float | str], BeforeValidator(_parse_condition)]


def condition_text(c: Condition) -> str:
    left, op, right = c
    return f"{left} {op.replace('_', ' ')} {right:g}" if isinstance(right, float) else f"{left} {op.replace('_', ' ')} {right}"


def condition_str(c: Condition) -> str:
    """Round-trippable text form, e.g. 'rsi_14 < 40' (what plan YAML files use)."""
    left, op, right = c
    return f"{left} {op} {right:g}" if isinstance(right, float) else f"{left} {op} {right}"


def plan_to_yaml_data(plan: "TradePlan") -> dict:
    """A plan as a tidy dict for a YAML file: defaults left out, conditions as text."""
    data = plan.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    data["name"] = plan.name
    data["entry"] = {**data.get("entry", {})}
    if plan.entry.when:
        data["entry"]["when"] = [condition_str(c) for c in plan.entry.when]
    if plan.exit.when_any:
        data.setdefault("exit", {})["when_any"] = [condition_str(c) for c in plan.exit.when_any]
    order = ["name", "description", "codes", "universe", "quality", "from", "to", "entry", "exit", "hold", "costs",
             "capital", "portfolio", "liquidity", "in_sample_until"]
    return {k: data[k] for k in order if k in data}


class PlanEntry(BaseModel):
    """When to buy. A signal on day t (after the close) buys at t+1's open, or at t's close with same_close."""

    model_config = ConfigDict(extra="forbid")

    strategy: str | None = None          # an existing strategy's signal, e.g. base_breakout
    profile: str | None = None           # take that strategy's parameters from this profile
    params: dict = {}                    # and override these
    when: list[Condition] = []           # all must be true (together with the strategy, if any)
    dates: list[date] = []               # instead: the days you buy on (a non-trading day rolls forward)
    fill: Literal["next_open", "same_close"] = "next_open"
    new_signal_only: bool = True         # act only on the first day of a run of signal days

    @model_validator(mode="after")
    def _one_source(self):
        if self.dates and (self.strategy or self.when):
            raise ValueError("entry: use either dates, or strategy/when, not both")
        if not (self.dates or self.strategy or self.when):
            raise ValueError("entry needs a strategy, conditions (when) or dates")
        if (self.profile or self.params) and not self.strategy:
            raise ValueError("entry: profile/params only apply with a strategy")
        return self


class PlanExit(BaseModel):
    """When to sell: the first rule to trigger. Checked in the order of the fields."""

    model_config = ConfigDict(extra="forbid")

    stop_pct: float | None = None        # intraday low this % below the entry; a gap down fills at the open
    target_pct: float | None = None      # intraday high this % above the entry; a gap up fills at the open
    trail_pct: float | None = None       # close this % below the highest close since entry
    trail_ma: int | None = None          # close below this moving average
    when_any: list[Condition] = []       # any true at the close
    max_days: int | None = None          # close this many trading days after the signal day

    @property
    def any(self) -> bool:
        return any(v is not None for v in (self.stop_pct, self.target_pct, self.trail_pct, self.trail_ma,
                                           self.max_days)) or bool(self.when_any)


class PlanHold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_days: int = 2          # no exit before entry day + this many trading days (DSE settlement)
    cooldown_days: int = 0     # trading days to wait after an exit before buying again


class PlanCosts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_trip_pct: float = 1.0


class PlanCapital(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = 100_000
    per_trade_pct: float = Field(100, gt=0, le=100)   # share of current equity put into each trade


class PlanPortfolio(BaseModel):
    """Shared capital across all the plan's stocks: at most max_positions open at once, each equity / max_positions."""

    model_config = ConfigDict(extra="forbid")

    max_positions: int = Field(5, ge=1, le=50)
    # When more stocks signal than there are free slots: highest first by this. None = the strategy's score if the
    # entry has a strategy, else vol_x_20. "score" = the strategy's score; anything else = a column (features.py).
    rank_by: str | None = None
    descending: bool = True


class PlanLiquidity(BaseModel):
    """Flag trades too big for the stock: stake above max_pct of its average daily traded value."""

    model_config = ConfigDict(extra="forbid")

    max_pct: float = Field(10, gt=0)
    days: int = Field(20, ge=1)


class TradePlan(BaseModel):
    """Your own entry/exit rules, tested on stocks (each on its own, or sharing capital). config/plans/*.yaml"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = "custom"
    description: str = ""
    codes: list[str] = []
    start: date | None = Field(None, alias="from")
    end: date | None = Field(None, alias="to")
    entry: PlanEntry
    exit: PlanExit = PlanExit()
    hold: PlanHold = PlanHold()
    costs: PlanCosts = PlanCosts()
    capital: PlanCapital = PlanCapital()
    universe: str | None = None           # also every stock in this universe (config/universes), e.g. ds30
    quality: str | None = None            # keep only stocks passing this profile's quality filter today
    portfolio: PlanPortfolio | None = None    # shared capital; None = each stock on its own with its own capital
    liquidity: PlanLiquidity = PlanLiquidity()
    in_sample_until: date | None = None   # optional: stats split into tuning (up to here) and test periods

    @model_validator(mode="after")
    def _rank_needs_strategy(self):
        if self.portfolio and self.portfolio.rank_by == "score" and not self.entry.strategy:
            raise ValueError("portfolio.rank_by 'score' needs an entry strategy; rank by a column instead, e.g. vol_x_20")
        return self

    @field_validator("codes")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [c.strip().upper() for c in v]


def set_plan_value(data: dict, path: str, value) -> None:
    """data['exit']['stop_pct'] = value for path 'exit.stop_pct'; numbers index lists ('entry.when.1.2')."""
    node = data
    *parents, leaf = path.strip().split(".")
    for key in parents:
        if isinstance(node, list):
            node = node[int(key)]
        else:
            node = node.setdefault(key, {})
    if isinstance(node, list):
        node[int(leaf)] = value
    else:
        node[leaf] = value


def plan_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    return p if p.suffix in (".yaml", ".yml") else CONFIG_DIR / "plans" / f"{name_or_path}.yaml"


def read_plan_data(name_or_path: str) -> dict:
    path = plan_path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"No plan '{name_or_path}' ({path}). Saved plans: {', '.join(list_plans()) or 'none'}")
    return _read_yaml(path)


def load_plan(name_or_path: str) -> TradePlan:
    return TradePlan.model_validate(read_plan_data(name_or_path))


def list_plans() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "plans").glob("*.yaml"))


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: Path | None = None) -> Settings:
    """settings.yaml, plus secrets.yaml (git-ignored), plus environment overrides."""
    data = _read_yaml(path or CONFIG_DIR / "settings.yaml")
    secrets = _read_secrets()
    tg = {**data.get("telegram", {}), **{k: v for k, v in (secrets.get("telegram") or {}).items() if v}}
    for key, env in [("bot_token", "DSE_TELEGRAM_BOT_TOKEN"), ("chat_id", "DSE_TELEGRAM_CHAT_ID")]:
        if os.environ.get(env):
            tg[key] = os.environ[env]
    data["telegram"] = tg
    ai = {**data.get("anthropic", {}), **{k: v for k, v in (secrets.get("anthropic") or {}).items() if v}}
    data["anthropic"] = ai
    return Settings.model_validate(data)


def _read_secrets() -> dict:
    path = CONFIG_DIR / "secrets.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, str):
        # Just the bot token pasted on its own line: accept it
        return {"telegram": {"bot_token": data.strip()}}
    return data or {}


def save_secret(section: str, key: str, value: str) -> Path:
    """Write one value into config/secrets.yaml, keeping the rest."""
    path = CONFIG_DIR / "secrets.yaml"
    data = _read_secrets()
    data.setdefault(section, {})[key] = value
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return path


def load_universe(name: str) -> Universe:
    return Universe.model_validate(_read_yaml(CONFIG_DIR / "universes" / f"{name}.yaml"))


def load_profile(name: str) -> Profile:
    return Profile.model_validate(_read_yaml(CONFIG_DIR / "profiles" / f"{name}.yaml"))


def list_profiles(settings: Settings | None = None) -> list[str]:
    """Profile names: settings.report.profiles order if set, else all profiles alphabetically."""
    if settings and settings.report.profiles:
        return list(settings.report.profiles)
    return sorted(p.stem for p in (CONFIG_DIR / "profiles").glob("*.yaml"))
