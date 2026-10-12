# Securities Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Windows program that stores the NBS secondary-market government-securities data (2020 → today) in a local SQLite file, lets the user query it with multi-dimensional filters and interactive charts, and updates itself from NBS with one button.

**Architecture:** Python package with strict module boundaries (`ingest` parses, `db` stores, `query` turns a validated `FilterSpec` into SQL, `updater` talks to NBS, `api` is thin JSON over those). A static HTML/JS frontend (vendored Plotly, no CDN) talks only to `/api/*`. A local uvicorn server on `127.0.0.1:<free port>` is shown in a pywebview window (browser fallback). PyInstaller one-folder build, released by GitHub Actions.

**Tech Stack:** Python 3.13, FastAPI + uvicorn, pydantic v2, httpx, openpyxl, SQLite (stdlib), pywebview, Plotly.js 2.35.2, pytest, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-12-securities-analyzer-design.md` (read it first; this plan refines it in the places listed under "Deviations from the spec").

## Global Constraints

- Python **3.13**; Windows is the only supported platform for v1.
- Repo root is `securities-analyzer/`, created inside a parent working folder. **All paths in this plan are relative to that repo root.**
- Everything runs locally. No server, accounts, cloud or telemetry. Server binds to `127.0.0.1` only.
- Business key of a row is `(trade_date, settlement_date, isin)` and is unique across the whole table. The year in a file name is only a *refresh unit* stored as `source_year`.
- Yields are percentage points (`5.14` = 5.14%). Dates are stored as ISO `YYYY-MM-DD` text.
- **Never sum or average across currencies.** Every total and every weighted yield is grouped by currency.
- Maturity filters: years × **365** = days. "More than" is strict (`>`), "at least" is `>=`; each bound carries its own `*_exclusive` flag, default inclusive.
- Default yield basis is the daily average yield (`avg_yield_pct`). Date bounds are inclusive on both ends.
- "Longer than 3 years" defaults to **remaining** maturity (`remaining_maturity_days`, value stored on each row).
- All SQL is parameterized. Anything interpolated into SQL (sort column, bucket, period expression) comes from a whitelist, never from user strings.
- UI text is Serbian (Latin script); code, identifiers and comments are English. Plotly is vendored, so the app works offline except for Update.
- Update never destroys data on network or format errors. Tests never touch the live NBS network.
- Footer must show "Podaci: Narodna banka Srbije".
- Commits: small, one per task step marked "Commit". Every commit message ends with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (second `-m`).
- On Windows consoles run Python with `-X utf8` (or set `PYTHONUTF8=1`) when printing Cyrillic.

## Deviations from the spec (apply the spec edits in Task 9, Step 5)

1. Numeric filters use a `Range {min, max, min_exclusive, max_exclusive}` model instead of separate `*_min`/`*_max` fields. This is how "yield **greater than** 3.5" and "at least" both work.
2. `scripts/build_seed.py` is replaced by CLI subcommands `python -m securities_analyzer build-seed` and `fetch-all`.
3. The release workflow builds the seed by **downloading from NBS in CI** (`fetch-all`), so no NBS data is committed to the repo (keeps the NBS-terms decision open, spec §11).
4. Currency codes are validated as any 3 uppercase letters (not only RSD/EUR) so a new currency on NBS never blocks an update.

## Verified facts the plan relies on (computed 2026-10-12 from the 7 local files)

- 5,309 rows, 0 duplicate business keys, all 18-column rows, **0 quality flags** with the rules in Task 1.
- The header is exactly the 18 Cyrillic names used in `EXPECTED_HEADER` (Task 1).
- Golden query (trade date 2023-02-02…2024-03-05 inclusive, remaining maturity > 1095 days strict, avg yield > 3.5 strict), computed independently in plain Python:
  - 388 rows total
  - RSD: 371 rows, turnover 155,830,121,796.84, weighted yield 6.093064, quantity 16,233,797, 3 ISINs
  - EUR: 17 rows, turnover 15,642,804.29, weighted yield 4.126739, quantity 16,859, 6 ISINs
  - Daily extremes on 2023-12-28, RSD, same filter: highest 6.27 (`RSMFRSD86176`), lowest 4.80 (`RSMFRSD55940`)
- Live endpoint `GET https://webappcenter.nbs.rs/WebApp/Securities/GovermentSecuritySecondaryTrade/Download?Format=csv&Year=<YYYY>` returns `text/csv`, UTF-8 with BOM, no auth.

## File structure

```
securities-analyzer/
  pyproject.toml
  .gitignore
  README.md
  run_app.py                          # PyInstaller entry point
  securities_analyzer/
    __init__.py                       # __version__
    __main__.py                       # CLI: run | fetch-all | build-seed
    paths.py                          # user data dir, seed path
    app.py                            # start server + window
    ingest/{__init__,models,parser,quality}.py
    db/{__init__,schema,repo,seed}.py
    query/{__init__,filters,builder,service}.py
    updater/{__init__,nbs}.py
    api/{__init__,app,jobs}.py
    ui/{index.html,styles.css,app.js,vendor/plotly.min.js}
  tests/
    conftest.py  factories.py
    test_ingest.py test_db.py test_builder.py test_service.py
    test_updater.py test_api.py test_real_data.py test_cli.py
  data/                               # raw/ and seed.db are generated, git-ignored
  .github/workflows/{ci,release}.yml
```

---

### Task 1: Scaffold, ingest parser and quality rules

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `securities_analyzer/__init__.py`, `securities_analyzer/ingest/__init__.py`, `securities_analyzer/ingest/models.py`, `securities_analyzer/ingest/parser.py`, `securities_analyzer/ingest/quality.py`
- Create: `tests/factories.py`, `tests/conftest.py` (ingest part), `tests/test_ingest.py`

**Interfaces:**
- Produces:
  - `securities_analyzer.ingest.models.TradeRow` — frozen dataclass, fields in this order: `trade_date: date, settlement_date: date, maturity_date: date, isin: str, original_maturity_days: int, currency: str, coupon_pct: float, remaining_maturity_days: int, quantity: int, transaction_count: int, nominal_per_unit: float, min_price: float, max_price: float, wavg_price: float, turnover: float, min_yield_pct: float, max_yield_pct: float, avg_yield_pct: float`; property `key -> tuple[date, date, str]`.
  - `models.EXPECTED_HEADER: list[str]` (18 names).
  - `parser.parse_csv(data: bytes) -> list[TradeRow]`, `parser.IngestError(ValueError)`.
  - `quality.quality_flag(row: TradeRow) -> str` (`"OK"` or comma-joined codes `PRICE_ORDER, YIELD_ORDER, SETTLE_BEFORE_TRADE, MATURITY_BEFORE_SETTLE, TURNOVER_MISMATCH`).
  - Test helpers `tests.factories.make_row(**overrides) -> TradeRow`, `tests.factories.rows_to_csv(rows) -> bytes`, `tests.factories.load_rows(conn, rows)` (added in Task 2).

- [ ] **Step 1: Create the repo and project files**

```powershell
cd <parent working folder>
mkdir securities-analyzer
cd securities-analyzer
git init
mkdir securities_analyzer, securities_analyzer\ingest, tests
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "securities-analyzer"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.32",
  "httpx>=0.27",
  "openpyxl>=3.1",
]

[project.optional-dependencies]
desktop = ["pywebview>=5.3"]
dev = ["pytest>=8", "pyinstaller>=6.10"]

[tool.setuptools.packages.find]
include = ["securities_analyzer*"]

[tool.setuptools.package-data]
securities_analyzer = ["ui/*", "ui/vendor/*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
data/raw/
data/seed.db
build/
dist/
*.spec
.pytest_cache/
```

`securities_analyzer/__init__.py`:

```python
__version__ = "0.1.0"
```

`securities_analyzer/ingest/__init__.py`: empty file.

`tests/__init__.py`: empty file (so `from tests.factories import ...` works with `pythonpath = ["."]`).

- [ ] **Step 2: Create the virtualenv and install**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,desktop]"
```

Expected: install succeeds, `python -m pytest --version` prints pytest 8.x.

- [ ] **Step 3: Write the failing tests**

`tests/factories.py`:

```python
from datetime import date

from securities_analyzer.ingest.models import EXPECTED_HEADER, TradeRow


def make_row(**kw) -> TradeRow:
    base = dict(
        trade_date=date(2023, 6, 15), settlement_date=date(2023, 6, 15),
        maturity_date=date(2030, 7, 30), isin="RSMFRSD00001",
        original_maturity_days=2556, currency="RSD", coupon_pct=5.0,
        remaining_maturity_days=2600, quantity=100, transaction_count=1,
        nominal_per_unit=10000.0, min_price=10000.0, max_price=10000.0,
        wavg_price=10000.0, turnover=1000000.0,
        min_yield_pct=5.0, max_yield_pct=5.0, avg_yield_pct=5.0,
    )
    if "turnover" in kw and "quantity" not in kw and "wavg_price" not in kw:
        t = kw["turnover"]
        base.update(quantity=1, wavg_price=t, min_price=t, max_price=t)
    if "avg_yield_pct" in kw and "min_yield_pct" not in kw and "max_yield_pct" not in kw:
        base.update(min_yield_pct=kw["avg_yield_pct"], max_yield_pct=kw["avg_yield_pct"])
    base.update(kw)
    return TradeRow(**base)


def rows_to_csv(rows) -> bytes:
    """Serialize rows the way NBS does: ', '-separated Cyrillic header, plain ',' rows, BOM."""
    lines = [", ".join(EXPECTED_HEADER)]
    for r in rows:
        lines.append(",".join([
            r.trade_date.isoformat(), r.settlement_date.isoformat(), r.maturity_date.isoformat(),
            r.isin, str(r.original_maturity_days), r.currency, f"{r.coupon_pct:.2f}",
            str(r.remaining_maturity_days), str(r.quantity), str(r.transaction_count),
            f"{r.nominal_per_unit:.0f}", f"{r.min_price:.2f}", f"{r.max_price:.2f}",
            f"{r.wavg_price:.2f}", f"{r.turnover:.2f}", f"{r.min_yield_pct:.2f}",
            f"{r.max_yield_pct:.2f}", f"{r.avg_yield_pct:.2f}",
        ]))
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")
```

`tests/test_ingest.py`:

```python
from datetime import date

import pytest

from securities_analyzer.ingest.parser import IngestError, parse_csv
from securities_analyzer.ingest.quality import quality_flag
from tests.factories import make_row, rows_to_csv


def test_round_trip_two_rows():
    rows = [make_row(), make_row(isin="RSMFRSD00002", currency="EUR", turnover=1234.56)]
    assert parse_csv(rows_to_csv(rows)) == rows


def test_key_is_trade_settlement_isin():
    r = make_row(settlement_date=date(2023, 6, 19))
    assert r.key == (date(2023, 6, 15), date(2023, 6, 19), "RSMFRSD00001")


def test_blank_lines_are_ignored():
    data = rows_to_csv([make_row()]) + b"\n\n"
    assert len(parse_csv(data)) == 1


def test_header_change_is_rejected():
    data = rows_to_csv([make_row()]).replace("ISIN".encode(), b"ISIN2", 1)
    with pytest.raises(IngestError, match="Zaglavlje"):
        parse_csv(data)


def test_html_instead_of_csv_is_rejected():
    with pytest.raises(IngestError):
        parse_csv(b"<!doctype html><html><body>Error</body></html>")


def test_bad_number_reports_line():
    data = rows_to_csv([make_row()]).replace(b",5.00,", b",abc,", 1)
    with pytest.raises(IngestError, match="Red 2"):
        parse_csv(data)


def test_wrong_column_count_reports_line():
    lines = rows_to_csv([make_row()]).decode("utf-8").rstrip("\n").split("\n")
    lines[1] = lines[1] + ",extra"
    with pytest.raises(IngestError, match="Red 2"):
        parse_csv(("\n".join(lines) + "\n").encode("utf-8"))


def test_duplicate_key_in_file_is_rejected():
    with pytest.raises(IngestError, match="duplirani"):
        parse_csv(rows_to_csv([make_row(), make_row()]))


def test_empty_file_is_rejected():
    with pytest.raises(IngestError):
        parse_csv(b"")


def test_quality_ok_row():
    assert quality_flag(make_row()) == "OK"


@pytest.mark.parametrize("overrides,code", [
    (dict(min_price=10001.0), "PRICE_ORDER"),
    (dict(min_yield_pct=6.0), "YIELD_ORDER"),
    (dict(settlement_date=date(2023, 6, 14)), "SETTLE_BEFORE_TRADE"),
    (dict(maturity_date=date(2023, 6, 1)), "MATURITY_BEFORE_SETTLE"),
    (dict(turnover=999.0), "TURNOVER_MISMATCH"),
])
def test_quality_flags(overrides, code):
    row = make_row()
    row = type(row)(**{**row.__dict__, **overrides})
    assert code in quality_flag(row).split(",")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: securities_analyzer.ingest.models`.

- [ ] **Step 5: Implement**

`securities_analyzer/ingest/models.py`:

```python
from dataclasses import dataclass
from datetime import date

EXPECTED_HEADER = [
    "Датум трговања", "Датум салдирања", "Датум доспећа", "ISIN", "Рочност у данима",
    "Валута", "Купонска стопа", "Преостала рочност у данима", "Количина",
    "Број трансакција", "Номинална цена по комаду", "Минимална цена", "Максимална цена",
    "Просечна пондерисана цена", "Укупан промет", "Минимални принос",
    "Максимални принос", "Просечни принос",
]


@dataclass(frozen=True)
class TradeRow:
    trade_date: date
    settlement_date: date
    maturity_date: date
    isin: str
    original_maturity_days: int
    currency: str
    coupon_pct: float
    remaining_maturity_days: int
    quantity: int
    transaction_count: int
    nominal_per_unit: float
    min_price: float
    max_price: float
    wavg_price: float
    turnover: float
    min_yield_pct: float
    max_yield_pct: float
    avg_yield_pct: float

    @property
    def key(self) -> tuple[date, date, str]:
        return (self.trade_date, self.settlement_date, self.isin)
```

`securities_analyzer/ingest/parser.py`:

```python
import csv
import io
import re
from datetime import date

from .models import EXPECTED_HEADER, TradeRow

_CURRENCY = re.compile(r"^[A-Z]{3}$")


class IngestError(ValueError):
    """The downloaded/parsed file is not a valid NBS secondary-trade CSV."""


def _to_row(c: list[str]) -> TradeRow:
    currency = c[5]
    if not _CURRENCY.match(currency):
        raise ValueError(f"neispravna valuta {currency!r}")
    if not c[3]:
        raise ValueError("prazan ISIN")
    return TradeRow(
        trade_date=date.fromisoformat(c[0]),
        settlement_date=date.fromisoformat(c[1]),
        maturity_date=date.fromisoformat(c[2]),
        isin=c[3],
        original_maturity_days=int(c[4]),
        currency=currency,
        coupon_pct=float(c[6]),
        remaining_maturity_days=int(c[7]),
        quantity=int(c[8]),
        transaction_count=int(c[9]),
        nominal_per_unit=float(c[10]),
        min_price=float(c[11]),
        max_price=float(c[12]),
        wavg_price=float(c[13]),
        turnover=float(c[14]),
        min_yield_pct=float(c[15]),
        max_yield_pct=float(c[16]),
        avg_yield_pct=float(c[17]),
    )


def parse_csv(data: bytes) -> list[TradeRow]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise IngestError(f"Fajl nije UTF-8: {e}") from e
    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    try:
        header = [c.strip() for c in next(reader)]
    except StopIteration:
        raise IngestError("Prazan fajl") from None
    if header != EXPECTED_HEADER:
        raise IngestError("Zaglavlje se ne poklapa sa očekivanim (NBS je možda promenio format)")
    rows: list[TradeRow] = []
    seen: set = set()
    for lineno, cells in enumerate(reader, start=2):
        if not cells or all(not c.strip() for c in cells):
            continue
        if len(cells) != len(EXPECTED_HEADER):
            raise IngestError(f"Red {lineno}: očekivano {len(EXPECTED_HEADER)} kolona, nađeno {len(cells)}")
        try:
            row = _to_row([c.strip() for c in cells])
        except ValueError as e:
            raise IngestError(f"Red {lineno}: {e}") from e
        if row.key in seen:
            raise IngestError(f"Red {lineno}: duplirani ključ {row.key}")
        seen.add(row.key)
        rows.append(row)
    return rows
```

`securities_analyzer/ingest/quality.py`:

```python
from .models import TradeRow


def quality_flag(r: TradeRow) -> str:
    problems = []
    if not (r.min_price <= r.wavg_price <= r.max_price):
        problems.append("PRICE_ORDER")
    if not (r.min_yield_pct <= r.avg_yield_pct <= r.max_yield_pct):
        problems.append("YIELD_ORDER")
    if r.settlement_date < r.trade_date:
        problems.append("SETTLE_BEFORE_TRADE")
    if r.maturity_date < r.settlement_date:
        problems.append("MATURITY_BEFORE_SETTLE")
    # Published average price has 2 decimals: allow half a unit of rounding per piece.
    if abs(r.turnover - r.quantity * r.wavg_price) > r.quantity * 0.005 + 0.02:
        problems.append("TURNOVER_MISMATCH")
    return ",".join(problems) or "OK"
```

`tests/conftest.py` (ingest part; extended in Task 2):

```python
# Shared fixtures are added task by task.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```powershell
git add -A
git commit -m "feat: project scaffold, NBS CSV parser and quality rules" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: SQLite layer, replace-by-year, seed

**Files:**
- Create: `securities_analyzer/db/__init__.py` (empty), `securities_analyzer/db/schema.py`, `securities_analyzer/db/repo.py`, `securities_analyzer/db/seed.py`, `securities_analyzer/paths.py`
- Modify: `tests/factories.py` (add `load_rows`), `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `TradeRow`, `quality_flag`, `parse_csv`, `rows_to_csv`.
- Produces:
  - `schema.connect(path: str | Path) -> sqlite3.Connection` (row_factory `sqlite3.Row`, `check_same_thread=False`); `schema.init_schema(conn) -> None`; `schema.SCHEMA_VERSION = 1`.
  - `repo.YearResult(year:int, added:int, removed:int, unchanged:int)`; `repo.KeyCollisionError(Exception)`.
  - `repo.replace_year(conn, year:int, rows: list[TradeRow]) -> YearResult` (atomic).
  - `repo.stored_count(conn, year) -> int`; `repo.last_source_year(conn) -> int | None`; `repo.data_range(conn) -> tuple[str | None, str | None, int]` (min trade_date, max trade_date, row count); `repo.get_meta(conn, key) -> str | None`; `repo.set_meta(conn, key, value:str) -> None`.
  - `seed.build_seed(csv_dir: Path, out_path: Path) -> int` (rows imported); `seed.ensure_user_db(db_path: Path, seed_path: Path | None) -> None`.
  - `paths.user_data_dir() -> Path`; `paths.seed_path() -> Path`.
  - Tables: `trades`, view `securities`, `meta`, `saved_queries(name, filter_json)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/factories.py`:

```python
from securities_analyzer.db.repo import replace_year


def load_rows(conn, rows):
    """Insert rows grouped by settlement year (mirrors NBS yearly files)."""
    by_year: dict[int, list] = {}
    for r in rows:
        by_year.setdefault(r.settlement_date.year, []).append(r)
    for year, rs in by_year.items():
        replace_year(conn, year, rs)
```

`tests/conftest.py`:

```python
import os
from pathlib import Path

import pytest

from securities_analyzer.db.schema import connect, init_schema


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    yield c
    c.close()


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    c = connect(p)
    init_schema(c)
    c.close()
    return p


def find_raw_dir() -> Path | None:
    default = Path(__file__).resolve().parents[2] / "outputs" / "PowerBI_Data" / "RawData"
    d = Path(os.environ.get("SA_RAW_DIR", default))
    return d if d.is_dir() and list(d.glob("GovermentSecuritySecondaryTrade_*.csv")) else None


@pytest.fixture(scope="session")
def real_conn(tmp_path_factory):
    raw = find_raw_dir()
    if raw is None:
        pytest.skip("real NBS CSV files not available (set SA_RAW_DIR)")
    from securities_analyzer.db.seed import build_seed
    out = tmp_path_factory.mktemp("seed") / "seed.db"
    build_seed(raw, out)
    c = connect(out)
    yield c
    c.close()
```

`tests/test_db.py`:

```python
from datetime import date

import pytest

from securities_analyzer.db.repo import (
    KeyCollisionError, data_range, get_meta, last_source_year, replace_year,
    set_meta, stored_count,
)
from securities_analyzer.db.schema import connect, init_schema
from securities_analyzer.db.seed import build_seed, ensure_user_db
from tests.factories import load_rows, make_row, rows_to_csv


def test_schema_objects(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"trades", "securities", "meta", "saved_queries"} <= names
    assert get_meta(conn, "schema_version") == "1"


def test_replace_year_inserts_and_derives_columns(conn):
    r = make_row(settlement_date=date(2023, 6, 19))
    res = replace_year(conn, 2023, [r])
    assert (res.added, res.removed, res.unchanged) == (1, 0, 0)
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["trade_date"] == "2023-06-15"
    assert row["source_year"] == 2023
    assert row["settlement_lag_days"] == 4
    assert row["quality_flag"] == "OK"


def test_replace_year_reports_diff(conn):
    a, b, c = (make_row(isin=f"RSMFRSD0000{i}") for i in (1, 2, 3))
    replace_year(conn, 2023, [a, b])
    res = replace_year(conn, 2023, [b, c])
    assert (res.added, res.removed, res.unchanged) == (1, 1, 1)
    assert stored_count(conn, 2023) == 2


def test_replace_year_is_atomic_on_key_collision(conn):
    a = make_row()
    replace_year(conn, 2023, [a])
    other = make_row(isin="RSMFRSD00009")
    with pytest.raises(KeyCollisionError):
        replace_year(conn, 2024, [other, a])      # `a` already stored under 2023
    assert stored_count(conn, 2024) == 0
    assert stored_count(conn, 2023) == 1


def test_last_source_year_and_range(conn):
    assert last_source_year(conn) is None
    assert data_range(conn) == (None, None, 0)
    load_rows(conn, [
        make_row(trade_date=date(2022, 12, 30), settlement_date=date(2023, 1, 3)),
        make_row(trade_date=date(2023, 6, 15), isin="RSMFRSD00002"),
    ])
    assert last_source_year(conn) == 2023
    assert data_range(conn) == ("2022-12-30", "2023-06-15", 2)


def test_meta_roundtrip(conn):
    set_meta(conn, "k", "v1")
    set_meta(conn, "k", "v2")
    assert get_meta(conn, "k") == "v2"
    assert get_meta(conn, "missing") is None


def test_securities_view(conn):
    load_rows(conn, [make_row(), make_row(trade_date=date(2023, 6, 16), settlement_date=date(2023, 6, 16))])
    rows = conn.execute("SELECT * FROM securities").fetchall()
    assert len(rows) == 1 and rows[0]["trade_rows"] == 2


def test_build_seed_and_ensure_user_db(tmp_path):
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "GovermentSecuritySecondaryTrade_2022.csv").write_bytes(
        rows_to_csv([make_row(trade_date=date(2022, 5, 5), settlement_date=date(2022, 5, 5))]))
    (csv_dir / "GovermentSecuritySecondaryTrade_2023.csv").write_bytes(rows_to_csv([make_row()]))
    seed = tmp_path / "seed.db"
    assert build_seed(csv_dir, seed) == 2

    user = tmp_path / "user" / "data.db"
    ensure_user_db(user, seed)                       # copies the seed
    c = connect(user)
    assert data_range(c)[2] == 2
    replace_year(c, 2023, [])                        # user modifies their DB
    c.close()
    ensure_user_db(user, seed)                       # must NOT overwrite
    c = connect(user)
    assert data_range(c)[2] == 1
    c.close()


def test_ensure_user_db_without_seed_creates_empty(tmp_path):
    user = tmp_path / "x" / "data.db"
    ensure_user_db(user, None)
    c = connect(user)
    assert data_range(c) == (None, None, 0)
    c.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.db...`.

- [ ] **Step 3: Implement**

`securities_analyzer/db/schema.py`:

```python
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY,
  trade_date TEXT NOT NULL,
  settlement_date TEXT NOT NULL,
  maturity_date TEXT NOT NULL,
  isin TEXT NOT NULL,
  original_maturity_days INTEGER NOT NULL,
  currency TEXT NOT NULL,
  coupon_pct REAL NOT NULL,
  remaining_maturity_days INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  transaction_count INTEGER NOT NULL,
  nominal_per_unit REAL NOT NULL,
  min_price REAL NOT NULL,
  max_price REAL NOT NULL,
  wavg_price REAL NOT NULL,
  turnover REAL NOT NULL,
  min_yield_pct REAL NOT NULL,
  max_yield_pct REAL NOT NULL,
  avg_yield_pct REAL NOT NULL,
  source_year INTEGER NOT NULL,
  settlement_lag_days INTEGER NOT NULL,
  quality_flag TEXT NOT NULL,
  UNIQUE (trade_date, settlement_date, isin)
);
CREATE INDEX IF NOT EXISTS ix_trades_trade_date ON trades (trade_date);
CREATE INDEX IF NOT EXISTS ix_trades_isin ON trades (isin);
CREATE INDEX IF NOT EXISTS ix_trades_remaining ON trades (remaining_maturity_days);
CREATE INDEX IF NOT EXISTS ix_trades_avg_yield ON trades (avg_yield_pct);
CREATE INDEX IF NOT EXISTS ix_trades_source_year ON trades (source_year);

CREATE VIEW IF NOT EXISTS securities AS
SELECT isin,
       MAX(maturity_date) AS maturity_date,
       MAX(currency) AS currency,
       MAX(coupon_pct) AS coupon_pct,
       MAX(nominal_per_unit) AS nominal_per_unit,
       MAX(original_maturity_days) AS original_maturity_days,
       MIN(trade_date) AS first_trade,
       MAX(trade_date) AS last_trade,
       COUNT(*) AS trade_rows
FROM trades GROUP BY isin;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
```

`securities_analyzer/db/repo.py`:

```python
import sqlite3
from dataclasses import dataclass

from ..ingest.models import TradeRow
from ..ingest.quality import quality_flag

_INSERT = """
INSERT INTO trades (
  trade_date, settlement_date, maturity_date, isin, original_maturity_days, currency,
  coupon_pct, remaining_maturity_days, quantity, transaction_count, nominal_per_unit,
  min_price, max_price, wavg_price, turnover, min_yield_pct, max_yield_pct, avg_yield_pct,
  source_year, settlement_lag_days, quality_flag
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


class KeyCollisionError(Exception):
    """A row's business key already exists under a different source year."""


@dataclass
class YearResult:
    year: int
    added: int
    removed: int
    unchanged: int


def _values(r: TradeRow, year: int) -> tuple:
    return (
        r.trade_date.isoformat(), r.settlement_date.isoformat(), r.maturity_date.isoformat(),
        r.isin, r.original_maturity_days, r.currency, r.coupon_pct, r.remaining_maturity_days,
        r.quantity, r.transaction_count, r.nominal_per_unit, r.min_price, r.max_price,
        r.wavg_price, r.turnover, r.min_yield_pct, r.max_yield_pct, r.avg_yield_pct,
        year, (r.settlement_date - r.trade_date).days, quality_flag(r),
    )


def replace_year(conn: sqlite3.Connection, year: int, rows: list[TradeRow]) -> YearResult:
    """Replace every row of `source_year == year` in ONE transaction."""
    old = {
        (r["trade_date"], r["settlement_date"], r["isin"])
        for r in conn.execute(
            "SELECT trade_date, settlement_date, isin FROM trades WHERE source_year = ?", (year,))
    }
    new = {(r.trade_date.isoformat(), r.settlement_date.isoformat(), r.isin) for r in rows}
    try:
        with conn:
            conn.execute("DELETE FROM trades WHERE source_year = ?", (year,))
            conn.executemany(_INSERT, [_values(r, year) for r in rows])
    except sqlite3.IntegrityError as e:
        raise KeyCollisionError(f"Kolizija ključa pri zameni godine {year}: {e}") from e
    return YearResult(year, added=len(new - old), removed=len(old - new), unchanged=len(new & old))


def stored_count(conn: sqlite3.Connection, year: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM trades WHERE source_year = ?", (year,)).fetchone()[0]


def last_source_year(conn: sqlite3.Connection) -> int | None:
    return conn.execute("SELECT MAX(source_year) FROM trades").fetchone()[0]


def data_range(conn: sqlite3.Connection) -> tuple[str | None, str | None, int]:
    r = conn.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM trades").fetchone()
    return (r[0], r[1], r[2])


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
```

`securities_analyzer/db/seed.py`:

```python
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
    conn = connect(out_path)
    init_schema(conn)
    total = 0
    for f in sorted(Path(csv_dir).glob("GovermentSecuritySecondaryTrade_*.csv")):
        m = _NAME.search(f.name)
        if not m:
            continue
        rows = parse_csv(f.read_bytes())
        replace_year(conn, int(m.group(1)), rows)
        total += len(rows)
    conn.execute("VACUUM")
    conn.close()
    return total


def ensure_user_db(db_path: Path, seed_path: Path | None) -> None:
    """Create the user DB from the seed on first run; never overwrite an existing one."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        if seed_path is not None and Path(seed_path).exists():
            shutil.copyfile(seed_path, db_path)
    conn = connect(db_path)
    init_schema(conn)
    conn.close()
```

`securities_analyzer/paths.py`:

```python
import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "SecuritiesAnalyzer"


def seed_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "data" / "seed.db"
    return Path(__file__).resolve().parents[1] / "data" / "seed.db"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py tests/test_ingest.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: SQLite schema, atomic replace-by-year, seed build" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: FilterSpec and SQL WHERE builder

**Files:**
- Create: `securities_analyzer/query/__init__.py` (empty), `securities_analyzer/query/filters.py`, `securities_analyzer/query/builder.py`
- Test: `tests/test_builder.py`

**Interfaces:**
- Produces:
  - `filters.Range` (pydantic): `min: float|None, max: float|None, min_exclusive: bool=False, max_exclusive: bool=False`; rejects `min > max`.
  - `filters.FilterSpec` (pydantic, `extra="forbid"`): `date_from: date|None, date_to: date|None, yield_pct: Range, yield_basis: Literal["avg","min","max"]="avg", remaining_maturity_years: Range, original_maturity_years: Range, coupon_pct: Range, settlement_lag_days: Range, turnover_min: float|None, currency: list[str], isin: list[str]`.
  - `filters.YEAR_DAYS = 365`.
  - `builder.build_where(spec: FilterSpec) -> tuple[str, list]` — SQL fragment (never empty; `"1=1"` when no filters) over the `trades` table, plus positional params.

- [ ] **Step 1: Write the failing tests**

`tests/test_builder.py`:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from securities_analyzer.query.builder import build_where
from securities_analyzer.query.filters import FilterSpec, Range
from tests.factories import load_rows, make_row


def pick(conn, spec, col="trade_date"):
    where, params = build_where(spec)
    return [r[0] for r in conn.execute(f"SELECT {col} FROM trades WHERE {where} ORDER BY {col}, id", params)]


def test_empty_spec_matches_everything():
    assert build_where(FilterSpec()) == ("1=1", [])


def test_dates_are_inclusive_on_both_ends(conn):
    days = [date(2023, 2, 1), date(2023, 2, 2), date(2023, 3, 5), date(2023, 3, 6)]
    load_rows(conn, [make_row(trade_date=d, settlement_date=d) for d in days])
    spec = FilterSpec(date_from=date(2023, 2, 2), date_to=date(2023, 3, 5))
    assert pick(conn, spec) == ["2023-02-02", "2023-03-05"]


def test_yield_strict_vs_inclusive(conn):
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", avg_yield_pct=y) for i, y in enumerate([3.4, 3.5, 3.6], 1)])
    strict = FilterSpec(yield_pct=Range(min=3.5, min_exclusive=True))
    incl = FilterSpec(yield_pct=Range(min=3.5))
    assert pick(conn, strict, "avg_yield_pct") == [3.6]
    assert pick(conn, incl, "avg_yield_pct") == [3.5, 3.6]


def test_yield_basis_max(conn):
    load_rows(conn, [make_row(min_yield_pct=3.0, avg_yield_pct=3.5, max_yield_pct=4.0)])
    assert pick(conn, FilterSpec(yield_pct=Range(min=3.9), yield_basis="max")) != []
    assert pick(conn, FilterSpec(yield_pct=Range(min=3.9), yield_basis="avg")) == []
    assert pick(conn, FilterSpec(yield_pct=Range(max=3.1), yield_basis="min")) != []


def test_remaining_maturity_three_years_strict(conn):
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", remaining_maturity_days=d)
                     for i, d in enumerate([1094, 1095, 1096], 1)])
    strict = FilterSpec(remaining_maturity_years=Range(min=3, min_exclusive=True))
    incl = FilterSpec(remaining_maturity_years=Range(min=3))
    assert pick(conn, strict, "remaining_maturity_days") == [1096]
    assert pick(conn, incl, "remaining_maturity_days") == [1095, 1096]


def test_original_maturity_and_coupon_and_lag(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD00001", original_maturity_days=730, coupon_pct=1.7),
        make_row(isin="RSMFRSD00002", original_maturity_days=3650, coupon_pct=5.5,
                 settlement_date=date(2023, 6, 19)),
    ])
    assert pick(conn, FilterSpec(original_maturity_years=Range(min=5)), "isin") == ["RSMFRSD00002"]
    assert pick(conn, FilterSpec(coupon_pct=Range(max=2)), "isin") == ["RSMFRSD00001"]
    assert pick(conn, FilterSpec(settlement_lag_days=Range(min=1)), "isin") == ["RSMFRSD00002"]


def test_currency_isin_turnover(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD00001", currency="RSD", turnover=100.0),
        make_row(isin="RSMFRSD00002", currency="EUR", turnover=900.0),
    ])
    assert pick(conn, FilterSpec(currency=["EUR"]), "isin") == ["RSMFRSD00002"]
    assert pick(conn, FilterSpec(isin=["RSMFRSD00001"]), "isin") == ["RSMFRSD00001"]
    assert pick(conn, FilterSpec(turnover_min=500), "isin") == ["RSMFRSD00002"]


def test_filters_are_anded(conn):
    load_rows(conn, [make_row(isin="RSMFRSD00001", currency="RSD", avg_yield_pct=4.0),
                     make_row(isin="RSMFRSD00002", currency="EUR", avg_yield_pct=4.0)])
    spec = FilterSpec(currency=["RSD"], yield_pct=Range(min=3.5))
    assert pick(conn, spec, "isin") == ["RSMFRSD00001"]


@pytest.mark.parametrize("kwargs", [
    dict(yield_pct=dict(min=5, max=4)),
    dict(date_from=date(2024, 1, 1), date_to=date(2023, 1, 1)),
    dict(currency=["rsd"]),
    dict(currency=["RSDX"]),
    dict(isin=["x' OR 1=1 --"]),
    dict(yield_basis="median"),
    dict(unknown_field=1),
])
def test_validation_rejects(kwargs):
    with pytest.raises(ValidationError):
        FilterSpec(**kwargs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.query`.

- [ ] **Step 3: Implement**

`securities_analyzer/query/filters.py`:

```python
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

YEAR_DAYS = 365
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ISIN = re.compile(r"^[A-Z0-9]{12}$")


class Range(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float | None = None
    max: float | None = None
    min_exclusive: bool = False
    max_exclusive: bool = False

    @model_validator(mode="after")
    def _ordered(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("donja granica je veća od gornje")
        return self


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date | None = None
    date_to: date | None = None
    yield_pct: Range = Field(default_factory=Range)
    yield_basis: Literal["avg", "min", "max"] = "avg"
    remaining_maturity_years: Range = Field(default_factory=Range)
    original_maturity_years: Range = Field(default_factory=Range)
    coupon_pct: Range = Field(default_factory=Range)
    settlement_lag_days: Range = Field(default_factory=Range)
    turnover_min: float | None = None
    currency: list[str] = Field(default_factory=list)
    isin: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _currencies(cls, v):
        for c in v:
            if not _CURRENCY.match(c):
                raise ValueError(f"neispravna valuta {c!r}")
        return v

    @field_validator("isin")
    @classmethod
    def _isins(cls, v):
        for i in v:
            if not _ISIN.match(i):
                raise ValueError(f"neispravan ISIN {i!r}")
        return v

    @model_validator(mode="after")
    def _dates_ordered(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("datum 'od' je posle datuma 'do'")
        return self
```

`securities_analyzer/query/builder.py`:

```python
from .filters import YEAR_DAYS, FilterSpec, Range

_YIELD_COL = {"avg": "avg_yield_pct", "min": "min_yield_pct", "max": "max_yield_pct"}


def _range(col: str, rng: Range, scale: float, clauses: list, params: list) -> None:
    if rng.min is not None:
        clauses.append(f"{col} {'>' if rng.min_exclusive else '>='} ?")
        params.append(rng.min * scale)
    if rng.max is not None:
        clauses.append(f"{col} {'<' if rng.max_exclusive else '<='} ?")
        params.append(rng.max * scale)


def build_where(spec: FilterSpec) -> tuple[str, list]:
    """Return (SQL fragment over `trades`, params). Only whitelisted identifiers are interpolated."""
    clauses: list[str] = []
    params: list = []
    if spec.date_from:
        clauses.append("trade_date >= ?")
        params.append(spec.date_from.isoformat())
    if spec.date_to:
        clauses.append("trade_date <= ?")
        params.append(spec.date_to.isoformat())
    _range(_YIELD_COL[spec.yield_basis], spec.yield_pct, 1, clauses, params)
    _range("remaining_maturity_days", spec.remaining_maturity_years, YEAR_DAYS, clauses, params)
    _range("original_maturity_days", spec.original_maturity_years, YEAR_DAYS, clauses, params)
    _range("coupon_pct", spec.coupon_pct, 1, clauses, params)
    _range("settlement_lag_days", spec.settlement_lag_days, 1, clauses, params)
    if spec.turnover_min is not None:
        clauses.append("turnover >= ?")
        params.append(spec.turnover_min)
    if spec.currency:
        clauses.append(f"currency IN ({','.join('?' * len(spec.currency))})")
        params.extend(spec.currency)
    if spec.isin:
        clauses.append(f"isin IN ({','.join('?' * len(spec.isin))})")
        params.extend(spec.isin)
    return (" AND ".join(clauses) or "1=1"), params
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_builder.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: FilterSpec validation and parameterized WHERE builder" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Query service (rows, KPIs, series, buckets, daily extremes) + golden test

**Files:**
- Create: `securities_analyzer/query/service.py`, `tests/test_service.py`, `tests/test_real_data.py`

**Interfaces:**
- Consumes: `FilterSpec`, `build_where`, `connect`, `load_rows`, `make_row`.
- Produces (all take `(conn, spec: FilterSpec, ...)` and return plain `list[dict]` / `dict`):
  - `ROW_COLUMNS: tuple[str, ...]`, `SORTABLE: frozenset[str]`
  - `fetch_rows(conn, spec, *, sort="trade_date", order="desc", limit=100, offset=0) -> dict` → `{"total": int, "rows": list[dict]}`; raises `ValueError` for non-whitelisted `sort`.
  - `kpis(conn, spec) -> list[dict]` per currency: `currency, turnover, quantity, transactions, isins, active_days, row_count, weighted_yield_pct`.
  - `yield_timeseries(conn, spec, granularity: "day"|"week"|"month") -> list[dict]`: `period (ISO date), currency, weighted_yield_pct, turnover`.
  - `scatter(conn, spec) -> list[dict]`: `trade_date, isin, currency, remaining_maturity_days, avg_yield_pct, turnover` (max 20000 rows).
  - `maturity_buckets(conn, spec) -> list[dict]`: `bucket, currency, turnover, row_count`, ordered by bucket order.
  - `daily_extremes(conn, spec, *, sort_by="trade_date", order="desc", limit=500) -> list[dict]`: `trade_date, currency, highest_pct, highest_isin, lowest_pct, lowest_isin, range_pct`.
  - `quality_count(conn, spec) -> int`; `list_securities(conn) -> list[dict]`.

- [ ] **Step 1: Write the failing unit tests**

`tests/test_service.py`:

```python
from datetime import date

import pytest

from securities_analyzer.query import service
from securities_analyzer.query.filters import FilterSpec, Range
from tests.factories import load_rows, make_row

ALL = FilterSpec()
D = date(2023, 6, 15)


@pytest.fixture
def sample(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", currency="RSD", turnover=100.0, avg_yield_pct=4.0),
        make_row(isin="RSMFRSD0000B", currency="RSD", turnover=300.0, avg_yield_pct=6.0),
        make_row(isin="RSMFRSD0000C", currency="EUR", turnover=50.0, avg_yield_pct=3.0),
        make_row(isin="RSMFRSD0000A", currency="RSD", turnover=100.0, avg_yield_pct=5.0,
                 trade_date=date(2023, 7, 3), settlement_date=date(2023, 7, 3)),
    ])
    return conn


def test_fetch_rows_paging_sort_and_total(sample):
    res = service.fetch_rows(sample, ALL, sort="turnover", order="desc", limit=2, offset=0)
    assert res["total"] == 4
    assert [r["turnover"] for r in res["rows"]] == [300.0, 100.0]
    res2 = service.fetch_rows(sample, ALL, sort="turnover", order="asc", limit=10, offset=3)
    assert [r["turnover"] for r in res2["rows"]] == [300.0]


def test_fetch_rows_rejects_unknown_sort(sample):
    with pytest.raises(ValueError):
        service.fetch_rows(sample, ALL, sort="id; DROP TABLE trades")


def test_kpis_are_split_by_currency_and_weighted(sample):
    k = {r["currency"]: r for r in service.kpis(sample, ALL)}
    assert set(k) == {"RSD", "EUR"}
    assert k["RSD"]["turnover"] == 500.0
    assert k["RSD"]["isins"] == 2 and k["RSD"]["active_days"] == 2 and k["RSD"]["row_count"] == 3
    assert k["RSD"]["weighted_yield_pct"] == pytest.approx((4 * 100 + 6 * 300 + 5 * 100) / 500)
    assert k["EUR"]["weighted_yield_pct"] == pytest.approx(3.0)


def test_kpis_honour_filters(sample):
    k = service.kpis(sample, FilterSpec(currency=["EUR"]))
    assert [r["currency"] for r in k] == ["EUR"]


def test_timeseries_month_week_day(sample):
    month = [r for r in service.yield_timeseries(sample, ALL, "month") if r["currency"] == "RSD"]
    assert [(r["period"], round(r["weighted_yield_pct"], 4)) for r in month] == [
        ("2023-06-01", 5.5), ("2023-07-01", 5.0)]
    week = [r["period"] for r in service.yield_timeseries(sample, ALL, "week") if r["currency"] == "RSD"]
    assert week == ["2023-06-12", "2023-07-03"]      # Mondays (2023-06-15 is a Thursday, 2023-07-03 a Monday)
    day = [r["period"] for r in service.yield_timeseries(sample, ALL, "day") if r["currency"] == "RSD"]
    assert day == ["2023-06-15", "2023-07-03"]


def test_timeseries_rejects_bad_granularity(sample):
    with pytest.raises(ValueError):
        service.yield_timeseries(sample, ALL, "year")


def test_maturity_buckets(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", remaining_maturity_days=300, turnover=10.0),
        make_row(isin="RSMFRSD0000B", remaining_maturity_days=1000, turnover=20.0),
        make_row(isin="RSMFRSD0000C", remaining_maturity_days=1095, turnover=30.0),
        make_row(isin="RSMFRSD0000D", remaining_maturity_days=2600, turnover=40.0),
        make_row(isin="RSMFRSD0000E", remaining_maturity_days=4000, turnover=50.0),
    ])
    res = service.maturity_buckets(conn, ALL)
    assert [(r["bucket"], r["turnover"]) for r in res] == [
        ("0-1Y", 10.0), ("1-3Y", 50.0), ("5-10Y", 40.0), ("10Y+", 50.0)]


def test_daily_extremes_tiebreak_and_range(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", turnover=100.0, min_yield_pct=3.0, avg_yield_pct=4.5, max_yield_pct=6.0),
        make_row(isin="RSMFRSD0000B", turnover=300.0, min_yield_pct=3.0, avg_yield_pct=4.5, max_yield_pct=6.0),
        make_row(isin="RSMFRSD0000C", turnover=10.0, min_yield_pct=2.5, avg_yield_pct=3.0, max_yield_pct=4.0),
    ])
    (r,) = service.daily_extremes(conn, ALL)
    assert r["highest_pct"] == 6.0 and r["highest_isin"] == "RSMFRSD0000B"   # tie -> larger turnover
    assert r["lowest_pct"] == 2.5 and r["lowest_isin"] == "RSMFRSD0000C"
    assert r["range_pct"] == pytest.approx(3.5)


def test_daily_extremes_sort_and_limit(conn):
    load_rows(conn, [
        make_row(trade_date=date(2023, 6, d), settlement_date=date(2023, 6, d),
                 min_yield_pct=y - 0.5, avg_yield_pct=y, max_yield_pct=y + 0.5)
        for d, y in [(1, 4.0), (2, 6.0), (3, 5.0)]
    ])
    top = service.daily_extremes(conn, ALL, sort_by="highest_pct", order="desc", limit=2)
    assert [r["trade_date"] for r in top] == ["2023-06-02", "2023-06-03"]
    low = service.daily_extremes(conn, ALL, sort_by="lowest_pct", order="asc", limit=1)
    assert [r["trade_date"] for r in low] == ["2023-06-01"]
    with pytest.raises(ValueError):
        service.daily_extremes(conn, ALL, sort_by="isin")


def test_daily_extremes_respect_other_filters(conn):
    load_rows(conn, [
        make_row(isin="RSMFRSD0000A", remaining_maturity_days=500, max_yield_pct=9.0, avg_yield_pct=5.0, min_yield_pct=5.0),
        make_row(isin="RSMFRSD0000B", remaining_maturity_days=2000, max_yield_pct=6.0, avg_yield_pct=5.0, min_yield_pct=5.0),
    ])
    spec = FilterSpec(remaining_maturity_years=Range(min=3))
    (r,) = service.daily_extremes(conn, spec)
    assert r["highest_pct"] == 6.0


def test_quality_count_and_securities(conn):
    load_rows(conn, [make_row(), make_row(isin="RSMFRSD0000B", turnover=1.0, quantity=500)])
    assert service.quality_count(conn, ALL) == 1
    secs = service.list_securities(conn)
    assert {s["isin"] for s in secs} == {"RSMFRSD00001", "RSMFRSD0000B"}


def test_scatter_columns(sample):
    rows = service.scatter(sample, ALL)
    assert len(rows) == 4
    assert set(rows[0]) == {"trade_date", "isin", "currency", "remaining_maturity_days",
                            "avg_yield_pct", "turnover"}
```

`tests/test_real_data.py`:

```python
import pytest

from securities_analyzer.ingest.parser import parse_csv
from securities_analyzer.query import service
from securities_analyzer.query.filters import FilterSpec, Range
from tests.conftest import find_raw_dir

GOLDEN = FilterSpec(
    date_from="2023-02-02", date_to="2024-03-05",
    yield_pct=Range(min=3.5, min_exclusive=True),
    remaining_maturity_years=Range(min=3, min_exclusive=True),
)


def test_every_real_file_parses():
    raw = find_raw_dir()
    if raw is None:
        pytest.skip("real NBS CSV files not available")
    total = 0
    for f in sorted(raw.glob("GovermentSecuritySecondaryTrade_*.csv")):
        total += len(parse_csv(f.read_bytes()))
    assert total >= 5000


def test_closed_years_have_no_quality_flags(real_conn):
    n = real_conn.execute(
        "SELECT COUNT(*) FROM trades WHERE quality_flag != 'OK' AND trade_date <= '2025-12-31'"
    ).fetchone()[0]
    assert n == 0


def test_golden_kpis(real_conn):
    k = {r["currency"]: r for r in service.kpis(real_conn, GOLDEN)}
    assert k["RSD"]["row_count"] == 371
    assert k["RSD"]["turnover"] == pytest.approx(155830121796.84, rel=1e-9)
    assert k["RSD"]["weighted_yield_pct"] == pytest.approx(6.093064, abs=1e-6)
    assert k["RSD"]["quantity"] == 16233797 and k["RSD"]["isins"] == 3
    assert k["EUR"]["row_count"] == 17
    assert k["EUR"]["turnover"] == pytest.approx(15642804.29, rel=1e-9)
    assert k["EUR"]["weighted_yield_pct"] == pytest.approx(4.126739, abs=1e-6)
    assert k["EUR"]["quantity"] == 16859 and k["EUR"]["isins"] == 6
    assert service.fetch_rows(real_conn, GOLDEN, limit=1)["total"] == 388


def test_golden_daily_extremes(real_conn):
    spec = GOLDEN.model_copy(update={"currency": ["RSD"]})
    day = [r for r in service.daily_extremes(real_conn, spec, limit=5000)
           if r["trade_date"] == "2023-12-28"]
    assert len(day) == 1
    assert day[0]["highest_pct"] == 6.27 and day[0]["highest_isin"] == "RSMFRSD86176"
    assert day[0]["lowest_pct"] == 4.80 and day[0]["lowest_isin"] == "RSMFRSD55940"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_service.py tests/test_real_data.py -v`
Expected: FAIL — `cannot import name 'service'`.

- [ ] **Step 3: Implement**

`securities_analyzer/query/service.py`:

```python
import sqlite3

from .builder import build_where
from .filters import FilterSpec

ROW_COLUMNS = (
    "trade_date", "settlement_date", "isin", "currency", "coupon_pct", "maturity_date",
    "remaining_maturity_days", "quantity", "transaction_count", "wavg_price",
    "min_yield_pct", "max_yield_pct", "avg_yield_pct", "turnover", "quality_flag",
)
SORTABLE = frozenset(ROW_COLUMNS)

_PERIOD = {
    "day": "trade_date",
    "week": "date(trade_date, 'weekday 0', '-6 days')",   # Monday of the week
    "month": "strftime('%Y-%m-01', trade_date)",
}

_BUCKET_CASE = (
    "CASE WHEN remaining_maturity_days <= 365 THEN 1 WHEN remaining_maturity_days <= 1095 THEN 2 "
    "WHEN remaining_maturity_days <= 1825 THEN 3 WHEN remaining_maturity_days <= 3650 THEN 4 ELSE 5 END"
)
_BUCKET_NAMES = {1: "0-1Y", 2: "1-3Y", 3: "3-5Y", 4: "5-10Y", 5: "10Y+"}

_EXTREME_SORT = frozenset({"trade_date", "highest_pct", "lowest_pct", "range_pct"})


def _all(conn: sqlite3.Connection, sql: str, params: list) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def fetch_rows(conn, spec: FilterSpec, *, sort: str = "trade_date", order: str = "desc",
               limit: int = 100, offset: int = 0) -> dict:
    if sort not in SORTABLE:
        raise ValueError(f"nedozvoljena kolona za sortiranje: {sort!r}")
    where, params = build_where(spec)
    total = conn.execute(f"SELECT COUNT(*) FROM trades WHERE {where}", params).fetchone()[0]
    direction = "ASC" if order == "asc" else "DESC"
    rows = _all(
        conn,
        f"SELECT {', '.join(ROW_COLUMNS)} FROM trades WHERE {where} "
        f"ORDER BY {sort} {direction}, id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "rows": rows}


def kpis(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    return _all(conn, f"""
        SELECT currency,
               SUM(turnover) AS turnover,
               SUM(quantity) AS quantity,
               SUM(transaction_count) AS transactions,
               COUNT(DISTINCT isin) AS isins,
               COUNT(DISTINCT trade_date) AS active_days,
               COUNT(*) AS row_count,
               SUM(avg_yield_pct * turnover) / SUM(turnover) AS weighted_yield_pct
        FROM trades WHERE {where} GROUP BY currency ORDER BY currency""", params)


def yield_timeseries(conn, spec: FilterSpec, granularity: str) -> list[dict]:
    if granularity not in _PERIOD:
        raise ValueError(f"nepoznata granulacija: {granularity!r}")
    where, params = build_where(spec)
    period = _PERIOD[granularity]
    return _all(conn, f"""
        SELECT {period} AS period, currency,
               SUM(avg_yield_pct * turnover) / SUM(turnover) AS weighted_yield_pct,
               SUM(turnover) AS turnover
        FROM trades WHERE {where} GROUP BY period, currency ORDER BY period, currency""", params)


def scatter(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    return _all(conn, f"""
        SELECT trade_date, isin, currency, remaining_maturity_days, avg_yield_pct, turnover
        FROM trades WHERE {where} ORDER BY trade_date, id LIMIT 20000""", params)


def maturity_buckets(conn, spec: FilterSpec) -> list[dict]:
    where, params = build_where(spec)
    rows = _all(conn, f"""
        SELECT {_BUCKET_CASE} AS bucket_order, currency,
               SUM(turnover) AS turnover, COUNT(*) AS row_count
        FROM trades WHERE {where} GROUP BY bucket_order, currency
        ORDER BY bucket_order, currency""", params)
    for r in rows:
        r["bucket"] = _BUCKET_NAMES[r.pop("bucket_order")]
    return rows


def daily_extremes(conn, spec: FilterSpec, *, sort_by: str = "trade_date",
                   order: str = "desc", limit: int = 500) -> list[dict]:
    if sort_by not in _EXTREME_SORT:
        raise ValueError(f"nedozvoljeno sortiranje: {sort_by!r}")
    where, params = build_where(spec)
    direction = "ASC" if order == "asc" else "DESC"
    return _all(conn, f"""
        WITH f AS (
          SELECT trade_date, currency, isin, min_yield_pct, max_yield_pct, turnover
          FROM trades WHERE {where}),
        hi AS (
          SELECT trade_date, currency, isin, max_yield_pct,
                 ROW_NUMBER() OVER (PARTITION BY trade_date, currency
                                    ORDER BY max_yield_pct DESC, turnover DESC, isin ASC) AS rn
          FROM f),
        lo AS (
          SELECT trade_date, currency, isin, min_yield_pct,
                 ROW_NUMBER() OVER (PARTITION BY trade_date, currency
                                    ORDER BY min_yield_pct ASC, turnover DESC, isin ASC) AS rn
          FROM f)
        SELECT hi.trade_date AS trade_date, hi.currency AS currency,
               hi.max_yield_pct AS highest_pct, hi.isin AS highest_isin,
               lo.min_yield_pct AS lowest_pct, lo.isin AS lowest_isin,
               ROUND(hi.max_yield_pct - lo.min_yield_pct, 4) AS range_pct
        FROM hi JOIN lo
          ON hi.trade_date = lo.trade_date AND hi.currency = lo.currency AND lo.rn = 1
        WHERE hi.rn = 1
        ORDER BY {sort_by} {direction}, trade_date, currency
        LIMIT ?""", [*params, limit])


def quality_count(conn, spec: FilterSpec) -> int:
    where, params = build_where(spec)
    return conn.execute(
        f"SELECT COUNT(*) FROM trades WHERE ({where}) AND quality_flag != 'OK'", params
    ).fetchone()[0]


def list_securities(conn) -> list[dict]:
    return _all(conn, "SELECT isin, currency, coupon_pct, maturity_date, original_maturity_days, "
                      "first_trade, last_trade FROM securities ORDER BY currency, maturity_date, isin", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_service.py tests/test_real_data.py -v`
Expected: unit tests PASS. `test_real_data.py` PASSES when the project's `outputs\PowerBI_Data\RawData` folder exists (it does on this machine); it is SKIPPED elsewhere. If a golden number differs, STOP and cross-check with the independent Python computation in "Verified facts" before touching the SQL — do not edit the expected values to match.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: query service with KPIs, series, buckets, daily extremes; golden test" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: NBS updater

**Files:**
- Create: `securities_analyzer/updater/__init__.py` (empty), `securities_analyzer/updater/nbs.py`
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: `parse_csv`, `IngestError`, `replace_year`, `KeyCollisionError`, `stored_count`, `last_source_year`, `set_meta`, `data_range`, `__version__`.
- Produces:
  - `nbs.NBS_URL` (str), `nbs.FIRST_YEAR = 2020`
  - `nbs.DownloadError(Exception)`
  - `nbs.download_year(year: int, *, base_url: str = NBS_URL, retries: int = 3, backoff: float = 1.0, timeout: float = 30.0) -> bytes`
  - `nbs.years_to_refresh(last_source_year: int | None, today: date) -> list[int]`
  - `nbs.YearReport(year, status: "ok"|"error", added=0, removed=0, unchanged=0, message="")`
  - `nbs.UpdateReport(years: list[YearReport], data_end: str | None)` with `.ok -> bool` and `.to_dict() -> dict`
  - `nbs.refresh(conn, *, today: date | None = None, fetch=download_year, progress: Callable[[str], None] | None = None) -> UpdateReport`
  - Meta keys written: `last_update_utc` (ISO UTC), `last_update_result` (JSON of `to_dict()`).

- [ ] **Step 1: Write the failing tests**

`tests/test_updater.py`:

```python
import json
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
    with pytest.raises(DownloadError):
        download_year(2023, base_url="http://127.0.0.1:9/Download", retries=2, backoff=0, timeout=2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.updater`.

- [ ] **Step 3: Implement**

`securities_analyzer/updater/nbs.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v`
Expected: all PASS (including the three fake-HTTP-server tests).

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: NBS updater with year selection, validation and atomic refresh" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: HTTP API

**Files:**
- Create: `securities_analyzer/api/__init__.py` (empty), `securities_analyzer/api/jobs.py`, `securities_analyzer/api/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `api.app.create_app(db_path: Path, *, fetch=download_year, export_dir: Path | None = None) -> FastAPI`
  - Routes (all JSON; bodies are pydantic models with an optional `filter` = `FilterSpec`):
    - `GET /api/meta` → `{version, rows, first_trade_date, last_trade_date, last_update_utc, last_update_result}`
    - `GET /api/securities` → list from `list_securities`
    - `POST /api/query/rows` `{filter, sort, order, page, page_size}` → `{total, rows, page, page_size}`
    - `POST /api/query/summary` `{filter}` → `{kpis, quality_flagged}`
    - `POST /api/query/timeseries` `{filter, granularity}` → list
    - `POST /api/query/scatter` `{filter}` → list
    - `POST /api/query/buckets` `{filter}` → list
    - `POST /api/query/extremes` `{filter, sort_by, order, limit}` → list
    - `POST /api/export` `{filter, format: "csv"|"xlsx"}` → `{path, rows}` (file written into `export_dir`, default `~/Downloads`)
    - `GET /api/saved-queries` → `[{name, filter}]`; `PUT /api/saved-queries` `{name, filter}`; `DELETE /api/saved-queries/{name}`
    - `POST /api/update` → `{started: bool}`; `GET /api/update/status` → `{state: "idle"|"running"|"done"|"error", messages, report, error}`
  - Invalid filter → HTTP 422 (pydantic); bad sort column → HTTP 422.
  - Static UI served at `/` from `securities_analyzer/ui` if the directory exists.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:

```python
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from securities_analyzer.api.app import create_app
from securities_analyzer.db.schema import connect
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
    from pathlib import Path
    p = Path(j["path"])
    assert p.exists() and p.suffix == f".{fmt}" and p.parent == tmp_path / "exports"
    if fmt == "csv":
        text = p.read_text(encoding="utf-8-sig")
        assert text.splitlines()[0].startswith("trade_date,") and len(text.splitlines()) == 3


def test_saved_queries_crud(client):
    f = {"currency": ["EUR"], "yield_pct": {"min": 3.5, "min_exclusive": True}}
    assert client.put("/api/saved-queries", json={"name": "Moj upit", "filter": f}).status_code == 200
    items = client.get("/api/saved-queries").json()
    assert items[0]["name"] == "Moj upit" and items[0]["filter"]["currency"] == ["EUR"]
    assert client.delete("/api/saved-queries/Moj upit").status_code == 200
    assert client.get("/api/saved-queries").json() == []
    assert client.put("/api/saved-queries", json={"name": "x", "filter": {"bad": 1}}).status_code == 422


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.api`.

- [ ] **Step 3: Implement**

`securities_analyzer/api/jobs.py`:

```python
import threading
from collections.abc import Callable


class UpdateJob:
    """Runs one background update at a time and exposes its progress for polling."""

    def __init__(self, run: Callable[[Callable[[str], None]], object]):
        self._run = run                      # run(progress) -> UpdateReport
        self._lock = threading.Lock()
        self._state: dict = {"state": "idle", "messages": [], "report": None, "error": None}

    def start(self) -> bool:
        with self._lock:
            if self._state["state"] == "running":
                return False
            self._state = {"state": "running", "messages": [], "report": None, "error": None}
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def _progress(self, msg: str) -> None:
        with self._lock:
            self._state["messages"].append(msg)

    def _work(self) -> None:
        try:
            report = self._run(self._progress)
            with self._lock:
                self._state.update(state="done", report=report.to_dict())
        except Exception as e:                       # surface any failure to the UI
            with self._lock:
                self._state.update(state="error", error=str(e))

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "messages": list(self._state["messages"])}
```

`securities_analyzer/api/app.py`:

```python
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

    @app.delete("/api/saved-queries/{name}")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: all PASS. Then run the full suite: `python -m pytest -q` — everything PASS (real-data tests PASS or SKIP).

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: FastAPI layer with queries, export, saved queries, update job" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: App runner and CLI

**Files:**
- Create: `securities_analyzer/app.py`, `securities_analyzer/__main__.py`, `run_app.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `create_app`, `ensure_user_db`, `build_seed`, `download_year`, `user_data_dir`, `seed_path`.
- Produces:
  - `__main__.main(argv: list[str] | None = None) -> int` with subcommands: `run` (default when no args), `fetch-all OUT_DIR [--from-year 2020]`, `build-seed CSV_DIR OUT_DB`.
  - `app.run() -> None` (starts server on a free `127.0.0.1` port, opens window).
  - `app.find_free_port() -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.__main__`.

- [ ] **Step 3: Implement**

`securities_analyzer/app.py`:

```python
import logging
import socket
import sqlite3
import sys
import threading
import time
import webbrowser

import uvicorn

from .api.app import create_app
from .db.seed import ensure_user_db
from .paths import seed_path, user_data_dir

log = logging.getLogger("securities_analyzer")


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run() -> None:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data_dir / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    db_path = data_dir / "data.db"
    try:
        ensure_user_db(db_path, seed_path())
    except sqlite3.DatabaseError as e:
        # Never delete or replace a user's DB automatically.
        msg = f"Baza podataka je oštećena ili zaključana: {db_path}\n{e}"
        log.error(msg)
        print(msg, file=sys.stderr)
        raise SystemExit(2) from e

    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(db_path), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise SystemExit("Server nije pokrenut")

    url = f"http://127.0.0.1:{port}/"
    log.info("Serving %s", url)
    try:
        import webview
        webview.create_window("Analiza državnih hartija", url, width=1440, height=900)
        webview.start()
    except Exception as e:                      # no pywebview / no WebView2 runtime
        log.warning("Window unavailable (%s); falling back to browser", e)
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
```

`securities_analyzer/__main__.py`:

```python
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
        n = build_seed(args.csv_dir, args.out_db)
        print(f"Imported {n} rows into {args.out_db}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

`run_app.py`:

```python
import sys

from securities_analyzer.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-test the real CLI against the local data**

```powershell
python -X utf8 -m securities_analyzer build-seed ..\outputs\PowerBI_Data\RawData data\seed.db
```
Expected: `Imported 5309 rows into data\seed.db` (the number may be higher only if the folder has changed).

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: app runner (free port, pywebview with browser fallback) and CLI" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Web UI

**Files:**
- Create: `securities_analyzer/ui/index.html`, `securities_analyzer/ui/styles.css`, `securities_analyzer/ui/app.js`, `securities_analyzer/ui/vendor/plotly.min.js` (downloaded)
- Test: manual checklist (Step 6) + one automated smoke test `tests/test_ui_static.py`

**Interfaces:**
- Consumes: every `/api/*` route from Task 6 (exact request/response shapes listed there).
- Produces: a single-page app served at `/`.

- [ ] **Step 1: Vendor Plotly (pinned version)**

```powershell
mkdir securities_analyzer\ui\vendor
curl.exe -L -o securities_analyzer\ui\vendor\plotly.min.js https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js
(Get-Item securities_analyzer\ui\vendor\plotly.min.js).Length
```
Expected: size ≈ 3–4 MB (anything under 1 MB means the download failed — retry).

- [ ] **Step 2: Write the static smoke test (failing)**

`tests/test_ui_static.py`:

```python
from fastapi.testclient import TestClient

from securities_analyzer.api.app import create_app


def test_ui_is_served_with_required_assets(db_path):
    c = TestClient(create_app(db_path))
    html = c.get("/").text
    assert "Podaci: Narodna banka Srbije" in html
    for asset in ("styles.css", "app.js", "vendor/plotly.min.js"):
        assert asset in html
        assert c.get("/" + asset).status_code == 200
```

Run: `python -m pytest tests/test_ui_static.py -v` → Expected: FAIL (404 / missing text).

- [ ] **Step 3: Write `securities_analyzer/ui/index.html`**

```html
<!doctype html>
<html lang="sr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Analiza državnih hartija</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<header>
  <h1>Sekundarno trgovanje državnim hartijama</h1>
  <div id="meta" class="muted"></div>
  <button id="btn-update" class="primary">Update base</button>
</header>
<div id="update-panel" hidden><pre id="update-log"></pre></div>
<div id="error" role="alert" hidden></div>

<div class="layout">
<aside id="filters">
  <div class="row-actions">
    <button id="btn-reset">Resetuj</button>
  </div>

  <fieldset>
    <legend>Period trgovanja</legend>
    <label>od <input type="date" id="date_from"></label>
    <label>do <input type="date" id="date_to"></label>
  </fieldset>

  <fieldset class="range" data-range="yield_pct">
    <legend>Prinos (%)</legend>
    <label>od <input type="number" step="any" data-part="min"></label>
    <label class="chk"><input type="checkbox" data-part="min_exclusive"> strogo veće</label>
    <label>do <input type="number" step="any" data-part="max"></label>
    <label class="chk"><input type="checkbox" data-part="max_exclusive"> strogo manje</label>
    <label>osnova
      <select id="yield_basis">
        <option value="avg">prosečni prinos</option>
        <option value="min">minimalni prinos</option>
        <option value="max">maksimalni prinos</option>
      </select>
    </label>
  </fieldset>

  <fieldset class="range" data-range="remaining_maturity_years">
    <legend>Preostala ročnost (godine)</legend>
    <label>od <input type="number" step="any" data-part="min"></label>
    <label class="chk"><input type="checkbox" data-part="min_exclusive"> strogo veće</label>
    <label>do <input type="number" step="any" data-part="max"></label>
    <label class="chk"><input type="checkbox" data-part="max_exclusive"> strogo manje</label>
  </fieldset>

  <fieldset class="range" data-range="original_maturity_years">
    <legend>Originalna ročnost (godine)</legend>
    <label>od <input type="number" step="any" data-part="min"></label>
    <label class="chk"><input type="checkbox" data-part="min_exclusive"> strogo veće</label>
    <label>do <input type="number" step="any" data-part="max"></label>
    <label class="chk"><input type="checkbox" data-part="max_exclusive"> strogo manje</label>
  </fieldset>

  <fieldset class="range" data-range="coupon_pct">
    <legend>Kupon (%)</legend>
    <label>od <input type="number" step="any" data-part="min"></label>
    <label>do <input type="number" step="any" data-part="max"></label>
  </fieldset>

  <fieldset>
    <legend>Valuta</legend>
    <label class="chk"><input type="checkbox" name="currency" value="RSD"> RSD</label>
    <label class="chk"><input type="checkbox" name="currency" value="EUR"> EUR</label>
  </fieldset>

  <fieldset>
    <legend>Ostalo</legend>
    <label>min. promet <input type="number" step="any" id="turnover_min"></label>
    <label>ISIN
      <select id="isin" multiple size="6"></select>
    </label>
  </fieldset>

  <fieldset>
    <legend>Sačuvani upiti</legend>
    <select id="saved"></select>
    <div class="row-actions">
      <button id="btn-load">Učitaj</button>
      <button id="btn-save">Sačuvaj…</button>
      <button id="btn-delete">Obriši</button>
    </div>
  </fieldset>
</aside>

<main>
  <section id="kpis" aria-live="polite"></section>

  <nav id="tabs">
    <button data-tab="time" class="active">Prinos kroz vreme</button>
    <button data-tab="scatter">Prinos i ročnost</button>
    <button data-tab="buckets">Promet po rokovima</button>
    <button data-tab="extremes">Dnevni ekstremi</button>
  </nav>

  <section id="chart-toolbar">
    <label id="gran-wrap">Granulacija
      <select id="gran">
        <option value="day">dan</option>
        <option value="week">nedelja</option>
        <option value="month" selected>mesec</option>
      </select>
    </label>
    <label id="exsort-wrap" hidden>Sortiraj
      <select id="exsort">
        <option value="trade_date|desc">po datumu (najnoviji)</option>
        <option value="highest_pct|desc">najveći prinos</option>
        <option value="lowest_pct|asc">najmanji prinos</option>
        <option value="range_pct|desc">najveći raspon</option>
      </select>
    </label>
  </section>
  <div id="chart"></div>
  <div id="extremes-table" hidden></div>

  <section id="table-section">
    <div class="table-bar">
      <strong id="table-title">Redovi</strong>
      <span class="spacer"></span>
      <button id="btn-csv">Izvezi CSV</button>
      <button id="btn-xlsx">Izvezi XLSX</button>
    </div>
    <div class="table-wrap"><table id="rows"></table></div>
    <div class="pager">
      <button id="prev">‹</button>
      <span id="page-info"></span>
      <button id="next">›</button>
    </div>
  </section>
</main>
</div>

<footer class="muted">Podaci: Narodna banka Srbije · <span id="foot-range"></span></footer>
<script src="vendor/plotly.min.js"></script>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `securities_analyzer/ui/styles.css`**

```css
:root {
  --bg: #f6f7f9; --panel: #fff; --ink: #1c2330; --muted: #667085; --line: #d9dde3;
  --accent: #1f6feb; --warn: #b42318;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #11151c; --panel: #1a2029; --ink: #e6e9ef; --muted: #98a2b3; --line: #2b3441; --accent: #5b9bff; --warn: #f97066; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.4 "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--ink); }
header { display: flex; align-items: center; gap: 16px; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
header h1 { font-size: 16px; margin: 0; }
header #meta { flex: 1; }
.muted { color: var(--muted); font-size: 12px; }
button, select, input { font: inherit; color: inherit; }
button { padding: 5px 10px; border: 1px solid var(--line); background: var(--panel); border-radius: 6px; cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
button:disabled { opacity: .5; cursor: default; }
input, select { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; max-width: 100%; }
#update-panel { padding: 8px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
#update-log { margin: 0; max-height: 140px; overflow: auto; font-size: 12px; white-space: pre-wrap; }
#error { margin: 8px 16px; padding: 8px 12px; border: 1px solid var(--warn); color: var(--warn); border-radius: 6px; }
.layout { display: grid; grid-template-columns: 280px 1fr; gap: 12px; padding: 12px 16px; align-items: start; }
aside { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; position: sticky; top: 8px; max-height: calc(100vh - 80px); overflow: auto; }
fieldset { border: 1px solid var(--line); border-radius: 6px; margin: 0 0 10px; padding: 6px 8px 8px; }
legend { font-weight: 600; padding: 0 4px; }
fieldset label { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 4px 0; }
fieldset label.chk { justify-content: flex-start; color: var(--muted); font-size: 12px; }
fieldset input[type=number], fieldset input[type=date], fieldset select { width: 150px; }
.row-actions { display: flex; gap: 6px; margin: 6px 0; flex-wrap: wrap; }
main { min-width: 0; }
#kpis { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.kpi-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; min-width: 260px; flex: 1; }
.kpi-card h3 { margin: 0 0 6px; font-size: 13px; }
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px 12px; }
.kpi-grid div span { display: block; color: var(--muted); font-size: 11px; }
.kpi-grid div b { font-size: 15px; }
.kpi-empty { padding: 12px; color: var(--muted); }
#tabs { display: flex; gap: 6px; margin-bottom: 6px; }
#tabs button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
#chart-toolbar { display: flex; gap: 12px; margin-bottom: 4px; min-height: 28px; }
#chart { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; height: 380px; }
#extremes-table { margin-top: 8px; max-height: 260px; overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
#table-section { margin-top: 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.table-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.spacer { flex: 1; }
.table-wrap { overflow: auto; max-height: 420px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { padding: 4px 8px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--panel); cursor: pointer; user-select: none; }
td.l, th.l { text-align: left; }
tr.flag td { color: var(--warn); }
.pager { display: flex; justify-content: center; align-items: center; gap: 10px; margin-top: 6px; }
footer { padding: 10px 16px; text-align: center; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } aside { position: static; max-height: none; } }
```

- [ ] **Step 5: Write `securities_analyzer/ui/app.js`**

```javascript
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 0) => n == null ? "–" : Number(n).toLocaleString("sr-RS", {minimumFractionDigits: d, maximumFractionDigits: d});
const COLORS = {RSD: "#1f6feb", EUR: "#d9480f"};
const colorFor = (c) => COLORS[c] || "#6b7280";
const state = {tab: "time", sort: "trade_date", order: "desc", page: 1, pageSize: 100, total: 0, exSort: "trade_date", exOrder: "desc"};

async function api(path, {method, body} = {}) {
  const opts = body === undefined && !method ? {} :
    {method: method || "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)};
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : j.detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    } catch (_) { /* keep status text */ }
    throw new Error(msg);
  }
  return res.json();
}

function showError(msg) { const e = $("error"); e.textContent = msg || ""; e.hidden = !msg; }

/* ---------- filter <-> form ---------- */
function readFilter() {
  const f = {};
  for (const id of ["date_from", "date_to"]) { const v = $(id).value; if (v) f[id] = v; }
  f.yield_basis = $("yield_basis").value;
  for (const fs of document.querySelectorAll("fieldset.range")) {
    const r = {};
    for (const inp of fs.querySelectorAll("[data-part]")) {
      const part = inp.dataset.part;
      if (inp.type === "checkbox") r[part] = inp.checked;
      else if (inp.value !== "") r[part] = Number(inp.value);
    }
    f[fs.dataset.range] = r;
  }
  const t = $("turnover_min").value;
  if (t !== "") f.turnover_min = Number(t);
  f.currency = [...document.querySelectorAll("input[name=currency]:checked")].map((i) => i.value);
  f.isin = [...$("isin").selectedOptions].map((o) => o.value);
  return f;
}

function writeFilter(f) {
  resetForm();
  for (const id of ["date_from", "date_to"]) if (f[id]) $(id).value = f[id];
  if (f.yield_basis) $("yield_basis").value = f.yield_basis;
  for (const fs of document.querySelectorAll("fieldset.range")) {
    const r = f[fs.dataset.range] || {};
    for (const inp of fs.querySelectorAll("[data-part]")) {
      const v = r[inp.dataset.part];
      if (inp.type === "checkbox") inp.checked = !!v; else if (v != null) inp.value = v;
    }
  }
  if (f.turnover_min != null) $("turnover_min").value = f.turnover_min;
  for (const c of document.querySelectorAll("input[name=currency]")) c.checked = (f.currency || []).includes(c.value);
  for (const o of $("isin").options) o.selected = (f.isin || []).includes(o.value);
}

function resetForm() {
  document.querySelectorAll("#filters input[type=number], #filters input[type=date]").forEach((i) => (i.value = ""));
  document.querySelectorAll("#filters input[type=checkbox]").forEach((i) => (i.checked = false));
  $("yield_basis").value = "avg";
  for (const o of $("isin").options) o.selected = false;
}

/* ---------- rendering ---------- */
function renderKpis(summary) {
  const el = $("kpis");
  if (!summary.kpis.length) { el.innerHTML = '<div class="kpi-empty">Nema rezultata za izabrane filtere.</div>'; return; }
  el.innerHTML = summary.kpis.map((k) => `
    <div class="kpi-card">
      <h3>${esc(k.currency)}</h3>
      <div class="kpi-grid">
        <div><span>Promet (${esc(k.currency)})</span><b>${fmt(k.turnover)}</b></div>
        <div><span>Ponderisani prinos</span><b>${fmt(k.weighted_yield_pct, 2)}%</b></div>
        <div><span>Količina</span><b>${fmt(k.quantity)}</b></div>
        <div><span>Transakcija</span><b>${fmt(k.transactions)}</b></div>
        <div><span>Hartija</span><b>${fmt(k.isins)}</b></div>
        <div><span>Dana</span><b>${fmt(k.active_days)}</b></div>
      </div>
    </div>`).join("") +
    (summary.quality_flagged ? `<div class="kpi-card"><h3>Kvalitet podataka</h3><b style="color:var(--warn)">${fmt(summary.quality_flagged)} označenih redova</b></div>` : "");
}

const ROW_COLS = [
  ["trade_date", "Datum", "l"], ["isin", "ISIN", "l"], ["currency", "Val.", "l"],
  ["coupon_pct", "Kupon %", 2], ["maturity_date", "Dospeće", "l"],
  ["remaining_maturity_days", "Preost. dana", 0], ["quantity", "Količina", 0],
  ["transaction_count", "Trans.", 0], ["wavg_price", "Pros. cena", 2],
  ["min_yield_pct", "Min %", 2], ["avg_yield_pct", "Prosek %", 2], ["max_yield_pct", "Max %", 2],
  ["turnover", "Promet", 2], ["quality_flag", "Kvalitet", "l"],
];

function renderRows(res) {
  state.total = res.total;
  const head = "<thead><tr>" + ROW_COLS.map(([k, label, kind]) =>
    `<th data-sort="${k}" class="${kind === "l" ? "l" : ""}">${label}${state.sort === k ? (state.order === "asc" ? " ▲" : " ▼") : ""}</th>`).join("") + "</tr></thead>";
  const body = "<tbody>" + res.rows.map((r) =>
    `<tr class="${r.quality_flag !== "OK" ? "flag" : ""}">` + ROW_COLS.map(([k, , kind]) =>
      `<td class="${kind === "l" ? "l" : ""}">${typeof kind === "number" ? fmt(r[k], kind) : esc(r[k])}</td>`).join("") + "</tr>").join("") + "</tbody>";
  $("rows").innerHTML = head + body;
  const pages = Math.max(1, Math.ceil(res.total / state.pageSize));
  $("page-info").textContent = `${fmt(res.total)} redova · strana ${state.page} / ${pages}`;
  $("prev").disabled = state.page <= 1;
  $("next").disabled = state.page >= pages;
  $("table-title").textContent = `Redovi (${fmt(res.total)})`;
}

// purge first: tabs use different axis layouts (e.g. the per-currency subplots) that must not leak between tabs
const plot = (traces, layout) => {
  Plotly.purge("chart");
  return Plotly.newPlot("chart", traces, Object.assign({
    margin: {l: 60, r: 20, t: 20, b: 50}, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {color: getComputedStyle(document.body).color}, legend: {orientation: "h", y: -0.2},
  }, layout), {responsive: true, displaylogo: false});
};

const groupBy = (rows, key) => rows.reduce((m, r) => ((m[r[key]] = m[r[key]] || []).push(r), m), {});
const emptyChart = (msg) => plot([], {annotations: [{text: msg, showarrow: false, font: {size: 14}}], xaxis: {visible: false}, yaxis: {visible: false}});

function drawTime(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const traces = Object.entries(groupBy(rows, "currency")).map(([cur, rs]) => ({
    type: "scatter", mode: "lines+markers", name: cur, x: rs.map((r) => r.period),
    y: rs.map((r) => r.weighted_yield_pct), line: {color: colorFor(cur)},
    hovertemplate: "%{x}<br>%{y:.2f}%<extra>" + cur + "</extra>",
  }));
  plot(traces, {yaxis: {title: "Ponderisani prosečni prinos (%)"}});
}

function drawScatter(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const maxT = Math.max(...rows.map((r) => r.turnover));
  const traces = Object.entries(groupBy(rows, "currency")).map(([cur, rs]) => ({
    type: "scattergl", mode: "markers", name: cur, x: rs.map((r) => r.remaining_maturity_days / 365),
    y: rs.map((r) => r.avg_yield_pct), text: rs.map((r) => `${r.isin} · ${r.trade_date}`),
    marker: {color: colorFor(cur), opacity: 0.6, size: rs.map((r) => Math.max(5, Math.sqrt(r.turnover / maxT) * 26))},
    hovertemplate: "%{text}<br>ročnost %{x:.2f} god · prinos %{y:.2f}%<extra>" + cur + "</extra>",
  }));
  plot(traces, {xaxis: {title: "Preostala ročnost (godine)"}, yaxis: {title: "Prosečni prinos (%)"}});
}

function drawBuckets(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const curs = [...new Set(rows.map((r) => r.currency))];
  const traces = curs.map((cur, i) => {
    const rs = rows.filter((r) => r.currency === cur);
    return {type: "bar", name: cur, x: rs.map((r) => r.bucket), y: rs.map((r) => r.turnover),
            marker: {color: colorFor(cur)}, xaxis: "x" + (i + 1), yaxis: "y" + (i + 1)};
  });
  const layout = {grid: {rows: 1, columns: curs.length, pattern: "independent"}, annotations: []};
  curs.forEach((cur, i) => {
    layout["yaxis" + (i + 1)] = {title: `Promet (${cur})`};
    layout["xaxis" + (i + 1)] = {categoryorder: "array", categoryarray: ["0-1Y", "1-3Y", "3-5Y", "5-10Y", "10Y+"]};
  });
  plot(traces, layout);
}

function drawExtremes(rows) {
  const tbl = $("extremes-table");
  if (!rows.length) { emptyChart("Nema podataka"); tbl.innerHTML = ""; return; }
  const chronological = [...rows].sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  const traces = [];
  for (const [cur, rs] of Object.entries(groupBy(chronological, "currency"))) {
    traces.push({type: "scatter", mode: "lines", name: `${cur} najmanji`, x: rs.map((r) => r.trade_date),
                 y: rs.map((r) => r.lowest_pct), line: {color: colorFor(cur), width: 1}});
    traces.push({type: "scatter", mode: "lines", name: `${cur} najveći`, x: rs.map((r) => r.trade_date),
                 y: rs.map((r) => r.highest_pct), line: {color: colorFor(cur), width: 1},
                 fill: "tonexty", fillcolor: colorFor(cur) + "33"});
  }
  plot(traces, {yaxis: {title: "Prinos (%)"}});
  tbl.innerHTML = "<table><thead><tr><th class='l'>Datum</th><th class='l'>Val.</th><th>Najveći %</th><th class='l'>ISIN</th><th>Najmanji %</th><th class='l'>ISIN</th><th>Raspon</th></tr></thead><tbody>" +
    rows.map((r) => `<tr><td class="l">${esc(r.trade_date)}</td><td class="l">${esc(r.currency)}</td><td>${fmt(r.highest_pct, 2)}</td><td class="l">${esc(r.highest_isin)}</td><td>${fmt(r.lowest_pct, 2)}</td><td class="l">${esc(r.lowest_isin)}</td><td>${fmt(r.range_pct, 2)}</td></tr>`).join("") +
    "</tbody></table>";
}

/* ---------- data loading ---------- */
async function loadTab() {
  const filter = readFilter();
  $("gran-wrap").hidden = state.tab !== "time";
  $("exsort-wrap").hidden = state.tab !== "extremes";
  $("extremes-table").hidden = state.tab !== "extremes";
  if (state.tab === "time") drawTime(await api("/api/query/timeseries", {body: {filter, granularity: $("gran").value}}));
  else if (state.tab === "scatter") drawScatter(await api("/api/query/scatter", {body: {filter}}));
  else if (state.tab === "buckets") drawBuckets(await api("/api/query/buckets", {body: {filter}}));
  else drawExtremes(await api("/api/query/extremes", {body: {filter, sort_by: state.exSort, order: state.exOrder, limit: 500}}));
}

async function loadRows() {
  const res = await api("/api/query/rows", {body: {filter: readFilter(), sort: state.sort, order: state.order, page: state.page, page_size: state.pageSize}});
  renderRows(res);
}

async function refreshAll(resetPage = true) {
  if (resetPage) state.page = 1;
  showError("");
  try {
    const filter = readFilter();
    const [summary] = await Promise.all([api("/api/query/summary", {body: {filter}}), loadRows(), loadTab()]);
    renderKpis(summary);
  } catch (e) { showError(e.message); }
}

let timer = null;
const debounced = () => { clearTimeout(timer); timer = setTimeout(() => refreshAll(true), 300); };

async function loadMeta() {
  const m = await api("/api/meta");
  const upd = m.last_update_utc ? new Date(m.last_update_utc).toLocaleString("sr-RS") : "nikad";
  $("meta").textContent = `Podaci: ${m.first_trade_date || "–"} → ${m.last_trade_date || "–"} · ${fmt(m.rows)} redova · poslednje ažuriranje: ${upd} · v${m.version}`;
  $("foot-range").textContent = `verzija ${m.version}`;
  if (!m.rows) showError("Baza je prazna. Klikni „Update base“ da preuzmeš podatke sa NBS-a.");
}

async function loadIsins() {
  const sel = await api("/api/securities");
  $("isin").innerHTML = sel.map((s) => `<option value="${esc(s.isin)}">${esc(s.isin)} · ${esc(s.currency)} · ${fmt(s.coupon_pct, 2)}% · ${esc(s.maturity_date)}</option>`).join("");
}

async function loadSaved() {
  const items = await api("/api/saved-queries");
  window.__saved = Object.fromEntries(items.map((i) => [i.name, i.filter]));
  $("saved").innerHTML = items.map((i) => `<option>${esc(i.name)}</option>`).join("");
}

/* ---------- update base ---------- */
async function runUpdate() {
  $("btn-update").disabled = true;
  $("update-panel").hidden = false;
  $("update-log").textContent = "Pokrećem ažuriranje…";
  try {
    await api("/api/update", {body: {}});
    for (;;) {
      await new Promise((r) => setTimeout(r, 800));
      const st = await api("/api/update/status");
      $("update-log").textContent = st.messages.join("\n");
      if (st.state === "running") continue;
      if (st.state === "error") $("update-log").textContent += `\nGREŠKA: ${st.error}`;
      else if (st.report && !st.report.ok) $("update-log").textContent += "\nNeke godine nisu ažurirane; postojeći podaci su sačuvani.";
      else $("update-log").textContent += "\nGotovo.";
      break;
    }
  } catch (e) { $("update-log").textContent = `GREŠKA: ${e.message}`; }
  $("btn-update").disabled = false;
  await Promise.all([loadMeta(), loadIsins()]);
  await refreshAll();
}

/* ---------- export ---------- */
async function doExport(format) {
  try {
    const r = await api("/api/export", {body: {filter: readFilter(), format}});
    showError("");
    $("table-title").textContent = `Sačuvano (${fmt(r.rows)} redova): ${r.path}`;
  } catch (e) { showError(e.message); }
}

/* ---------- wiring ---------- */
document.querySelectorAll("#filters input, #filters select").forEach((el) => {
  if (el.id !== "saved") el.addEventListener("input", debounced);
});
$("btn-reset").onclick = () => { resetForm(); refreshAll(); };
$("btn-update").onclick = runUpdate;
$("btn-csv").onclick = () => doExport("csv");
$("btn-xlsx").onclick = () => doExport("xlsx");
$("prev").onclick = () => { state.page--; loadRows().catch((e) => showError(e.message)); };
$("next").onclick = () => { state.page++; loadRows().catch((e) => showError(e.message)); };
$("rows").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-sort]");
  if (!th) return;
  state.order = state.sort === th.dataset.sort && state.order === "desc" ? "asc" : "desc";
  state.sort = th.dataset.sort;
  state.page = 1;
  loadRows().catch((e) => showError(e.message));
});
$("tabs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-tab]");
  if (!b) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  state.tab = b.dataset.tab;
  loadTab().catch((e) => showError(e.message));
});
$("gran").onchange = () => loadTab().catch((e) => showError(e.message));
$("exsort").onchange = () => {
  [state.exSort, state.exOrder] = $("exsort").value.split("|");
  loadTab().catch((e) => showError(e.message));
};
$("btn-save").onclick = async () => {
  const name = window.prompt("Naziv upita:");
  if (!name) return;
  try { await api("/api/saved-queries", {method: "PUT", body: {name, filter: readFilter()}}); await loadSaved(); $("saved").value = name; }
  catch (e) { showError(e.message); }
};
$("btn-load").onclick = () => { const f = (window.__saved || {})[$("saved").value]; if (f) { writeFilter(f); refreshAll(); } };
$("btn-delete").onclick = async () => {
  const name = $("saved").value;
  if (!name || !window.confirm(`Obrisati upit „${name}“?`)) return;
  try { await api("/api/saved-queries/" + encodeURIComponent(name), {method: "DELETE"}); await loadSaved(); }
  catch (e) { showError(e.message); }
};

(async function init() {
  try { await Promise.all([loadMeta(), loadIsins(), loadSaved()]); } catch (e) { showError(e.message); }
  await refreshAll();
})();
```

- [ ] **Step 6: Run automated smoke test, then manual verification**

Run: `python -m pytest tests/test_ui_static.py -v` → Expected: PASS. Then full suite `python -m pytest -q` → all PASS/SKIP.

Manual checklist (run `python -X utf8 -m securities_analyzer`; the window should open with the seed data. Use the project's `data\seed.db` built in Task 7 Step 5):

- [ ] Header shows data range `2020-01-03 → 2026-08-20` (or later) and ≈5,309 rows.
- [ ] Enter the spec example: date from 02.02.2023, to 05.03.2024; yield "od" 3.5 + "strogo veće"; remaining maturity "od" 3 + "strogo veće". there are two KPI cards, **RSD** with weighted yield **6.09%** and **EUR** with **4.13%**; the table title says **Redovi (388)**.
- [ ] Tab "Dnevni ekstremi": row for 2023-12-28 / RSD shows **6.27 (RSMFRSD86176)** and **4.80 (RSMFRSD55940)**; sorting "najveći prinos" puts the highest-yield day on top.
- [ ] All four tabs render and react to filter changes; EUR and RSD are never mixed in one KPI card or one bucket subplot.
- [ ] Export CSV and XLSX: the status text shows a path in `Downloads`; the file opens and has the filtered rows.
- [ ] Save a query, reload the app (new port), the query is still in the list; load and delete work.
- [ ] Disconnect the network, press **Update base**: a readable error appears per year and the data/row count is unchanged.
- [ ] Reconnect and press **Update base**: log shows `2025`/`2026` lines with `+added / -removed / nepromenjeno`; header "poslednje ažuriranje" changes.
- [ ] Known limitation to record in README: the Plotly camera (PNG) button may not save a file inside the pywebview window; it works when the app falls back to the browser.

- [ ] **Step 7: Commit**

```powershell
git add -A
git commit -m "feat: interactive web UI with filters, charts, daily extremes, update and export" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Packaging, CI/release, README, spec sync

**Files:**
- Create: `README.md`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `scripts/build_exe.ps1`
- Modify: `docs/superpowers/specs/2026-10-12-securities-analyzer-design.md` (in the *parent* project folder; see Step 5)

**Interfaces:**
- Consumes: CLI subcommands `fetch-all`, `build-seed`; `run_app.py`.
- Produces: `dist\SecuritiesAnalyzer\SecuritiesAnalyzer.exe` locally via `scripts\build_exe.ps1`; on tag `v*` a GitHub Release with `SecuritiesAnalyzer-windows.zip`.

- [ ] **Step 1: Local build script**

`scripts/build_exe.ps1`:

```powershell
$ErrorActionPreference = "Stop"
if (-not (Test-Path data\seed.db)) {
    Write-Host "data\seed.db missing - building it from data\raw (run fetch-all first)"
    python -X utf8 -m securities_analyzer build-seed data\raw data\seed.db
}
pyinstaller --noconfirm --clean --name SecuritiesAnalyzer --windowed `
    --add-data "securities_analyzer\ui;securities_analyzer\ui" `
    --add-data "data\seed.db;data" `
    --collect-submodules uvicorn --collect-all webview `
    run_app.py
Write-Host "Built dist\SecuritiesAnalyzer\SecuritiesAnalyzer.exe"
```

- [ ] **Step 2: Build and smoke-test locally**

```powershell
python -X utf8 -m securities_analyzer build-seed ..\outputs\PowerBI_Data\RawData data\seed.db
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
.\dist\SecuritiesAnalyzer\SecuritiesAnalyzer.exe
```
Expected: the window opens with the full history without any Python installed in the PATH being needed (verify on a second user profile or VM if available); `%APPDATA%\SecuritiesAnalyzer\data.db` and `app.log` exist; closing the window ends the process (check Task Manager). If the exe starts but shows a blank window, read `app.log` and check that `ui` was bundled (`dist\SecuritiesAnalyzer\_internal\securities_analyzer\ui\index.html`).

- [ ] **Step 3: CI workflows**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -e ".[dev]"
      - run: python -m pytest -q
```

`.github/workflows/release.yml`:

```yaml
name: release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -e ".[dev,desktop]"
      - name: Download NBS data (also used for the golden tests)
        run: python -X utf8 -m securities_analyzer fetch-all data/raw
      - name: Tests
        run: python -m pytest -q
        env:
          SA_RAW_DIR: data/raw
      - name: Build seed database
        run: python -X utf8 -m securities_analyzer build-seed data/raw data/seed.db
      - name: Build exe
        run: powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1
      - name: Zip
        run: Compress-Archive -Path dist\SecuritiesAnalyzer -DestinationPath SecuritiesAnalyzer-windows.zip
        shell: pwsh
      - uses: softprops/action-gh-release@v2
        with:
          files: SecuritiesAnalyzer-windows.zip
          generate_release_notes: true
```

- [ ] **Step 4: README**

`README.md` (write exactly these sections; keep it short):

```markdown
# Securities Analyzer

Standalone Windows program for exploring NBS secondary-market trading of Serbian
government securities (2020 → today): multi-dimensional filters, interactive charts,
daily highest/lowest yields, CSV/XLSX export and an **Update base** button that pulls
fresh data from NBS onto your own machine. No server, no account.

## Install (users)
1. Download `SecuritiesAnalyzer-windows.zip` from the latest GitHub Release and unzip it.
2. Run `SecuritiesAnalyzer.exe`.
3. Windows SmartScreen may warn about an unsigned app: "More info" → "Run anyway".
4. Press **Update base** from time to time. Your data lives in `%APPDATA%\SecuritiesAnalyzer\`.

## Run from source
    python -m venv .venv && .venv\Scripts\activate
    pip install -e ".[dev,desktop]"
    python -m securities_analyzer fetch-all data/raw
    python -m securities_analyzer build-seed data/raw data/seed.db
    python -m securities_analyzer
Without `data/seed.db` the app starts empty; press **Update base** to download everything.

## Develop
    python -m pytest -q     # real-data tests run when SA_RAW_DIR points at the yearly CSVs

## Notes
- Source: Narodna banka Srbije (webappcenter.nbs.rs). Check NBS terms of use before redistributing data.
- Each row is a *daily aggregate* per ISIN, not a single trade. Totals and weighted yields are always shown per currency.
- Plotly's PNG button may not save inside the app window; it works when the app falls back to the browser.
```

- [ ] **Step 5: Sync the spec with the plan's deviations**

Edit `..\docs\superpowers\specs\2026-10-12-securities-analyzer-design.md`:
- §5 table: replace the `*_min`/`*_max` rows with "`Range {min, max, min_exclusive, max_exclusive}` for yield, remaining/original maturity, coupon, settlement lag" and change the sentence "'More than' is strict `>`…" to "each bound has an `*_exclusive` flag (default inclusive)".
- §3 layout: replace `scripts/build_seed.py` with "CLI `python -m securities_analyzer build-seed|fetch-all`".
- §11: add "The release workflow downloads the data from NBS in CI; no NBS data is committed to the repo."
- §2/§5: currency codes are any 3 uppercase letters.

- [ ] **Step 6: Final verification and commit**

Run: `python -m pytest -q` → all PASS (real-data tests PASS locally). 

```powershell
git add -A
git commit -m "build: PyInstaller script, CI + release workflows, README" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7 (needs explicit user approval — do NOT run without it): publish**

Publishing to GitHub is public and outward-facing. Ask the user first, then: create a public repo, `git remote add origin …`, `git push -u origin main`, `git tag v0.1.0`, `git push origin v0.1.0`, and check that the `release` workflow attaches `SecuritiesAnalyzer-windows.zip`.

---

## Self-review (spec coverage)

| Spec section | Task |
|---|---|
| §2 source data, column map, header validation | 1 (parser, `EXPECTED_HEADER`), 7 (`fetch-all`) |
| §3 architecture / module boundaries, 127.0.0.1, free port, pywebview fallback | 1–7 (module layout), 7 |
| §4 DB (`trades`, `securities` view, `meta`, `saved_queries`, quality flags, seed copy-on-first-run, never overwrite) | 1 (quality), 2 |
| §5 FilterSpec, strictness, 365-day years, validation, parameterization | 3 |
| §6 rows, KPIs per currency, weighted yield, time series, scatter, buckets, **daily extremes**, quality count, export | 4, 6, 8 |
| §7 UI (Serbian, filters, KPI strip, tabs, table, saved queries, footer attribution) | 8 |
| §8 Update algorithm (year range, validation, 50% guard, per-year transaction, meta, summary) | 5, 6 (job/endpoints), 8 (button) |
| §9 error handling (offline, format change, corrupt DB, 422) | 5, 6, 7 (`SystemExit(2)` message on corrupt DB) |
| §10 tests (ingest, db atomicity, per-filter, golden, fake server, API contract) | 1–6 |
| §11 packaging, CI release, SmartScreen note, NBS-terms fallback | 9 |
| §12 Android | out of scope (API-driven static UI keeps it open) |

Placeholder scan: none — every code step contains the code. Type consistency: `YearResult`/`YearReport`/`UpdateReport.to_dict()` names, `service.*` signatures, `FilterSpec` field names (`yield_pct`, `remaining_maturity_years`, …) and API body field names are identical in Tasks 3–8.
