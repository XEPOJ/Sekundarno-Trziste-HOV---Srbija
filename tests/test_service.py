from datetime import date

import pytest

from securities_analyzer.query import service
from securities_analyzer.query.filters import FilterSpec, Range
from tests.factories import load_rows, make_row

ALL = FilterSpec()
D = date(2023, 6, 15)


@pytest.fixture
def sample(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", currency="RSD", turnover=100.0, avg_yield_pct=4.0),
        make_row(isin="RSMFRSD0000B", currency="RSD", turnover=300.0, avg_yield_pct=6.0),
        make_row(isin="RSMFRSD0000C", currency="EUR", turnover=50.0, avg_yield_pct=3.0),
        make_row(isin="RSMFRSD0000A", currency="RSD", turnover=100.0, avg_yield_pct=5.0,
                 trade_date=date(2023, 7, 3), settlement_date=date(2023, 7, 3)),
    ])
    return conn


def test_fetch_rows_paging_sort_and_total(sample):
    res = service.fetch_rows(sample, ALL, sort="turnover", order="desc", limit=2, offset=0)
    assert res["total"] == 4
    assert [r["turnover"] for r in res["rows"]] == [300.0, 100.0]
    res2 = service.fetch_rows(sample, ALL, sort="turnover", order="asc", limit=10, offset=3)
    assert [r["turnover"] for r in res2["rows"]] == [300.0]


def test_fetch_rows_rejects_unknown_sort(sample):
    with pytest.raises(ValueError):
        service.fetch_rows(sample, ALL, sort="id; DROP TABLE trades")


def test_kpis_are_split_by_currency_and_weighted(sample):
    k = {r["currency"]: r for r in service.kpis(sample, ALL)}
    assert set(k) == {"RSD", "EUR"}
    assert k["RSD"]["turnover"] == 500.0
    assert k["RSD"]["isins"] == 2 and k["RSD"]["active_days"] == 2 and k["RSD"]["row_count"] == 3
    assert k["RSD"]["weighted_yield_pct"] == pytest.approx((4 * 100 + 6 * 300 + 5 * 100) / 500)
    assert k["EUR"]["weighted_yield_pct"] == pytest.approx(3.0)


def test_kpis_honour_filters(sample):
    k = service.kpis(sample, FilterSpec(currency=["EUR"]))
    assert [r["currency"] for r in k] == ["EUR"]


def test_timeseries_month_week_day(sample):
    month = [r for r in service.yield_timeseries(sample, ALL, "month") if r["currency"] == "RSD"]
    assert [(r["period"], round(r["weighted_yield_pct"], 4)) for r in month] == [
        ("2023-06-01", 5.5), ("2023-07-01", 5.0)]
    week = [r["period"] for r in service.yield_timeseries(sample, ALL, "week") if r["currency"] == "RSD"]
    assert week == ["2023-06-12", "2023-07-03"]      # Mondays (2023-06-15 is a Thursday, 2023-07-03 a Monday)
    day = [r["period"] for r in service.yield_timeseries(sample, ALL, "day") if r["currency"] == "RSD"]
    assert day == ["2023-06-15", "2023-07-03"]


def test_timeseries_rejects_bad_granularity(sample):
    with pytest.raises(ValueError):
        service.yield_timeseries(sample, ALL, "year")


def test_maturity_buckets(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", remaining_maturity_days=300, turnover=10.0),
        make_row(isin="RSMFRSD0000B", remaining_maturity_days=1000, turnover=20.0),
        make_row(isin="RSMFRSD0000C", remaining_maturity_days=1095, turnover=30.0),
        make_row(isin="RSMFRSD0000D", remaining_maturity_days=2600, turnover=40.0),
        make_row(isin="RSMFRSD0000E", remaining_maturity_days=4000, turnover=50.0),
    ])
    res = service.maturity_buckets(conn, ALL)
    assert [(r["bucket"], r["turnover"]) for r in res] == [
        ("0-1Y", 10.0), ("1-3Y", 50.0), ("5-10Y", 40.0), ("10Y+", 50.0)]


def test_daily_extremes_tiebreak_and_range(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", turnover=100.0, min_yield_pct=3.0, avg_yield_pct=4.5, max_yield_pct=6.0),
        make_row(isin="RSMFRSD0000B", turnover=300.0, min_yield_pct=3.0, avg_yield_pct=4.5, max_yield_pct=6.0),
        make_row(isin="RSMFRSD0000C", turnover=10.0, min_yield_pct=2.5, avg_yield_pct=3.0, max_yield_pct=4.0),
    ])
    (r,) = service.daily_extremes(conn, ALL)
    assert r["highest_pct"] == 6.0 and r["highest_isin"] == "RSMFRSD0000B"   # tie -> larger turnover
    assert r["lowest_pct"] == 2.5 and r["lowest_isin"] == "RSMFRSD0000C"
    assert r["range_pct"] == pytest.approx(3.5)


def test_daily_extremes_sort_and_limit(conn):
    load_rows(conn, [
        make_row(trade_date=date(2023, 6, d), settlement_date=date(2023, 6, d),
                 min_yield_pct=y - 0.5, avg_yield_pct=y, max_yield_pct=y + 0.5)
        for d, y in [(1, 4.0), (2, 6.0), (3, 5.0)]
    ])
    top = service.daily_extremes(conn, ALL, sort_by="highest_pct", order="desc", limit=2)
    assert [r["trade_date"] for r in top] == ["2023-06-02", "2023-06-03"]
    low = service.daily_extremes(conn, ALL, sort_by="lowest_pct", order="asc", limit=1)
    assert [r["trade_date"] for r in low] == ["2023-06-01"]
    with pytest.raises(ValueError):
        service.daily_extremes(conn, ALL, sort_by="isin")


def test_daily_extremes_respect_other_filters(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", remaining_maturity_days=500, max_yield_pct=9.0, avg_yield_pct=5.0, min_yield_pct=5.0),
        make_row(isin="RSMFRSD0000B", remaining_maturity_days=2000, max_yield_pct=6.0, avg_yield_pct=5.0, min_yield_pct=5.0),
    ])
    spec = FilterSpec(remaining_maturity_years=Range(min=3))
    (r,) = service.daily_extremes(conn, spec)
    assert r["highest_pct"] == 6.0


def test_quality_count_and_securities(conn):
    load_rows(conn, [make_row(), make_row(isin="RSMFRSD0000B", turnover=1.0, quantity=500)])
    assert service.quality_count(conn, ALL) == 1
    secs = service.list_securities(conn)
    assert {s["isin"] for s in secs} == {"RSMFRSD00001", "RSMFRSD0000B"}


def test_scatter_columns(sample):
    rows = service.scatter(sample, ALL)
    assert len(rows) == 4
    assert set(rows[0]) == {"trade_date", "isin", "currency", "remaining_maturity_days",
                            "avg_yield_pct", "turnover"}


def _three_days_for_a(conn):
    d1, d2, d3 = date(2023, 6, 1), date(2023, 6, 2), date(2023, 6, 5)
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", turnover=100.0, quantity=10, transaction_count=2, avg_yield_pct=4.0,
                 min_yield_pct=3.5, max_yield_pct=4.5, trade_date=d1, settlement_date=d1),
        make_row(isin="RSMFRSD0000A", turnover=100.0, quantity=20, transaction_count=1, avg_yield_pct=5.0,
                 min_yield_pct=4.8, max_yield_pct=5.2, trade_date=d2, settlement_date=d2),
        make_row(isin="RSMFRSD0000A", turnover=300.0, quantity=30, transaction_count=3, avg_yield_pct=9.0,
                 min_yield_pct=8.0, max_yield_pct=9.5, trade_date=d3, settlement_date=d3),
        make_row(isin="RSMFRSD0000B", currency="EUR", turnover=50.0, quantity=5, transaction_count=1,
                 avg_yield_pct=3.0, trade_date=d1, settlement_date=d1),
    ])
    return conn


def test_securities_summary_gives_one_row_per_isin_for_the_whole_period(conn):
    rows = service.securities_summary(_three_days_for_a(conn), ALL)
    assert [r["isin"] for r in rows] == ["RSMFRSD0000A", "RSMFRSD0000B"]      # biggest turnover first
    a = rows[0]
    assert (a["currency"], a["active_days"], a["transactions"], a["quantity"], a["turnover"]) == ("RSD", 3, 6, 60, 500.0)
    assert a["weighted_yield_pct"] == pytest.approx((4 * 100 + 5 * 100 + 9 * 300) / 500)   # 7.2, weighted by turnover
    assert a["avg_daily_yield_pct"] == pytest.approx(6.0)                                  # plain mean of the daily averages
    assert (a["min_yield_pct"], a["max_yield_pct"]) == (3.5, 9.5)
    assert (a["first_trade"], a["last_trade"]) == ("2023-06-01", "2023-06-05")
    assert a["coupon_pct"] == 5.0 and a["maturity_date"] == "2030-07-30"
    assert rows[1]["currency"] == "EUR" and rows[1]["weighted_yield_pct"] == pytest.approx(3.0)


def test_securities_summary_only_uses_rows_that_pass_the_filters(conn):
    _three_days_for_a(conn)
    a = service.securities_summary(conn, FilterSpec(quantity=Range(min=15)))[0]
    assert a["active_days"] == 2 and a["quantity"] == 50 and a["turnover"] == 400.0
    assert a["weighted_yield_pct"] == pytest.approx((5 * 100 + 9 * 300) / 400)
    only_late = service.securities_summary(conn, FilterSpec(date_from=date(2023, 6, 5)))
    assert [(r["isin"], r["active_days"]) for r in only_late] == [("RSMFRSD0000A", 1)]
    assert service.securities_summary(conn, FilterSpec(isin=["RSMFRSD0000B"]))[0]["currency"] == "EUR"
    assert service.securities_summary(conn, FilterSpec(quantity=Range(min=10**6))) == []
