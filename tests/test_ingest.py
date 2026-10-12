from datetime import date

import pytest

from securities_analyzer.ingest.parser import IngestError, parse_csv
from securities_analyzer.ingest.quality import quality_flag
from tests.factories import make_row, rows_to_csv


def test_round_trip_two_rows():
    rows = [make_row(), make_row(isin="RSMFRSD00002", currency="EUR", turnover=1234.56)]
    assert parse_csv(rows_to_csv(rows)) == rows


def test_key_is_trade_settlement_isin():
    r = make_row(settlement_date=date(2023, 6, 19))
    assert r.key == (date(2023, 6, 15), date(2023, 6, 19), "RSMFRSD00001")


def test_blank_lines_are_ignored():
    data = rows_to_csv([make_row()]) + b"\n\n"
    assert len(parse_csv(data)) == 1


def test_header_change_is_rejected():
    data = rows_to_csv([make_row()]).replace("ISIN".encode(), b"ISIN2", 1)
    with pytest.raises(IngestError, match="Zaglavlje"):
        parse_csv(data)


def test_html_instead_of_csv_is_rejected():
    with pytest.raises(IngestError):
        parse_csv(b"<!doctype html><html><body>Error</body></html>")


def test_bad_number_reports_line():
    data = rows_to_csv([make_row()]).replace(b",5.00,", b",abc,", 1)
    with pytest.raises(IngestError, match="Red 2"):
        parse_csv(data)


def test_dash_coupon_is_zero_coupon():
    data = rows_to_csv([make_row(coupon_pct=0.0)]).replace(b",0.00,", b",-,", 1)
    assert b",-," in data
    assert parse_csv(data)[0].coupon_pct == 0.0


def test_wrong_column_count_reports_line():
    lines = rows_to_csv([make_row()]).decode("utf-8").rstrip("\n").split("\n")
    lines[1] = lines[1] + ",extra"
    with pytest.raises(IngestError, match="Red 2"):
        parse_csv(("\n".join(lines) + "\n").encode("utf-8"))


def test_duplicate_key_in_file_is_rejected():
    with pytest.raises(IngestError, match="duplirani"):
        parse_csv(rows_to_csv([make_row(), make_row()]))


def test_empty_file_is_rejected():
    with pytest.raises(IngestError):
        parse_csv(b"")


def test_quality_ok_row():
    assert quality_flag(make_row()) == "OK"


@pytest.mark.parametrize("overrides,code", [
    (dict(min_price=10001.0), "PRICE_ORDER"),
    (dict(min_yield_pct=6.0), "YIELD_ORDER"),
    (dict(settlement_date=date(2023, 6, 14)), "SETTLE_BEFORE_TRADE"),
    (dict(maturity_date=date(2023, 6, 1)), "MATURITY_BEFORE_SETTLE"),
    (dict(turnover=999.0), "TURNOVER_MISMATCH"),
])
def test_quality_flags(overrides, code):
    row = make_row()
    row = type(row)(**{**row.__dict__, **overrides})
    assert code in quality_flag(row).split(",")
