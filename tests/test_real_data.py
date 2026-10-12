import pytest

from securities_analyzer.ingest.parser import parse_csv
from securities_analyzer.query import service
from securities_analyzer.query.filters import FilterSpec, Range
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
