import pytest

from securities_analyzer.ingest.parser import parse_csv
from securities_analyzer.query import service
from securities_analyzer.query.filters import FilterSpec, Range
from securities_analyzer.query.pivot import PivotQuery, run_pivot
from tests.conftest import find_raw_dir

GOLDEN = FilterSpec(
    date_from="2023-02-02", date_to="2024-03-05",
    yield_pct=Range(min=3.5, min_exclusive=True),
    remaining_maturity_years=Range(min=3, min_exclusive=True),
)


def test_every_real_file_parses():
    raw = find_raw_dir()
    if raw is None:
        pytest.skip("real NBS CSV files not available")
    total = 0
    for f in sorted(raw.glob("GovermentSecuritySecondaryTrade_*.csv")):
        total += len(parse_csv(f.read_bytes()))
    assert total >= 5000


def test_closed_years_have_no_quality_flags(real_conn):
    n = real_conn.execute(
        "SELECT COUNT(*) FROM trades WHERE quality_flag != 'OK' AND trade_date <= '2025-12-31'"
    ).fetchone()[0]
    assert n == 0


def test_golden_kpis(real_conn):
    k = {r["currency"]: r for r in service.kpis(real_conn, GOLDEN)}
    assert k["RSD"]["row_count"] == 371
    assert k["RSD"]["turnover"] == pytest.approx(155830121796.84, rel=1e-9)
    assert k["RSD"]["weighted_yield_pct"] == pytest.approx(6.093064, abs=1e-6)
    assert k["RSD"]["quantity"] == 16233797 and k["RSD"]["isins"] == 3
    assert k["EUR"]["row_count"] == 17
    assert k["EUR"]["turnover"] == pytest.approx(15642804.29, rel=1e-9)
    assert k["EUR"]["weighted_yield_pct"] == pytest.approx(4.126739, abs=1e-6)
    assert k["EUR"]["quantity"] == 16859 and k["EUR"]["isins"] == 6
    assert service.fetch_rows(real_conn, GOLDEN, limit=1)["total"] == 388


def test_golden_daily_extremes(real_conn):
    spec = GOLDEN.model_copy(update={"currency": ["RSD"]})
    day = [r for r in service.daily_extremes(real_conn, spec, limit=5000)
           if r["trade_date"] == "2023-12-28"]
    assert len(day) == 1
    assert day[0]["highest_pct"] == 6.27 and day[0]["highest_isin"] == "RSMFRSD86176"
    assert day[0]["lowest_pct"] == 4.80 and day[0]["lowest_isin"] == "RSMFRSD55940"


def _rows(res, currency):
    return [r for r in res["rows"] if r["currency"] == currency]


def test_golden_pivot_most_traded_securities_2024(real_conn):
    spec = FilterSpec(date_from="2024-01-01", date_to="2024-12-31")
    res = run_pivot(real_conn, spec, PivotQuery(
        dimensions=["isin"], measures=["turnover", "quantity", "transactions", "weighted_yield"],
        sort_by="turnover", order="desc", limit=5))
    expected = {
        "RSD": [("RSMFRSD58761", 121471327158.97, 10904256, 541, 5.5628),
                ("RSMFRSD86176", 105048689266.66, 11105945, 685, 5.4735),
                ("RSMFRSD55940", 43845029342.10, 4107635, 289, 4.5509),
                ("RSMFRSD89592", 28305748426.46, 2799899, 185, 4.6835),
                ("RSMFRSD90335", 8727699321.06, 873622, 10, 4.1348)],
        "EUR": [("RSMFRSD51436", 43154118.53, 43261, 48, 3.6302),
                ("RSMFRSD66798", 38485549.00, 41120, 19, 2.4128),
                ("RSMFRSD70022", 20734643.90, 19860, 8, 3.8982),
                ("RSMFRSD84510", 19348117.50, 19000, 7, 3.5481),
                ("RSMFRSD68802", 18076263.44, 17992, 14, 3.9726)],
    }
    for cur, exp in expected.items():
        got = _rows(res, cur)
        assert len(got) == 5
        for row, (isin, turnover, qty, tx, wy) in zip(got, exp):
            assert row["dims"] == [isin]
            assert row["values"][0] == pytest.approx(turnover, rel=1e-9)
            assert row["values"][1] == qty and row["values"][2] == tx
            assert row["values"][3] == pytest.approx(wy, abs=5e-5)


def test_golden_pivot_yield_by_year_and_bucket(real_conn):
    spec = FilterSpec(currency=["RSD"], date_to="2022-12-31")
    res = run_pivot(real_conn, spec, PivotQuery(
        dimensions=["date_year", "remaining_bucket"], measures=["weighted_yield"],
        sort_by="group", order="asc"))
    first = [(r["dims"], r["values"][0]) for r in res["rows"][:6]]
    assert [d for d, _ in first] == [
        ["2020", "0-1Y"], ["2020", "1-3Y"], ["2020", "3-5Y"], ["2020", "5-10Y"],
        ["2020", "10Y+"], ["2021", "0-1Y"]]
    for (_, value), exp in zip(first, [1.5359, 2.0573, 2.3980, 2.9846, 3.8285, 1.0443]):
        assert value == pytest.approx(exp, abs=5e-5)


def test_golden_pivot_group_counts_and_truncation(real_conn):
    base = dict(dimensions=["date_day", "isin"], measures=["turnover"], sort_by="group", order="asc")
    # Bounded to closed years: release.yml downloads live NBS data, so an open-ended range drifts.
    closed = FilterSpec(date_to="2025-12-31")
    full = run_pivot(real_conn, closed, PivotQuery(**base, limit=5000))
    assert len(_rows(full, "RSD")) == 3563 and len(_rows(full, "EUR")) == 1048
    assert full["truncated_currencies"] == []
    cut = run_pivot(real_conn, closed, PivotQuery(**base, limit=1000))
    assert len(_rows(cut, "RSD")) == 1000 and len(_rows(cut, "EUR")) == 1000
    assert cut["truncated_currencies"] == ["EUR", "RSD"]
