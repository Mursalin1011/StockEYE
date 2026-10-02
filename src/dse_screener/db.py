"""SQLite storage. Keep SQL in this module so it can be swapped for Postgres later."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .sources.base import PRICE_COLUMNS

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_prices (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,          -- ISO yyyy-mm-dd
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    ltp         REAL,
    ycp         REAL,                   -- yesterday's close as published by DSE (not adjusted)
    trades      INTEGER,
    value_mn    REAL,
    volume      INTEGER,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS ix_daily_prices_date ON daily_prices(date);

CREATE TABLE IF NOT EXISTS companies (
    code                TEXT PRIMARY KEY,
    name                TEXT,
    sector              TEXT,
    category            TEXT,
    instrument_type     TEXT,
    listing_year        INTEGER,
    face_value          REAL,
    outstanding_shares  REAL,
    authorized_mn       REAL,
    paid_up_mn          REAL,
    market_cap_mn       REAL,
    free_float_mcap_mn  REAL,
    year_end            TEXT,
    last_agm            TEXT,
    trailing_pe         REAL,
    pe_unaudited        REAL,
    short_loan_mn       REAL,
    long_loan_mn        REAL,
    operational_status  TEXT,
    fetched_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dividend_history (
    code        TEXT NOT NULL,
    year        INTEGER NOT NULL,       -- financial year the dividend is for
    cash_pct    REAL NOT NULL,          -- % of face value
    stock_pct   REAL NOT NULL,          -- bonus shares per 100 held
    PRIMARY KEY (code, year)
);

-- Company pages only show the last few months, so this builds up over time.
CREATE TABLE IF NOT EXISTS shareholding (
    code        TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    sponsor     REAL,
    govt        REAL,
    institute   REAL,
    foreign_pct REAL,
    public      REAL,
    PRIMARY KEY (code, as_of)
);

CREATE TABLE IF NOT EXISTS annual_financials (
    code            TEXT NOT NULL,
    year            INTEGER NOT NULL,
    eps             REAL,               -- restated where available (bonus-adjusted)
    nav             REAL,
    profit_mn       REAL,
    pe              REAL,               -- year-end P/E
    dividend_text   TEXT,               -- e.g. "17.50, 17.50%B"
    dividend_yield  REAL,
    PRIMARY KEY (code, year)
);

CREATE TABLE IF NOT EXISTS news (
    code        TEXT NOT NULL,
    post_date   TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    UNIQUE (code, post_date, title, body)
);
CREATE INDEX IF NOT EXISTS ix_news_code_date ON news(code, post_date);

CREATE TABLE IF NOT EXISTS corporate_actions (
    code            TEXT NOT NULL,
    record_date     TEXT NOT NULL,
    ex_date         TEXT,               -- first trading day after the record date
    cash_pct        REAL NOT NULL,
    stock_pct       REAL NOT NULL,
    face_value      REAL,
    ref_close       REAL,               -- last close before the record date
    price_factor    REAL,               -- (ref - cash) / (1 + bonus) / ref
    bonus_factor    REAL,               -- 1 / (1 + bonus); used when cash isn't adjusted
    volume_factor   REAL,               -- 1 + bonus; multiplies volume before ex_date
    ex_open         REAL,               -- actual open on ex_date, to sanity-check the factor
    fiscal_year     INTEGER,
    revised         INTEGER NOT NULL DEFAULT 0,  -- 1 = amounts taken from the final approved dividend
    news_date       TEXT,
    PRIMARY KEY (code, record_date)
);

CREATE TABLE IF NOT EXISTS screen_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    profile         TEXT NOT NULL,
    config_json     TEXT NOT NULL,      -- the profile as used, so results stay explainable
    universe_size   INTEGER,
    passed_quality  INTEGER
);

CREATE TABLE IF NOT EXISTS screen_signals (
    run_id      INTEGER NOT NULL REFERENCES screen_runs(run_id),
    code        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    role        TEXT NOT NULL,          -- primary | confirm
    score       REAL NOT NULL,
    weighted    REAL NOT NULL,
    reasons     TEXT NOT NULL,          -- JSON list
    metrics     TEXT NOT NULL           -- JSON object
);

CREATE TABLE IF NOT EXISTS screen_picks (
    run_id      INTEGER NOT NULL REFERENCES screen_runs(run_id),
    rank        INTEGER NOT NULL,
    code        TEXT NOT NULL,
    final_score REAL NOT NULL,
    strategies  TEXT NOT NULL,          -- JSON list
    reasons     TEXT NOT NULL           -- JSON list
);

CREATE TABLE IF NOT EXISTS research_docs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256      TEXT NOT NULL UNIQUE,
    url         TEXT,
    file_path   TEXT NOT NULL,          -- local copy under research.store
    filename    TEXT NOT NULL,
    source      TEXT,                   -- matched rule in config/research/sources.yaml
    publisher   TEXT,
    doc_type    TEXT NOT NULL,          -- newsflash | market_review | macro | company | sector | other
    published   TEXT,                   -- YYYY-MM-DD
    pages       INTEGER,
    text        TEXT,                   -- extracted text (for search and code matching)
    codes       TEXT NOT NULL,          -- JSON list of DSE codes mentioned
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    as_of       TEXT NOT NULL,          -- latest trading day in StockEYE's data at review time
    model       TEXT NOT NULL,
    doc_ids     TEXT NOT NULL,          -- JSON list
    review      TEXT NOT NULL,          -- JSON (research.review.Review)
    usage       TEXT,                   -- JSON token usage
    guide_sha   TEXT                    -- version of ANALYST.md used
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id     INTEGER NOT NULL,
    as_of         TEXT NOT NULL,
    code          TEXT NOT NULL,
    stance        TEXT NOT NULL,        -- bullish | bearish | neutral
    horizon_days  INTEGER NOT NULL,
    confidence    REAL NOT NULL,        -- 0-100
    thesis        TEXT,
    ret           REAL,                 -- filled by `research score` once the horizon has passed
    bench         REAL,
    excess        REAL,
    correct       INTEGER,              -- 1/0; NULL for neutral or not yet scored
    scored_at     TEXT
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    source      TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    rows        INTEGER NOT NULL,
    status      TEXT NOT NULL,          -- ok | empty | incomplete | error
    message     TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(df: pd.DataFrame) -> list[tuple]:
    """DataFrame -> tuples with NaN/NA as None, as sqlite expects."""
    return list(df.astype(object).where(df.notna(), None).itertuples(index=False, name=None))


class Database:
    def __init__(self, path: Path, check_same_thread: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        # The dashboard reads from Streamlit's worker threads: it passes check_same_thread=False
        self.conn = sqlite3.connect(path, check_same_thread=check_same_thread, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def _upsert(self, table: str, df: pd.DataFrame, keys: list[str]) -> int:
        if df.empty:
            return 0
        cols = list(df.columns)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
        conflict = f"ON CONFLICT({', '.join(keys)}) DO " + (f"UPDATE SET {updates}" if updates else "NOTHING")
        with self.conn:
            self.conn.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) {conflict}",
                _clean(df),
            )
        return len(df)

    def _query(self, sql: str, params: list | tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.conn, params=params)

    @staticmethod
    def _in(codes: list[str] | None, col: str = "code") -> tuple[str, list]:
        if not codes:
            return "", []
        return f" AND {col} IN ({', '.join('?' * len(codes))})", list(codes)

    # --- prices -------------------------------------------------------------

    def upsert_prices(self, df: pd.DataFrame, source: str) -> int:
        rows = df[PRICE_COLUMNS].copy()
        rows["date"] = rows["date"].astype(str)
        rows["source"], rows["fetched_at"] = source, _now()
        return self._upsert("daily_prices", rows, ["code", "date"])

    def load_prices(
        self, codes: list[str] | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        where, params = self._in(codes)
        if start:
            where += " AND date >= ?"
            params.append(start.isoformat())
        if end:
            where += " AND date <= ?"
            params.append(end.isoformat())
        df = self._query(f"SELECT * FROM daily_prices WHERE 1=1{where} ORDER BY code, date", params)
        df["date"] = pd.to_datetime(df["date"])
        return df

    def market_totals(self) -> pd.DataFrame:
        """Whole-market traded value and volume per day (all instruments)."""
        df = self._query("SELECT date, SUM(value_mn) AS mkt_value_mn, SUM(volume) AS mkt_volume "
                         "FROM daily_prices GROUP BY date ORDER BY date")
        df["date"] = pd.to_datetime(df["date"])
        return df

    def rows_per_day(self) -> pd.Series:
        df = self._query("SELECT date, COUNT(*) AS n FROM daily_prices GROUP BY date ORDER BY date")
        return df.set_index("date")["n"]

    def date_range(self) -> tuple[str | None, str | None]:
        return self.conn.execute("SELECT MIN(date), MAX(date) FROM daily_prices").fetchone()

    # --- fundamentals -------------------------------------------------------

    def save_company(self, profile) -> None:
        """Store a CompanyProfile (see sources.dse_company)."""
        code = profile.code
        info = pd.DataFrame([{**profile.info, "fetched_at": _now()}])
        self._upsert("companies", info, ["code"])
        if profile.dividends:
            self._upsert("dividend_history", pd.DataFrame(profile.dividends).assign(code=code), ["code", "year"])
        if profile.shareholding:
            sh = pd.DataFrame(profile.shareholding).rename(columns={"foreign": "foreign_pct"}).assign(code=code)
            self._upsert("shareholding", sh, ["code", "as_of"])
        if profile.annual:
            self._upsert("annual_financials", pd.DataFrame(profile.annual).assign(code=code), ["code", "year"])

    def load_companies(self, codes: list[str] | None = None) -> pd.DataFrame:
        where, params = self._in(codes)
        return self._query(f"SELECT * FROM companies WHERE 1=1{where} ORDER BY code", params)

    def load_table(self, table: str, codes: list[str] | None = None) -> pd.DataFrame:
        assert table in {"dividend_history", "shareholding", "annual_financials"}
        where, params = self._in(codes)
        return self._query(f"SELECT * FROM {table} WHERE 1=1{where}", params)

    # --- news & corporate actions -------------------------------------------

    def upsert_news(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        before = self.conn.total_changes
        rows = df.assign(post_date=df["post_date"].astype(str))
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO news (code, post_date, title, body) VALUES (?, ?, ?, ?)",
                _clean(rows[["code", "post_date", "title", "body"]]),
            )
        return self.conn.total_changes - before

    def load_news(self, codes: list[str] | None = None) -> pd.DataFrame:
        where, params = self._in(codes)
        df = self._query(f"SELECT * FROM news WHERE 1=1{where} ORDER BY code, post_date", params)
        df["post_date"] = pd.to_datetime(df["post_date"])
        return df

    def replace_corporate_actions(self, df: pd.DataFrame, codes: list[str]) -> int:
        where, params = self._in(codes)
        with self.conn:
            self.conn.execute(f"DELETE FROM corporate_actions WHERE 1=1{where}", params)
        return self._upsert("corporate_actions", df, ["code", "record_date"])

    def load_corporate_actions(self, codes: list[str] | None = None) -> pd.DataFrame:
        where, params = self._in(codes)
        df = self._query(f"SELECT * FROM corporate_actions WHERE 1=1{where} ORDER BY code, record_date", params)
        df["ex_date"] = pd.to_datetime(df["ex_date"])
        return df

    # --- screen runs --------------------------------------------------------

    def save_screen(self, result, profile_json: str) -> int:
        """Store a ScreenResult (see engine.py). Returns run_id."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO screen_runs (run_at, as_of, profile, config_json, universe_size, passed_quality) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), result.as_of.isoformat(), result.profile, profile_json,
                 result.universe_size, result.universe_size - len(result.excluded)),
            )
            run_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO screen_signals (run_id, code, strategy, role, score, weighted, reasons, metrics) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, s.code, s.strategy, s.role, s.score, s.weighted, json.dumps(s.reasons),
                  json.dumps(s.metrics)) for s in result.signals.itertuples()],
            )
            self.conn.executemany(
                "INSERT INTO screen_picks (run_id, rank, code, final_score, strategies, reasons) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(run_id, i + 1, p.code, p.final_score, json.dumps(p.strategies), json.dumps(p.reasons))
                 for i, p in enumerate(result.picks.itertuples())],
            )
        return run_id

    def load_runs(self) -> pd.DataFrame:
        """Latest run per (as_of, profile)."""
        return self._query(
            "SELECT r.* FROM screen_runs r JOIN (SELECT as_of, profile, MAX(run_id) AS run_id "
            "FROM screen_runs GROUP BY as_of, profile) l USING (run_id) ORDER BY as_of DESC, profile"
        )

    def load_run_picks(self, run_ids: list[int]) -> pd.DataFrame:
        if not run_ids:
            return pd.DataFrame(columns=["run_id", "rank", "code", "final_score", "strategies", "reasons"])
        q = f"SELECT * FROM screen_picks WHERE run_id IN ({', '.join('?' * len(run_ids))}) ORDER BY run_id, rank"
        df = self._query(q, run_ids)
        for col in ("strategies", "reasons"):
            df[col] = df[col].map(json.loads)
        return df

    def load_run_signals(self, run_ids: list[int]) -> pd.DataFrame:
        if not run_ids:
            return pd.DataFrame(columns=["run_id", "code", "strategy", "role", "score", "weighted", "reasons", "metrics"])
        q = f"SELECT * FROM screen_signals WHERE run_id IN ({', '.join('?' * len(run_ids))})"
        df = self._query(q, run_ids)
        for col in ("reasons", "metrics"):
            df[col] = df[col].map(json.loads)
        return df

    # --- ingest log ---------------------------------------------------------

    def log_ingest(
        self, source: str, start: date, end: date, rows: int, status: str, message: str = ""
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO ingest_log (run_at, source, start_date, end_date, rows, status, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_now(), source, start.isoformat(), end.isoformat(), rows, status, message),
            )

    def completed_chunks(self, source: str) -> set[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT start_date, end_date FROM ingest_log WHERE source = ? AND status IN ('ok', 'empty')",
            (source,),
        ).fetchall()
        return {(s, e) for s, e in rows}
