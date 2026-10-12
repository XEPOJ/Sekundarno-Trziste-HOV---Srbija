from .filters import YEAR_DAYS, FilterSpec, Range

_YIELD_COL = {"avg": "avg_yield_pct", "min": "min_yield_pct", "max": "max_yield_pct"}


def _range(col: str, rng: Range, scale: float, clauses: list, params: list) -> None:
    if rng.min is not None:
        clauses.append(f"{col} {'>' if rng.min_exclusive else '>='} ?")
        params.append(rng.min * scale)
    if rng.max is not None:
        clauses.append(f"{col} {'<' if rng.max_exclusive else '<='} ?")
        params.append(rng.max * scale)


def build_where(spec: FilterSpec) -> tuple[str, list]:
    """Return (SQL fragment over `trades`, params). Only whitelisted identifiers are interpolated."""
    clauses: list[str] = []
    params: list = []
    if spec.date_from:
        clauses.append("trade_date >= ?")
        params.append(spec.date_from.isoformat())
    if spec.date_to:
        clauses.append("trade_date <= ?")
        params.append(spec.date_to.isoformat())
    _range(_YIELD_COL[spec.yield_basis], spec.yield_pct, 1, clauses, params)
    _range("remaining_maturity_days", spec.remaining_maturity_years, YEAR_DAYS, clauses, params)
    _range("original_maturity_days", spec.original_maturity_years, YEAR_DAYS, clauses, params)
    _range("coupon_pct", spec.coupon_pct, 1, clauses, params)
    _range("settlement_lag_days", spec.settlement_lag_days, 1, clauses, params)
    if spec.turnover_min is not None:
        clauses.append("turnover >= ?")
        params.append(spec.turnover_min)
    if spec.currency:
        clauses.append(f"currency IN ({','.join('?' * len(spec.currency))})")
        params.extend(spec.currency)
    if spec.isin:
        clauses.append(f"isin IN ({','.join('?' * len(spec.isin))})")
        params.extend(spec.isin)
    return (" AND ".join(clauses) or "1=1"), params
