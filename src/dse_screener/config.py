"""Load and validate YAML config. All tunable numbers live in config/, not in code."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, field_validator

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
