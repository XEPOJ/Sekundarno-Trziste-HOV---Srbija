import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from openpyxl import Workbook, load_workbook

from securities_analyzer.api import exporting


def test_unique_export_path_appends_counter_on_collision(tmp_path, monkeypatch):
    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 9, 30, 15)

    monkeypatch.setattr(exporting, "datetime", FixedNow)
    d = tmp_path / "out"
    p1 = exporting.unique_export_path(d, "securities", "csv")
    p2 = exporting.unique_export_path(d, "securities", "csv")
    p3 = exporting.unique_export_path(d, "securities", "csv")
    assert [p.name for p in (p1, p2, p3)] == [
        "securities_20261012_093015.csv", "securities_20261012_093015_2.csv",
        "securities_20261012_093015_3.csv"]
    assert all(p.exists() for p in (p1, p2, p3))   # names are reserved by exclusive creation


def test_unique_export_path_is_distinct_across_threads(tmp_path, monkeypatch):
    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 9, 30, 15)

    monkeypatch.setattr(exporting, "datetime", FixedNow)
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: exporting.unique_export_path(tmp_path, "securities", "csv"),
                              range(8)))
    assert len({p.name for p in paths}) == 8
    assert len(list(tmp_path.iterdir())) == 8


def test_write_table_csv_has_bom_header_and_rows(tmp_path):
    path = tmp_path / "t.csv"
    exporting.write_table(path, ["A", "B"], [[1, "x"], [2, None]], "csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_text(encoding="utf-8-sig").splitlines() == ["A,B", "1,x", "2,"]


def test_write_table_xlsx_sheet_header_and_rows(tmp_path):
    path = tmp_path / "t.xlsx"
    exporting.write_table(path, ["A", "B"], [[1, "x"], [2, None]], "xlsx")
    ws = load_workbook(path).active
    assert ws.title == "Podaci"
    assert [[c.value for c in row] for row in ws.iter_rows()] == [["A", "B"], [1, "x"], [2, None]]


def test_write_table_csv_failure_leaves_no_files(tmp_path, monkeypatch):
    path = exporting.unique_export_path(tmp_path, "securities", "csv")

    class BoomWriter:
        def __init__(self, fp):
            self.fp = fp

        def writerow(self, row):
            self.fp.write("partial")
            raise RuntimeError("boom")

    monkeypatch.setattr(csv, "writer", BoomWriter)
    with pytest.raises(RuntimeError):
        exporting.write_table(path, ["A"], [[1]], "csv")
    assert list(tmp_path.iterdir()) == []


def test_write_table_xlsx_failure_leaves_no_files(tmp_path, monkeypatch):
    path = exporting.unique_export_path(tmp_path, "securities", "xlsx")

    def boom(self, target):
        target.write(b"partial")
        raise RuntimeError("boom")

    monkeypatch.setattr(Workbook, "save", boom)
    with pytest.raises(RuntimeError):
        exporting.write_table(path, ["A"], [[1]], "xlsx")
    assert list(tmp_path.iterdir()) == []


def test_write_table_success_leaves_only_the_final_file(tmp_path):
    path = exporting.unique_export_path(tmp_path, "securities", "csv")
    exporting.write_table(path, ["A"], [[1]], "csv")
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_write_table_xlsx_writer_failure_leaves_no_files(tmp_path, monkeypatch):
    """Real failure mode: openpyxl's ExcelWriter raises while it holds the archive open."""
    path = exporting.unique_export_path(tmp_path, "securities", "xlsx")

    def boom(self):
        raise RuntimeError("boom")

    monkeypatch.setattr("openpyxl.writer.excel.ExcelWriter.write_data", boom)
    with pytest.raises(RuntimeError, match="boom"):
        exporting.write_table(path, ["A"], [[1]], "xlsx")
    assert list(tmp_path.iterdir()) == []
