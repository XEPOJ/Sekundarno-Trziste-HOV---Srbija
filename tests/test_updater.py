import json
import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from securities_analyzer.db.repo import get_meta, replace_year, stored_count
from securities_analyzer.updater.nbs import (
    DownloadError, download_year, refresh, years_to_refresh,
)
from tests.factories import make_row, rows_to_csv


def year_rows(y, n=2):
    return [make_row(trade_date=date(y, 6, 10 + i), settlement_date=date(y, 6, 10 + i)) for i in range(n)]


# ---------- year selection ----------
@pytest.mark.parametrize("last,today,expected", [
    (None, date(2026, 10, 12), [2020, 2021, 2022, 2023, 2024, 2025, 2026]),
    (2026, date(2026, 10, 12), [2025, 2026]),
    (2025, date(2026, 1, 5), [2025, 2026]),
    (2023, date(2026, 10, 12), [2023, 2024, 2025, 2026]),
])
def test_years_to_refresh(last, today, expected):
    assert years_to_refresh(last, today) == expected


# ---------- refresh logic with an injected fetch ----------
def test_refresh_fills_empty_db_and_records_meta(conn):
    msgs = []
    rep = refresh(conn, today=date(2022, 3, 1),
                  fetch=lambda y: rows_to_csv(year_rows(y)), progress=msgs.append)
    assert [y.year for y in rep.years] == [2020, 2021, 2022]
    assert rep.ok and all(y.added == 2 for y in rep.years)
    assert rep.data_end == "2022-06-11"
    assert get_meta(conn, "last_update_utc")
    assert json.loads(get_meta(conn, "last_update_result"))["years"][0]["year"] == 2020
    assert any("2021" in m for m in msgs)


def test_refresh_is_idempotent(conn):
    f = lambda y: rows_to_csv(year_rows(y))
    refresh(conn, today=date(2021, 3, 1), fetch=f)
    rep = refresh(conn, today=date(2021, 3, 1), fetch=f)
    assert all(y.added == 0 and y.removed == 0 and y.unchanged == 2 for y in rep.years)


def test_refresh_download_error_keeps_existing_data(conn):
    replace_year(conn, 2021, year_rows(2021))
    def fail(y): raise DownloadError("offline")
    rep = refresh(conn, today=date(2021, 5, 1), fetch=fail)
    assert not rep.ok and all(y.status == "error" for y in rep.years)
    assert stored_count(conn, 2021) == 2


def test_refresh_format_change_keeps_existing_data(conn):
    replace_year(conn, 2021, year_rows(2021))
    rep = refresh(conn, today=date(2021, 5, 1), fetch=lambda y: b"<html>Greska</html>")
    assert not rep.ok and "Zaglavlje" in rep.years[-1].message
    assert stored_count(conn, 2021) == 2


def test_refresh_rejects_suspiciously_truncated_file(conn):
    replace_year(conn, 2021, year_rows(2021, n=10))
    rep = refresh(conn, today=date(2021, 5, 1), fetch=lambda y: rows_to_csv(year_rows(y, n=2)))
    y2021 = [y for y in rep.years if y.year == 2021][0]
    assert y2021.status == "error" and "skraćen" in y2021.message
    assert stored_count(conn, 2021) == 10


def test_refresh_empty_file_is_an_error(conn):
    rep = refresh(conn, today=date(2020, 5, 1), fetch=lambda y: rows_to_csv([]))
    assert not rep.ok and "nijedan red" in rep.years[0].message


def test_refresh_one_bad_year_does_not_block_others(conn):
    def fetch(y):
        if y == 2021:
            raise DownloadError("HTTP 500")
        return rows_to_csv(year_rows(y))
    rep = refresh(conn, today=date(2022, 3, 1), fetch=fetch)
    assert [y.status for y in rep.years] == ["ok", "error", "ok"]


# ---------- real HTTP layer against a local fake server ----------
class _Handler(BaseHTTPRequestHandler):
    calls = []
    mode = "ok"

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        type(self).calls.append((q.get("Format"), q.get("Year"), self.headers.get("User-Agent")))
        mode = type(self).mode
        if mode == "500":
            self.send_response(500); self.end_headers(); return
        if mode == "404":
            self.send_response(404); self.end_headers(); return
        body = rows_to_csv(year_rows(int(q["Year"][0])))
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_nbs():
    _Handler.calls, _Handler.mode = [], "ok"
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/Download", _Handler
    srv.shutdown()


def test_download_year_sends_format_year_and_user_agent(fake_nbs):
    url, h = fake_nbs
    data = download_year(2023, base_url=url, backoff=0)
    assert data.startswith("\ufeff".encode("utf-8"))
    fmt, year, ua = h.calls[0]
    assert fmt == ["csv"] and year == ["2023"] and ua.startswith("SecuritiesAnalyzer/")


def test_download_year_retries_on_500_then_fails(fake_nbs):
    url, h = fake_nbs
    h.mode = "500"
    with pytest.raises(DownloadError):
        download_year(2023, base_url=url, retries=3, backoff=0)
    assert len(h.calls) == 3


def test_download_year_does_not_retry_on_404(fake_nbs):
    url, h = fake_nbs
    h.mode = "404"
    with pytest.raises(DownloadError, match="404"):
        download_year(2023, base_url=url, retries=3, backoff=0)
    assert len(h.calls) == 1


def test_download_year_connection_refused():
    # Bind then close a port so the connection is refused immediately (port 9 hangs on Windows).
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(DownloadError):
        download_year(2023, base_url=f"http://127.0.0.1:{port}/Download", retries=2, backoff=0, timeout=2)
