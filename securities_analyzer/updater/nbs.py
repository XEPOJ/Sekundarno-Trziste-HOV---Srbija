import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

import httpx

from .. import __version__
from ..db.repo import (
    KeyCollisionError, data_range, last_source_year, replace_year, set_meta, stored_count,
)
from ..ingest.parser import IngestError, parse_csv

NBS_URL = ("https://webappcenter.nbs.rs/WebApp/Securities/"
           "GovermentSecuritySecondaryTrade/Download")
FIRST_YEAR = 2020
_MIN_SHARE = 0.5     # a refreshed year must keep at least this share of the stored rows


class DownloadError(Exception):
    """Network/HTTP failure while fetching a yearly CSV."""


def download_year(year: int, *, base_url: str = NBS_URL, retries: int = 3,
                  backoff: float = 1.0, timeout: float = 30.0) -> bytes:
    headers = {"User-Agent": f"SecuritiesAnalyzer/{__version__}"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                resp = client.get(base_url, params={"Format": "csv", "Year": year})
            if resp.status_code == 200:
                return resp.content
            if resp.status_code < 500:
                raise DownloadError(f"HTTP {resp.status_code} za {year}. godinu")
            last = DownloadError(f"HTTP {resp.status_code} za {year}. godinu")
        except httpx.TransportError as e:
            last = DownloadError(f"Mrežna greška za {year}. godinu: {e}")
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    raise last  # type: ignore[misc]


def years_to_refresh(last_source_year: int | None, today: date) -> list[int]:
    if last_source_year is None:
        return list(range(FIRST_YEAR, today.year + 1))
    return list(range(min(last_source_year, today.year - 1), today.year + 1))


@dataclass
class YearReport:
    year: int
    status: str                      # "ok" | "error"
    added: int = 0
    removed: int = 0
    unchanged: int = 0
    message: str = ""


@dataclass
class UpdateReport:
    years: list[YearReport] = field(default_factory=list)
    data_end: str | None = None

    @property
    def ok(self) -> bool:
        return all(y.status == "ok" for y in self.years)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data_end": self.data_end, "years": [asdict(y) for y in self.years]}


def refresh(conn, *, today: date | None = None, fetch: Callable[[int], bytes] = download_year,
            progress: Callable[[str], None] | None = None) -> UpdateReport:
    say = progress or (lambda _m: None)
    today = today or date.today()
    report = UpdateReport()
    for y in years_to_refresh(last_source_year(conn), today):
        say(f"Preuzimam {y}. godinu…")
        try:
            rows = parse_csv(fetch(y))
            if not rows:
                raise IngestError("Fajl nema nijedan red")
            stored = stored_count(conn, y)
            if stored and len(rows) < stored * _MIN_SHARE:
                raise IngestError(
                    f"Novi fajl ima {len(rows)} redova, a baza {stored}: sumnjivo skraćen fajl")
            res = replace_year(conn, y, rows)
            report.years.append(YearReport(y, "ok", res.added, res.removed, res.unchanged))
            say(f"{y}: +{res.added} / -{res.removed} / nepromenjeno {res.unchanged}")
        except (DownloadError, IngestError, KeyCollisionError) as e:
            report.years.append(YearReport(y, "error", message=str(e)))
            say(f"{y}: GREŠKA — {e}")
    report.data_end = data_range(conn)[1]
    set_meta(conn, "last_update_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    set_meta(conn, "last_update_result", json.dumps(report.to_dict()))
    return report
