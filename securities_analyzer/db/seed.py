import os
import re
import shutil
from pathlib import Path

from ..ingest.parser import parse_csv
from .repo import replace_year
from .schema import connect, init_schema

_NAME = re.compile(r"GovermentSecuritySecondaryTrade_(\d{4})\.csv$")


def build_seed(csv_dir: Path, out_path: Path) -> int:
    """Import every yearly CSV in `csv_dir` into a fresh DB at `out_path`. Returns row count."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    files = [(m, f) for f in sorted(Path(csv_dir).glob("GovermentSecuritySecondaryTrade_*.csv"))
             if (m := _NAME.search(f.name))]
    if not files:
        raise ValueError(f"Nema godišnjih CSV fajlova u {csv_dir}")
    conn = connect(out_path)
    try:
        init_schema(conn)
        total = 0
        for m, f in files:
            rows = parse_csv(f.read_bytes())
            replace_year(conn, int(m.group(1)), rows)
            total += len(rows)
        if total == 0:
            raise ValueError(f"CSV fajlovi u {csv_dir} nemaju nijedan red (0 redova)")
        conn.execute("VACUUM")
    except BaseException:
        conn.close()
        out_path.unlink(missing_ok=True)       # never leave a half-built or empty seed behind
        raise
    conn.close()
    return total


def ensure_user_db(db_path: Path, seed_path: Path | None) -> None:
    """Create the user DB from the seed on first run; never overwrite an existing one."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        if seed_path is not None and Path(seed_path).exists():
            # Copy next to the target, then rename: a crash mid-copy never leaves a truncated data.db.
            tmp = db_path.with_name(db_path.name + ".tmp")
            try:
                shutil.copyfile(seed_path, tmp)
                os.replace(tmp, db_path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
    conn = connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()
