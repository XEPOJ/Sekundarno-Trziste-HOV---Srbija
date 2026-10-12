import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from securities_analyzer.api.app import create_app
from securities_analyzer.db.schema import connect
from securities_analyzer.query import service
from tests.factories import load_rows, make_row, rows_to_csv


@pytest.fixture
def client(db_path, tmp_path):
    c = connect(db_path)
    load_rows(c, [
        make_row(isin="RSMFRSD0000A", currency="RSD", turnover=100.0, avg_yield_pct=4.0),
        make_row(isin="RSMFRSD0000B", currency="RSD", turnover=300.0, avg_yield_pct=6.0),
        make_row(isin="RSMFRSD0000C", currency="EUR", turnover=50.0, avg_yield_pct=3.0),
    ])
    c.close()
    # Two rows per year: a single row would trip the "<50% of stored rows" guard for 2023.
    app = create_app(db_path, fetch=lambda y: rows_to_csv(
        [make_row(trade_date=date(y, 6, 10), settlement_date=date(y, 6, 10), isin=i)
         for i in ("RSMFRSD0000Y", "RSMFRSD0000Z")]),
        export_dir=tmp_path / "exports")
    return TestClient(app)


def test_meta(client):
    j = client.get("/api/meta").json()
    assert j["rows"] == 3 and j["first_trade_date"] == "2023-06-15" and j["version"]


def test_securities(client):
    assert {s["isin"] for s in client.get("/api/securities").json()} == {
        "RSMFRSD0000A", "RSMFRSD0000B", "RSMFRSD0000C"}


def test_rows_with_filter_and_paging(client):
    body = {"filter": {"currency": ["RSD"]}, "sort": "turnover", "order": "desc", "page": 1, "page_size": 1}
    j = client.post("/api/query/rows", json=body).json()
    assert j["total"] == 2 and j["rows"][0]["turnover"] == 300.0 and j["page"] == 1


def test_rows_default_body_returns_everything(client):
    assert client.post("/api/query/rows", json={}).json()["total"] == 3


def test_invalid_filter_is_422(client):
    r = client.post("/api/query/rows", json={"filter": {"currency": ["rsd"]}})
    assert r.status_code == 422
    r = client.post("/api/query/rows", json={"filter": {"nope": 1}})
    assert r.status_code == 422


def test_bad_sort_is_422(client):
    assert client.post("/api/query/rows", json={"sort": "id; DROP"}).status_code == 422
    assert client.post("/api/query/extremes", json={"sort_by": "isin"}).status_code == 422


def test_summary_is_split_by_currency(client):
    j = client.post("/api/query/summary", json={}).json()
    assert {k["currency"] for k in j["kpis"]} == {"RSD", "EUR"} and j["quality_flagged"] == 0


def test_timeseries_scatter_buckets_extremes(client):
    assert client.post("/api/query/timeseries", json={"granularity": "month"}).json()
    assert len(client.post("/api/query/scatter", json={}).json()) == 3
    assert client.post("/api/query/buckets", json={}).json()
    ex = client.post("/api/query/extremes", json={"filter": {"currency": ["RSD"]}}).json()
    assert ex[0]["highest_pct"] == 6.0 and ex[0]["lowest_pct"] == 4.0
    assert client.post("/api/query/timeseries", json={"granularity": "year"}).status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_export(client, tmp_path, fmt):
    j = client.post("/api/export", json={"format": fmt, "filter": {"currency": ["RSD"]}}).json()
    assert j["rows"] == 2
    p = Path(j["path"])
    assert p.exists() and p.suffix == f".{fmt}" and p.parent == tmp_path / "exports"
    if fmt == "csv":
        assert p.read_bytes().startswith(b"\xef\xbb\xbf")
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0].split(",") == list(service.ROW_COLUMNS) and len(lines) == 3
    else:
        from openpyxl import load_workbook
        wb = load_workbook(p)
        ws = wb["Podaci"]
        assert wb.sheetnames == ["Podaci"]
        data = list(ws.iter_rows(values_only=True))
        assert list(data[0]) == list(service.ROW_COLUMNS) and len(data) == 3
        wb.close()


def test_saved_queries_crud(client):
    f = {"currency": ["EUR"], "yield_pct": {"min": 3.5, "min_exclusive": True}}
    assert client.put("/api/saved-queries", json={"name": "Moj upit", "filter": f}).status_code == 200
    items = client.get("/api/saved-queries").json()
    assert items[0]["name"] == "Moj upit" and items[0]["filter"]["currency"] == ["EUR"]
    assert client.delete("/api/saved-queries/Moj upit").status_code == 200
    assert client.get("/api/saved-queries").json() == []
    assert client.put("/api/saved-queries", json={"name": "x", "filter": {"bad": 1}}).status_code == 422


def test_saved_query_name_with_slash_can_be_deleted(client):
    assert client.put("/api/saved-queries", json={"name": "a/b", "filter": {}}).status_code == 200
    assert client.delete("/api/saved-queries/a%2Fb").status_code == 200
    assert client.get("/api/saved-queries").json() == []
    assert client.put("/api/saved-queries", json={"name": "a/b", "filter": {}}).status_code == 200
    assert client.delete("/api/saved-queries/a/b").status_code == 200
    assert client.get("/api/saved-queries").json() == []


def test_update_flow(client):
    assert client.get("/api/update/status").json()["state"] == "idle"
    assert client.post("/api/update").json() == {"started": True}
    for _ in range(100):
        st = client.get("/api/update/status").json()
        if st["state"] != "running":
            break
        time.sleep(0.05)
    assert st["state"] == "done", st
    assert st["report"]["ok"] is True
    assert any("Preuzimam" in m for m in st["messages"])
    assert client.get("/api/meta").json()["rows"] > 3
    assert client.get("/api/meta").json()["last_update_utc"]
