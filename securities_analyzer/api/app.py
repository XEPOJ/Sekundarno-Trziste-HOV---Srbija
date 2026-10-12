import csv
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..db.repo import data_range, get_meta
from ..db.schema import connect
from ..query import service
from ..query.filters import FilterSpec
from ..updater.nbs import download_year, refresh
from .jobs import UpdateJob

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


class QueryBody(BaseModel):
    filter: FilterSpec = Field(default_factory=FilterSpec)


class RowsBody(QueryBody):
    sort: str = "trade_date"
    order: Literal["asc", "desc"] = "desc"
    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=1000)


class SeriesBody(QueryBody):
    granularity: Literal["day", "week", "month"] = "month"


class ExtremesBody(QueryBody):
    sort_by: str = "trade_date"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(500, ge=1, le=5000)


class ExportBody(QueryBody):
    format: Literal["csv", "xlsx"] = "csv"


class SaveBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filter: FilterSpec


def create_app(db_path: Path, *, fetch=download_year, export_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Securities Analyzer", version=__version__)
    export_dir = export_dir or (Path.home() / "Downloads")

    def get_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _run_update(progress):
        with closing(connect(db_path)) as conn:
            return refresh(conn, fetch=fetch, progress=progress)

    job = UpdateJob(_run_update)

    def _guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.get("/api/meta")
    def meta(conn=Depends(get_conn)):
        first, last, count = data_range(conn)
        raw = get_meta(conn, "last_update_result")
        return {
            "version": __version__, "rows": count,
            "first_trade_date": first, "last_trade_date": last,
            "last_update_utc": get_meta(conn, "last_update_utc"),
            "last_update_result": json.loads(raw) if raw else None,
        }

    @app.get("/api/securities")
    def securities(conn=Depends(get_conn)):
        return service.list_securities(conn)

    @app.post("/api/query/rows")
    def q_rows(body: RowsBody, conn=Depends(get_conn)):
        res = _guard(service.fetch_rows, conn, body.filter, sort=body.sort, order=body.order,
                     limit=body.page_size, offset=(body.page - 1) * body.page_size)
        return {**res, "page": body.page, "page_size": body.page_size}

    @app.post("/api/query/summary")
    def q_summary(body: QueryBody, conn=Depends(get_conn)):
        return {"kpis": service.kpis(conn, body.filter),
                "quality_flagged": service.quality_count(conn, body.filter)}

    @app.post("/api/query/timeseries")
    def q_timeseries(body: SeriesBody, conn=Depends(get_conn)):
        return _guard(service.yield_timeseries, conn, body.filter, body.granularity)

    @app.post("/api/query/scatter")
    def q_scatter(body: QueryBody, conn=Depends(get_conn)):
        return service.scatter(conn, body.filter)

    @app.post("/api/query/buckets")
    def q_buckets(body: QueryBody, conn=Depends(get_conn)):
        return service.maturity_buckets(conn, body.filter)

    @app.post("/api/query/extremes")
    def q_extremes(body: ExtremesBody, conn=Depends(get_conn)):
        return _guard(service.daily_extremes, conn, body.filter, sort_by=body.sort_by,
                      order=body.order, limit=body.limit)

    @app.post("/api/export")
    def export(body: ExportBody, conn=Depends(get_conn)):
        rows = service.fetch_rows(conn, body.filter, limit=10**9)["rows"]
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"securities_{datetime.now():%Y%m%d_%H%M%S}.{body.format}"
        cols = list(service.ROW_COLUMNS)
        if body.format == "csv":
            with path.open("w", encoding="utf-8-sig", newline="") as fp:
                w = csv.writer(fp)
                w.writerow(cols)
                w.writerows([[r[c] for c in cols] for r in rows])
        else:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Podaci"
            ws.append(cols)
            for r in rows:
                ws.append([r[c] for c in cols])
            wb.save(path)
        return {"path": str(path), "rows": len(rows)}

    @app.get("/api/saved-queries")
    def saved_list(conn=Depends(get_conn)):
        return [{"name": r["name"], "filter": json.loads(r["filter_json"])}
                for r in conn.execute("SELECT name, filter_json FROM saved_queries ORDER BY name")]

    @app.put("/api/saved-queries")
    def saved_put(body: SaveBody, conn=Depends(get_conn)):
        with conn:
            conn.execute(
                "INSERT INTO saved_queries (name, filter_json) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET filter_json = excluded.filter_json",
                (body.name, body.filter.model_dump_json()))
        return {"saved": body.name}

    @app.delete("/api/saved-queries/{name:path}")
    def saved_delete(name: str, conn=Depends(get_conn)):
        with conn:
            conn.execute("DELETE FROM saved_queries WHERE name = ?", (name,))
        return {"deleted": name}

    @app.post("/api/update")
    def update_start():
        return {"started": job.start()}

    @app.get("/api/update/status")
    def update_status():
        return job.snapshot()

    if UI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app
