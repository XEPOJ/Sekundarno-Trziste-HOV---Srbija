import argparse
import sys
from datetime import date
from pathlib import Path

from .db.seed import build_seed
from .updater.nbs import FIRST_YEAR, download_year


def _fetch_all(out_dir: Path, from_year: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for year in range(from_year, date.today().year + 1):
        data = download_year(year)
        (out_dir / f"GovermentSecuritySecondaryTrade_{year}.csv").write_bytes(data)
        print(f"{year}: {len(data)} bytes")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="securities_analyzer")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start the application (default)")
    f = sub.add_parser("fetch-all", help="download all yearly CSVs from NBS")
    f.add_argument("out_dir", type=Path)
    f.add_argument("--from-year", type=int, default=FIRST_YEAR)
    b = sub.add_parser("build-seed", help="build a seed SQLite DB from yearly CSVs")
    b.add_argument("csv_dir", type=Path)
    b.add_argument("out_db", type=Path)
    args = p.parse_args(argv)

    if args.cmd in (None, "run"):
        from .app import run
        run()
        return 0
    if args.cmd == "fetch-all":
        return _fetch_all(args.out_dir, args.from_year)
    if args.cmd == "build-seed":
        try:
            n = build_seed(args.csv_dir, args.out_db)
        except ValueError as e:
            print(f"build-seed failed: {e}", file=sys.stderr)
            return 1
        print(f"Imported {n} rows into {args.out_db}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
