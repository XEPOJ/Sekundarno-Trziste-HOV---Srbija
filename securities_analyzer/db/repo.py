import sqlite3
from dataclasses import dataclass

from ..ingest.models import TradeRow
from ..ingest.quality import quality_flag

_INSERT = """
INSERT INTO trades (
  trade_date, settlement_date, maturity_date, isin, original_maturity_days, currency,
  coupon_pct, remaining_maturity_days, quantity, transaction_count, nominal_per_unit,
  min_price, max_price, wavg_price, turnover, min_yield_pct, max_yield_pct, avg_yield_pct,
  source_year, settlement_lag_days, quality_flag
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


class KeyCollisionError(Exception):
    """A row's business key already exists under a different source year."""


@dataclass
class YearResult:
    year: int
    added: int
    removed: int
    unchanged: int


def _values(r: TradeRow, year: int) -> tuple:
    return (
        r.trade_date.isoformat(), r.settlement_date.isoformat(), r.maturity_date.isoformat(),
        r.isin, r.original_maturity_days, r.currency, r.coupon_pct, r.remaining_maturity_days,
        r.quantity, r.transaction_count, r.nominal_per_unit, r.min_price, r.max_price,
        r.wavg_price, r.turnover, r.min_yield_pct, r.max_yield_pct, r.avg_yield_pct,
        year, (r.settlement_date - r.trade_date).days, quality_flag(r),
    )


def replace_year(conn: sqlite3.Connection, year: int, rows: list[TradeRow]) -> YearResult:
    """Replace every row of `source_year == year` in ONE transaction."""
    old = {
        (r["trade_date"], r["settlement_date"], r["isin"])
        for r in conn.execute(
            "SELECT trade_date, settlement_date, isin FROM trades WHERE source_year = ?", (year,))
    }
    new = {(r.trade_date.isoformat(), r.settlement_date.isoformat(), r.isin) for r in rows}
    try:
        with conn:
            conn.execute("DELETE FROM trades WHERE source_year = ?", (year,))
            conn.executemany(_INSERT, [_values(r, year) for r in rows])
    except sqlite3.IntegrityError as e:
        raise KeyCollisionError(f"Kolizija ključa pri zameni godine {year}: {e}") from e
    return YearResult(year, added=len(new - old), removed=len(old - new), unchanged=len(new & old))


def stored_count(conn: sqlite3.Connection, year: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM trades WHERE source_year = ?", (year,)).fetchone()[0]


def last_source_year(conn: sqlite3.Connection) -> int | None:
    return conn.execute("SELECT MAX(source_year) FROM trades").fetchone()[0]


def data_range(conn: sqlite3.Connection) -> tuple[str | None, str | None, int]:
    r = conn.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM trades").fetchone()
    return (r[0], r[1], r[2])


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
