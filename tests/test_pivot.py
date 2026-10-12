from datetime import date

import pytest

from securities_analyzer.query.filters import FilterSpec, Range
from securities_analyzer.query.pivot import PivotQuery, run_pivot
from tests.factories import load_rows, make_row

ALL = FilterSpec()
A, B, E, F = "RSMFRSD0000A", "RSMFRSD0000B", "RSMFRSD0000E", "RSMFRSD0000F"


def q(**kw) -> PivotQuery:
    return PivotQuery(**kw)


def by_currency(res):
    out: dict[str, list] = {}
    for r in res["rows"]:
        out.setdefault(r["currency"], []).append(r)
    return out


@pytest.fixture
def sample(conn):
    load_rows(conn, [
        make_row(isin=A, turnover=100.0, avg_yield_pct=4.0, transaction_count=2),
        make_row(isin=A, turnover=300.0, avg_yield_pct=6.0, transaction_count=1,
                 trade_date=date(2023, 7, 3), settlement_date=date(2023, 7, 3)),
        make_row(isin=B, turnover=500.0, avg_yield_pct=5.0, transaction_count=5,
                 remaining_maturity_days=300),
        make_row(isin=E, currency="EUR", turnover=50.0, avg_yield_pct=3.0, transaction_count=1),
        make_row(isin=F, currency="EUR", turnover=70.0, avg_yield_pct=2.0, transaction_count=2),
    ])
    return conn


def test_zero_dimensions_gives_one_row_per_currency(sample):
    res = run_pivot(sample, ALL, q(measures=["turnover", "transactions"]))
    assert [(r["currency"], r["dims"], r["values"]) for r in res["rows"]] == [
        ("EUR", [], [120.0, 3]), ("RSD", [], [900.0, 8])]
    assert res["dimensions"] == []
    assert res["measures"] == [
        {"id": "turnover", "label": "Promet", "unit": "currency"},
        {"id": "transactions", "label": "Broj transakcija", "unit": "count"}]
    assert res["truncated_currencies"] == []


def test_group_by_isin_sorted_by_measure_desc(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc"))
    got = {c: [(r["dims"][0], r["values"][0]) for r in rs] for c, rs in by_currency(res).items()}
    assert got == {"RSD": [(B, 500.0), (A, 400.0)], "EUR": [(F, 70.0), (E, 50.0)]}
    assert res["dimensions"] == [{"id": "isin", "label": "Hartija (ISIN)"}]


def test_weighted_yield_quantity_active_days_isin_count(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"],
                                    measures=["weighted_yield", "quantity", "active_days", "isin_count"],
                                    sort_by="group", order="asc"))
    rsd = {r["dims"][0]: r["values"] for r in by_currency(res)["RSD"]}
    assert rsd[A][0] == pytest.approx(5.5)          # (4*100 + 6*300) / 400
    assert rsd[A][1:] == [2, 2, 1]                  # 2 rows with quantity 1, 2 days, 1 security
    assert rsd[B][0] == pytest.approx(5.0)


def test_yield_extremes_price_and_trade_size(conn):
    load_rows(conn, [
        make_row(isin=A, quantity=10, wavg_price=9000.0, min_price=8900.0, max_price=9100.0,
                 turnover=90000.0, min_yield_pct=3.0, avg_yield_pct=3.5, max_yield_pct=4.0,
                 transaction_count=2, nominal_per_unit=10000.0),
        make_row(isin=A, trade_date=date(2023, 6, 16), settlement_date=date(2023, 6, 16),
                 quantity=30, wavg_price=9500.0, min_price=9400.0, max_price=9600.0,
                 turnover=285000.0, min_yield_pct=2.5, avg_yield_pct=3.0, max_yield_pct=3.8,
                 transaction_count=3, nominal_per_unit=10000.0),
    ])
    (r,) = run_pivot(conn, ALL, q(measures=["yield_min", "yield_max", "price_pct_nominal",
                                            "avg_trade_size"]))["rows"]
    assert r["values"][0] == 2.5 and r["values"][1] == 4.0           # true extremes, not averages
    assert r["values"][2] == pytest.approx(93.75)                    # 100 * 375000 / (40 * 10000)
    assert r["values"][3] == pytest.approx(75000.0)                  # 375000 / 5 transactions


def test_division_by_zero_gives_null_and_sorts_last(conn):
    load_rows(conn, [make_row(isin=A, turnover=100.0, avg_yield_pct=4.0),
                     make_row(isin=B, turnover=0.0, avg_yield_pct=9.0)])
    for order in ("asc", "desc"):
        res = run_pivot(conn, ALL, q(dimensions=["isin"], measures=["weighted_yield"],
                                      sort_by="weighted_yield", order=order))
        assert [(r["dims"][0], r["values"][0]) for r in res["rows"]] == [(A, 4.0), (B, None)]


def test_time_dimensions_values_and_order(conn):
    days = [date(2023, 2, 10), date(2023, 4, 1), date(2023, 6, 15), date(2024, 1, 2)]
    load_rows(conn, [make_row(isin=A, turnover=10.0, trade_date=d, settlement_date=d) for d in days])

    def vals(dim):
        res = run_pivot(conn, ALL, q(dimensions=[dim], measures=["turnover"], sort_by="group", order="asc"))
        return [r["dims"][0] for r in res["rows"]]

    assert vals("date_day") == ["2023-02-10", "2023-04-01", "2023-06-15", "2024-01-02"]
    assert vals("date_week") == ["2023-02-06", "2023-03-27", "2023-06-12", "2024-01-01"]   # Mondays
    assert vals("date_month") == ["2023-02-01", "2023-04-01", "2023-06-01", "2024-01-01"]
    assert vals("date_quarter") == ["2023-Q1", "2023-Q2", "2024-Q1"]
    assert vals("date_year") == ["2023", "2024"]


def test_bucket_dimension_uses_natural_order_not_alphabetical(conn):
    days = [300, 1000, 1500, 2600, 4000]
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", remaining_maturity_days=d, turnover=10.0)
                     for i, d in enumerate(days, 1)])
    base = dict(dimensions=["remaining_bucket"], measures=["turnover"], sort_by="group")
    asc = [r["dims"][0] for r in run_pivot(conn, ALL, q(**base, order="asc"))["rows"]]
    desc = [r["dims"][0] for r in run_pivot(conn, ALL, q(**base, order="desc"))["rows"]]
    assert asc == ["0-1Y", "1-3Y", "3-5Y", "5-10Y", "10Y+"]
    assert desc == list(reversed(asc))


def test_numeric_dimensions(conn):
    load_rows(conn, [
        make_row(isin=A, original_maturity_days=2556, remaining_maturity_days=1094,
                 coupon_pct=5.0, turnover=10.0),
        make_row(isin=B, original_maturity_days=4565, remaining_maturity_days=1095,
                 coupon_pct=4.5, turnover=10.0, settlement_date=date(2023, 6, 19)),
    ])

    def vals(dim):
        res = run_pivot(conn, ALL, q(dimensions=[dim], measures=["turnover"], sort_by="group", order="asc"))
        return [r["dims"][0] for r in res["rows"]]

    assert vals("original_years") == [7.0, 12.5]
    assert vals("remaining_years") == [2, 3]
    assert vals("coupon") == [4.5, 5.0]


def test_two_dimensions_group_order(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin", "date_month"], measures=["turnover"],
                                    sort_by="group", order="asc"))
    rsd = [(r["dims"], r["values"][0]) for r in by_currency(res)["RSD"]]
    assert rsd == [([A, "2023-06-01"], 100.0), ([A, "2023-07-01"], 300.0), ([B, "2023-06-01"], 500.0)]


def test_limit_is_per_currency_and_truncation_is_reported(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc", limit=1))
    assert {r["currency"]: r["dims"][0] for r in res["rows"]} == {"RSD": B, "EUR": F}
    assert res["truncated_currencies"] == ["EUR", "RSD"]
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc", limit=2))
    assert res["truncated_currencies"] == [] and len(res["rows"]) == 4
    zero = run_pivot(sample, ALL, q(measures=["turnover"], limit=1))
    assert zero["truncated_currencies"] == [] and len(zero["rows"]) == 2


def test_filters_apply_before_grouping(sample):
    res = run_pivot(sample, FilterSpec(currency=["EUR"]), q(dimensions=["isin"], measures=["turnover"]))
    assert {r["currency"] for r in res["rows"]} == {"EUR"}
    res = run_pivot(sample, FilterSpec(remaining_maturity_years=Range(min=3)), q(measures=["turnover"]))
    assert {r["currency"]: r["values"][0] for r in res["rows"]} == {"EUR": 120.0, "RSD": 400.0}


def test_ties_are_broken_by_dimension_ascending(conn):
    # Equal turnover. The 10Y+ group is inserted first, and its label sorts before "5-10Y" as text,
    # so only the bucket sort expression (5-10Y before 10Y+) can produce the expected order.
    load_rows(conn, [make_row(isin=A, remaining_maturity_days=4000, turnover=10.0),
                     make_row(isin=B, remaining_maturity_days=2600, turnover=10.0)])
    for order in ("desc", "asc"):
        res = run_pivot(conn, ALL, q(dimensions=["remaining_bucket"], measures=["turnover"],
                                      sort_by="turnover", order=order))
        assert [r["dims"][0] for r in res["rows"]] == ["5-10Y", "10Y+"]


def test_empty_result(conn):
    res = run_pivot(conn, ALL, q(dimensions=["isin"], measures=["turnover"]))
    assert res["rows"] == [] and res["truncated_currencies"] == []
