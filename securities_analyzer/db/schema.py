import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY,
  trade_date TEXT NOT NULL,
  settlement_date TEXT NOT NULL,
  maturity_date TEXT NOT NULL,
  isin TEXT NOT NULL,
  original_maturity_days INTEGER NOT NULL,
  currency TEXT NOT NULL,
  coupon_pct REAL NOT NULL,
  remaining_maturity_days INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  transaction_count INTEGER NOT NULL,
  nominal_per_unit REAL NOT NULL,
  min_price REAL NOT NULL,
  max_price REAL NOT NULL,
  wavg_price REAL NOT NULL,
  turnover REAL NOT NULL,
  min_yield_pct REAL NOT NULL,
  max_yield_pct REAL NOT NULL,
  avg_yield_pct REAL NOT NULL,
  source_year INTEGER NOT NULL,
  settlement_lag_days INTEGER NOT NULL,
  quality_flag TEXT NOT NULL,
  UNIQUE (trade_date, settlement_date, isin)
);
CREATE INDEX IF NOT EXISTS ix_trades_trade_date ON trades (trade_date);
CREATE INDEX IF NOT EXISTS ix_trades_isin ON trades (isin);
CREATE INDEX IF NOT EXISTS ix_trades_remaining ON trades (remaining_maturity_days);
CREATE INDEX IF NOT EXISTS ix_trades_avg_yield ON trades (avg_yield_pct);
CREATE INDEX IF NOT EXISTS ix_trades_source_year ON trades (source_year);

CREATE VIEW IF NOT EXISTS securities AS
SELECT isin,
       MAX(maturity_date) AS maturity_date,
       MAX(currency) AS currency,
       MAX(coupon_pct) AS coupon_pct,
       MAX(nominal_per_unit) AS nominal_per_unit,
       MAX(original_maturity_days) AS original_maturity_days,
       MIN(trade_date) AS first_trade,
       MAX(trade_date) AS last_trade,
       COUNT(*) AS trade_rows
FROM trades GROUP BY isin;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL, pivot_json TEXT);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(saved_queries)")}
    if "pivot_json" not in cols:
        conn.execute("ALTER TABLE saved_queries ADD COLUMN pivot_json TEXT")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
