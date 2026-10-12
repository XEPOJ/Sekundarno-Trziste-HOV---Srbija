import csv
from datetime import datetime
from pathlib import Path
from typing import Literal


def unique_export_path(export_dir: Path, stem: str, ext: str) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_{datetime.now():%Y%m%d_%H%M%S}"
    path = export_dir / f"{base}.{ext}"
    n = 2
    while path.exists():
        path = export_dir / f"{base}_{n}.{ext}"
        n += 1
    return path


def write_table(path: Path, header: list[str], rows: list[list], fmt: Literal["csv", "xlsx"]) -> None:
    if fmt == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(header)
            w.writerows(rows)
        return
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Podaci"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
