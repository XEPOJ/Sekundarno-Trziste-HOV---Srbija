from datetime import date

import pytest
from pydantic import ValidationError

from securities_analyzer.query.builder import build_where
from securities_analyzer.query.filters import FilterSpec, Range
from tests.factories import load_rows, make_row


def pick(conn, spec, col="trade_date"):
    where, params = build_where(spec)
    return [r[0] for r in conn.execute(f"SELECT {col} FROM trades WHERE {where} ORDER BY {col}, id", params)]


def test_empty_spec_matches_everything():
    assert build_where(FilterSpec()) == ("1=1", [])


def test_dates_are_inclusive_on_both_ends(conn):
    days = [date(2023, 2, 1), date(2023, 2, 2), date(2023, 3, 5), date(2023, 3, 6)]
    load_rows(conn, [make_row(trade_date=d, settlement_date=d) for d in days])
    spec = FilterSpec(date_from=date(2023, 2, 2), date_to=date(2023, 3, 5))
    assert pick(conn, spec) == ["2023-02-02", "2023-03-05"]


def test_yield_strict_vs_inclusive(conn):
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", avg_yield_pct=y) for i, y in enumerate([3.4, 3.5, 3.6], 1)])
    strict = FilterSpec(yield_pct=Range(min=3.5, min_exclusive=True))
    incl = FilterSpec(yield_pct=Range(min=3.5))
    assert pick(conn, strict, "avg_yield_pct") == [3.6]
    assert pick(conn, incl, "avg_yield_pct") == [3.5, 3.6]


def test_yield_basis_max(conn):
    load_rows(conn, [make_row(min_yield_pct=3.0, avg_yield_pct=3.5, max_yield_pct=4.0)])
    assert pick(conn, FilterSpec(yield_pct=Range(min=3.9), yield_basis="max")) != []
    assert pick(conn, FilterSpec(yield_pct=Range(min=3.9), yield_basis="avg")) == []
    assert pick(conn, FilterSpec(yield_pct=Range(max=3.1), yield_basis="min")) != []


def test_remaining_maturity_three_years_strict(conn):
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", remaining_maturity_days=d)
                     for i, d in enumerate([1094, 1095, 1096], 1)])
    strict = FilterSpec(remaining_maturity_years=Range(min=3, min_exclusive=True))
    incl = FilterSpec(remaining_maturity_years=Range(min=3))
    assert pick(conn, strict, "remaining_maturity_days") == [1096]
    assert pick(conn, incl, "remaining_maturity_days") == [1095, 1096]


def test_fractional_years_boundaries_are_exact(conn):
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", remaining_maturity_days=d)
                     for i, d in enumerate([510, 511, 512], 1)])
    col = "remaining_maturity_days"
    assert pick(conn, FilterSpec(remaining_maturity_years=Range(min=1.4, min_exclusive=True)), col) == [512]
    assert pick(conn, FilterSpec(remaining_maturity_years=Range(min=1.4)), col) == [511, 512]
    assert pick(conn, FilterSpec(remaining_maturity_years=Range(max=1.4, max_exclusive=True)), col) == [510]


def test_original_maturity_and_coupon_and_lag(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD00001", original_maturity_days=730, coupon_pct=1.7),
        make_row(isin="RSMFRSD00002", original_maturity_days=3650, coupon_pct=5.5,
                 settlement_date=date(2023, 6, 19)),
    ])
    assert pick(conn, FilterSpec(original_maturity_years=Range(min=5)), "isin") == ["RSMFRSD00002"]
    assert pick(conn, FilterSpec(coupon_pct=Range(max=2)), "isin") == ["RSMFRSD00001"]
    assert pick(conn, FilterSpec(settlement_lag_days=Range(min=1)), "isin") == ["RSMFRSD00002"]


def test_currency_isin_turnover(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD00001", currency="RSD", turnover=100.0),
        make_row(isin="RSMFRSD00002", currency="EUR", turnover=900.0),
    ])
    assert pick(conn, FilterSpec(currency=["EUR"]), "isin") == ["RSMFRSD00002"]
    assert pick(conn, FilterSpec(isin=["RSMFRSD00001"]), "isin") == ["RSMFRSD00001"]
    assert pick(conn, FilterSpec(turnover_min=500), "isin") == ["RSMFRSD00002"]


def _isins(n):
    return [f"RSMFRSD0000{i}" for i in range(1, n + 1)]


def test_quantity_range_strict_and_inclusive(conn):
    load_rows(conn, [make_row(isin=i, quantity=q) for i, q in zip(_isins(3), [999, 1000, 1001])])
    assert pick(conn, FilterSpec(quantity=Range(min=1000)), "quantity") == [1000, 1001]
    assert pick(conn, FilterSpec(quantity=Range(min=1000, min_exclusive=True)), "quantity") == [1001]
    assert pick(conn, FilterSpec(quantity=Range(max=1000)), "quantity") == [999, 1000]
    assert pick(conn, FilterSpec(quantity=Range(max=1000, max_exclusive=True)), "quantity") == [999]
    assert pick(conn, FilterSpec(quantity=Range(min=1000, max=1000)), "quantity") == [1000]


def test_turnover_range_replaces_the_single_minimum(conn):
    load_rows(conn, [make_row(isin=i, turnover=t) for i, t in zip(_isins(3), [100.0, 500.0, 900.0])])
    assert pick(conn, FilterSpec(turnover=Range(min=500)), "turnover") == [500.0, 900.0]
    assert pick(conn, FilterSpec(turnover=Range(min=500, max=900, min_exclusive=True)), "turnover") == [900.0]
    assert pick(conn, FilterSpec(turnover=Range(max=500, max_exclusive=True)), "turnover") == [100.0]
    # the old single minimum keeps working for saved queries
    assert pick(conn, FilterSpec(turnover_min=500), "turnover") == [500.0, 900.0]


def test_min_price_and_max_price_are_separate_ranges(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD00001", min_price=9000.0, max_price=9500.0, wavg_price=9200.0),
        make_row(isin="RSMFRSD00002", min_price=9800.0, max_price=10200.0, wavg_price=10000.0),
        make_row(isin="RSMFRSD00003", min_price=10100.0, max_price=11000.0, wavg_price=10500.0),
    ])
    assert pick(conn, FilterSpec(min_price=Range(min=9800)), "isin") == ["RSMFRSD00002", "RSMFRSD00003"]
    assert pick(conn, FilterSpec(max_price=Range(max=10200)), "isin") == ["RSMFRSD00001", "RSMFRSD00002"]
    assert pick(conn, FilterSpec(min_price=Range(min=9800), max_price=Range(max=10200)), "isin") == ["RSMFRSD00002"]
    assert pick(conn, FilterSpec(min_price=Range(min=9800, min_exclusive=True)), "isin") == ["RSMFRSD00003"]
    assert pick(conn, FilterSpec(max_price=Range(max=10200, max_exclusive=True)), "isin") == ["RSMFRSD00001"]


def test_remaining_maturity_in_days_is_exact(conn):
    load_rows(conn, [make_row(isin=i, remaining_maturity_days=d) for i, d in zip(_isins(3), [399, 400, 401])])
    col = "remaining_maturity_days"
    assert pick(conn, FilterSpec(remaining_maturity_days=Range(min=400)), col) == [400, 401]
    assert pick(conn, FilterSpec(remaining_maturity_days=Range(min=400, min_exclusive=True)), col) == [401]
    assert pick(conn, FilterSpec(remaining_maturity_days=Range(max=400, max_exclusive=True)), col) == [399]
    assert pick(conn, FilterSpec(remaining_maturity_days=Range(min=400, max=400)), col) == [400]


def test_remaining_days_and_years_filters_combine_with_and(conn):
    load_rows(conn, [make_row(isin=i, remaining_maturity_days=d) for i, d in zip(_isins(3), [100, 800, 1500])])
    spec = FilterSpec(remaining_maturity_years=Range(min=1), remaining_maturity_days=Range(max=1000))
    assert pick(conn, spec, "remaining_maturity_days") == [800]


def test_filters_are_anded(conn):
    load_rows(conn, [make_row(isin="RSMFRSD00001", currency="RSD", avg_yield_pct=4.0),
                     make_row(isin="RSMFRSD00002", currency="EUR", avg_yield_pct=4.0)])
    spec = FilterSpec(currency=["RSD"], yield_pct=Range(min=3.5))
    assert pick(conn, spec, "isin") == ["RSMFRSD00001"]


@pytest.mark.parametrize("kwargs", [
    dict(yield_pct=dict(min=5, max=4)),
    dict(quantity=dict(min=5, max=4)),
    dict(turnover=dict(min=5, max=4)),
    dict(min_price=dict(min=5, max=4)),
    dict(max_price=dict(min=5, max=4)),
    dict(remaining_maturity_days=dict(min=5, max=4)),
    dict(date_from=date(2024, 1, 1), date_to=date(2023, 1, 1)),
    dict(currency=["rsd"]),
    dict(currency=["RSDX"]),
    dict(currency=["RSD\n"]),
    dict(isin=["RSMFRSD00001\n"]),
    dict(isin=["x' OR 1=1 --"]),
    dict(yield_basis="median"),
    dict(unknown_field=1),
])
def test_validation_rejects(kwargs):
    with pytest.raises(ValidationError):
        FilterSpec(**kwargs)
