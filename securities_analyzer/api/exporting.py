import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Literal


def unique_export_path(export_dir: Path, stem: str, ext: str) -> Path:
    """Reserve a fresh `<stem>_<timestamp>[_n].<ext>` by creating it exclusively (atomic).

    The returned path already exists as an empty file, so parallel callers can never get the same name.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_{datetime.now():%Y%m%d_%H%M%S}"
    path = export_dir / f"{base}.{ext}"
    n = 2
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except FileExistsError:
            path = export_dir / f"{base}_{n}.{ext}"
            n += 1


def write_table(path: Path, header: list[str], rows: list[list], fmt: Literal["csv", "xlsx"]) -> None:
    """Write to `<path>.part`, then atomically replace `path`. On any failure no file is left behind."""
    part = path.with_name(path.name + ".part")
    try:
        if fmt == "csv":
            with part.open("w", encoding="utf-8-sig", newline="") as fp:
                w = csv.writer(fp)
                w.writerow(header)
                w.writerows(rows)
        else:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Podaci"
            ws.append(header)
            for r in rows:
                ws.append(r)
            # Save to memory: openpyxl leaks its open ZipFile when it fails mid-save, which on
            # Windows would keep a file lock on the .part file and break the cleanup below.
            buf = io.BytesIO()
            wb.save(buf)
            part.write_bytes(buf.getvalue())
        os.replace(part, path)
    except BaseException:
        for f in (part, path):   # best effort and independent: never mask the original error
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        raise
