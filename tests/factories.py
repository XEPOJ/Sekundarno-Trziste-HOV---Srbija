from datetime import date

from securities_analyzer.db.repo import replace_year
from securities_analyzer.ingest.models import EXPECTED_HEADER, TradeRow


def make_row(**kw) -> TradeRow:
    base = dict(
        trade_date=date(2023, 6, 15), settlement_date=date(2023, 6, 15),
        maturity_date=date(2030, 7, 30), isin="RSMFRSD00001",
        original_maturity_days=2556, currency="RSD", coupon_pct=5.0,
        remaining_maturity_days=2600, quantity=100, transaction_count=1,
        nominal_per_unit=10000.0, min_price=10000.0, max_price=10000.0,
        wavg_price=10000.0, turnover=1000000.0,
        min_yield_pct=5.0, max_yield_pct=5.0, avg_yield_pct=5.0,
    )
    if "turnover" in kw and "quantity" not in kw and "wavg_price" not in kw:
        t = kw["turnover"]
        base.update(quantity=1, wavg_price=t, min_price=t, max_price=t)
    if "avg_yield_pct" in kw and "min_yield_pct" not in kw and "max_yield_pct" not in kw:
        base.update(min_yield_pct=kw["avg_yield_pct"], max_yield_pct=kw["avg_yield_pct"])
    base.update(kw)
    return TradeRow(**base)


def rows_to_csv(rows) -> bytes:
    """Serialize rows the way NBS does: ', '-separated Cyrillic header, plain ',' rows, BOM."""
    lines = [", ".join(EXPECTED_HEADER)]
    for r in rows:
        lines.append(",".join([
            r.trade_date.isoformat(), r.settlement_date.isoformat(), r.maturity_date.isoformat(),
            r.isin, str(r.original_maturity_days), r.currency, f"{r.coupon_pct:.2f}",
            str(r.remaining_maturity_days), str(r.quantity), str(r.transaction_count),
            f"{r.nominal_per_unit:.0f}", f"{r.min_price:.2f}", f"{r.max_price:.2f}",
            f"{r.wavg_price:.2f}", f"{r.turnover:.2f}", f"{r.min_yield_pct:.2f}",
            f"{r.max_yield_pct:.2f}", f"{r.avg_yield_pct:.2f}",
        ]))
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def load_rows(conn, rows):
    """Insert rows grouped by settlement year (mirrors NBS yearly files)."""
    by_year: dict[int, list] = {}
    for r in rows:
        by_year.setdefault(r.settlement_date.year, []).append(r)
    for year, rs in by_year.items():
        replace_year(conn, year, rs)
