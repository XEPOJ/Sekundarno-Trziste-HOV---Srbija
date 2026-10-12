from datetime import date

from securities_analyzer.__main__ import main
from securities_analyzer.app import find_free_port
from securities_analyzer.db.repo import data_range
from securities_analyzer.db.schema import connect
from tests.factories import make_row, rows_to_csv


def test_find_free_port_is_usable():
    p = find_free_port()
    assert 1024 < p < 65536


def test_build_seed_command(tmp_path, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "GovermentSecuritySecondaryTrade_2023.csv").write_bytes(rows_to_csv([make_row()]))
    out = tmp_path / "seed.db"
    assert main(["build-seed", str(raw), str(out)]) == 0
    c = connect(out)
    assert data_range(c)[2] == 1
    c.close()
    assert "1" in capsys.readouterr().out


def test_fetch_all_command_writes_one_file_per_year(tmp_path, monkeypatch):
    calls = []
    def fake_download(year, **kw):
        calls.append(year)
        return rows_to_csv([make_row(trade_date=date(year, 6, 10), settlement_date=date(year, 6, 10))])
    monkeypatch.setattr("securities_analyzer.__main__.download_year", fake_download)
    monkeypatch.setattr("securities_analyzer.__main__.date", type("D", (), {"today": staticmethod(lambda: date(2022, 2, 1))}))
    out = tmp_path / "raw"
    assert main(["fetch-all", str(out), "--from-year", "2020"]) == 0
    assert calls == [2020, 2021, 2022]
    assert sorted(p.name for p in out.glob("*.csv")) == [
        f"GovermentSecuritySecondaryTrade_{y}.csv" for y in (2020, 2021, 2022)]
