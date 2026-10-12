import sqlite3

from .builder import build_where
from .expressions import BUCKET_NAMES as _BUCKET_NAMES
from .expressions import BUCKET_ORDER_SQL as _BUCKET_CASE
from .expressions import PERIOD_SQL as _PERIOD
from .filters import FilterSpec

ROW_COLUMNS = (
    "trade_date", "settlement_date", "isin", "currency", "coupon_pct", "maturity_date",
    "remaining_maturity_days", "quantity", "transaction_count", "wavg_price",
    "min_yield_pct", "max_yield_pct", "avg_yield_pct", "turnover", "quality_flag",
)
SORTABLE = frozenset(ROW_COLUMNS)

_EXTREME_SORT = frozenset({"trade_date", "highest_pct", "lowest_pct", "range_pct"})


def _all(conn: sqlite3.Connection, sql: str, params: list) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def fetch_rows(conn, spec: FilterSpec, *, sort: str = "trade_date", order: str = "desc",
               limit: int = 100, offset: int = 0) -> dict:
    if sort not in SORTABLE:
        raise ValueError(f"nedozvoljena kolona za sortiranje: {sort!r}")
    where, params = build_where(spec)
    total = conn.execute(f"SELECT COUNT(*) FROM trades WHERE {where}", params).fetchone()[0]
    direction = "ASC" if order == "asc" else "DESC"
    rows = _all(
        conn,
        f"SELECT {', '.join(ROW_COLUMNS)} FROM trades WHERE {where} "
        f"ORDER BY {sort} {direction}, id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "rows": rows}


def kpis(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    return _all(conn, f"""
        SELECT currency,
               SUM(turnover) AS turnover,
               SUM(quantity) AS quantity,
               SUM(transaction_count) AS transactions,
               COUNT(DISTINCT isin) AS isins,
               COUNT(DISTINCT trade_date) AS active_days,
               COUNT(*) AS row_count,
               SUM(avg_yield_pct * turnover) / SUM(turnover) AS weighted_yield_pct
        FROM trades WHERE {where} GROUP BY currency ORDER BY currency""", params)


def securities_summary(conn, spec: FilterSpec) -> list[dict]:
    """One row per ISIN for the whole filtered period, biggest turnover first.

    The yield is weighted by turnover (same as the KPI cards); `avg_daily_yield_pct` is the plain mean of
    the daily averages. Turnover is in the security's own currency, so nothing is summed across currencies.
    """
    where, params = build_where(spec)
    return _all(conn, f"""
        SELECT isin, currency,
               MAX(coupon_pct) AS coupon_pct,
               MAX(maturity_date) AS maturity_date,
               COUNT(DISTINCT trade_date) AS active_days,
               SUM(transaction_count) AS transactions,
               SUM(quantity) AS quantity,
               SUM(turnover) AS turnover,
               SUM(avg_yield_pct * turnover) / SUM(turnover) AS weighted_yield_pct,
               AVG(avg_yield_pct) AS avg_daily_yield_pct,
               MIN(min_yield_pct) AS min_yield_pct,
               MAX(max_yield_pct) AS max_yield_pct,
               MIN(trade_date) AS first_trade,
               MAX(trade_date) AS last_trade
        FROM trades WHERE {where}
        GROUP BY isin, currency ORDER BY turnover DESC, isin""", params)


def yield_timeseries(conn, spec: FilterSpec, granularity: str) -> list[dict]:
    if granularity not in _PERIOD:
        raise ValueError(f"nepoznata granulacija: {granularity!r}")
    where, params = build_where(spec)
    period = _PERIOD[granularity]
    return _all(conn, f"""
        SELECT {period} AS period, currency,
               SUM(avg_yield_pct * turnover) / SUM(turnover) AS weighted_yield_pct,
               SUM(turnover) AS turnover
        FROM trades WHERE {where} GROUP BY period, currency ORDER BY period, currency""", params)


def scatter(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    return _all(conn, f"""
        SELECT trade_date, isin, currency, remaining_maturity_days, avg_yield_pct, turnover
        FROM trades WHERE {where} ORDER BY trade_date, id LIMIT 20000""", params)


def maturity_buckets(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    rows = _all(conn, f"""
        SELECT {_BUCKET_CASE} AS bucket_order, currency,
               SUM(turnover) AS turnover, COUNT(*) AS row_count
        FROM trades WHERE {where} GROUP BY bucket_order, currency
        ORDER BY bucket_order, currency""", params)
    for r in rows:
        r["bucket"] = _BUCKET_NAMES[r.pop("bucket_order")]
    return rows


def daily_extremes(conn, spec: FilterSpec, *, sort_by: str = "trade_date",
                   order: str = "desc", limit: int = 500) -> list[dict]:
    if sort_by not in _EXTREME_SORT:
        raise ValueError(f"nedozvoljeno sortiranje: {sort_by!r}")
    where, params = build_where(spec)
    direction = "ASC" if order == "asc" else "DESC"
    return _all(conn, f"""
        WITH f AS (
          SELECT trade_date, currency, isin, min_yield_pct, max_yield_pct, turnover
          FROM trades WHERE {where}),
        hi AS (
          SELECT trade_date, currency, isin, max_yield_pct,
                 ROW_NUMBER() OVER (PARTITION BY trade_date, currency
                                    ORDER BY max_yield_pct DESC, turnover DESC, isin ASC) AS rn
          FROM f),
        lo AS (
          SELECT trade_date, currency, isin, min_yield_pct,
                 ROW_NUMBER() OVER (PARTITION BY trade_date, currency
                                    ORDER BY min_yield_pct ASC, turnover DESC, isin ASC) AS rn
          FROM f)
        SELECT hi.trade_date AS trade_date, hi.currency AS currency,
               hi.max_yield_pct AS highest_pct, hi.isin AS highest_isin,
               lo.min_yield_pct AS lowest_pct, lo.isin AS lowest_isin,
               ROUND(hi.max_yield_pct - lo.min_yield_pct, 4) AS range_pct
        FROM hi JOIN lo
          ON hi.trade_date = lo.trade_date AND hi.currency = lo.currency AND lo.rn = 1
        WHERE hi.rn = 1
        ORDER BY {sort_by} {direction}, trade_date, currency
        LIMIT ?""", [*params, limit])


def quality_count(conn, spec: FilterSpec) -> int:
    where, params = build_where(spec)
    return conn.execute(
        f"SELECT COUNT(*) FROM trades WHERE ({where}) AND quality_flag != 'OK'", params
    ).fetchone()[0]


def list_securities(conn) -> list[dict]:
    return _all(conn, "SELECT isin, currency, coupon_pct, maturity_date, original_maturity_days, "
                      "first_trade, last_trade FROM securities ORDER BY currency, maturity_date, isin", [])
