# Query Builder ("Analiza") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Analiza" mode to Securities Analyzer where the user picks up to 2 grouping dimensions, 1–4 measures, a chart type, sorting and "top N per currency" on top of the existing filters, sees chart + table, exports it, and saves the whole view.

**Architecture:** A fixed server-side catalog of dimensions and measures (SQL expressions from whitelists) feeds one generic grouping query (`run_pivot`) that always groups by currency as well and applies top-N per currency with a window function. A thin API layer exposes catalog / query / export and extends saved queries with an optional `pivot` config. The frontend adds a mode switch, a builder bar and a result view; all chart/axis construction lives in a small pure JS module unit-tested with Node's test runner.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, SQLite (window functions), vanilla JS + vendored Plotly 2.35.2, pytest, `node --test` (Node 22 locally; `windows-latest` has Node).

**Spec:** `docs/superpowers/specs/2026-10-12-query-builder-design.md` (binding). It extends `docs/superpowers/specs/2026-10-12-securities-analyzer-design.md`.

## Global Constraints

- Repo root is `securities-analyzer/` (branch `feature/query-builder`, created from `build/v0.1`). All paths are relative to it. Python **3.13**, Windows only.
- **Never mix currencies.** `currency` is always an implicit extra grouping; every result row carries its `currency`; `limit` ("top N") applies **per currency**.
- All SQL is parameterized. Dimension and measure ids are whitelisted enums; every SQL expression that reaches SQL text comes from the catalog (`pivot_catalog.py`), never from request strings.
- Maximum **2 dimensions** and **4 measures**, `limit` 1–5000 (default 100). Invalid combinations are rejected with HTTP 422 by pydantic validation.
- `weighted_yield = SUM(avg_yield_pct * turnover) / SUM(turnover)`; division by zero yields `null` (shown "–"); min/max yields are true extremes (`MIN(min_yield_pct)`, `MAX(max_yield_pct)`), never averaged.
- Maturity buckets: `0-1Y` ≤365, `1-3Y` ≤1095, `3-5Y` ≤1825, `5-10Y` ≤3650, `10Y+`; the bucket dimension sorts by bucket number 1…5, never alphabetically. Years × 365.
- UI text is Serbian Latin; code/identifiers/comments are English. Plotly stays vendored (no CDN). Every API/DB string put into `innerHTML` is HTML-escaped.
- Server stays loopback-only; no new network access. Tests never call live NBS.
- Chart type is **not** part of the query: the server returns the same rows for every chart; chart choice lives in the client and in the saved `pivot.chart`.
- Run Python via `.venv\Scripts\python.exe -m pytest ...` (do not activate the venv). Test output must be pristine (no warnings). Never `git push`, never add remotes, never touch `securities_analyzer/ui/vendor/plotly.min.js`.
- Commits: small, one per task step marked "Commit"; the trailer is the `Co-Authored-By` line **your own harness specifies for this run**, as a second `-m`.

## Deviations from the spec (the final task syncs the spec)

1. Dimension `kind` has three values: `time`, `ordinal` (bucket, years, coupon, lag — naturally ordered) and `category` (ISIN). The UI's default sort is **group ascending for `time` and `ordinal`**, and **first measure descending only for `category`** (the spec text said "time → group asc, otherwise measure desc", which would sort maturity buckets by size instead of by length).
2. `PivotQuery.order` defaults to `"asc"` (the spec did not state a default; the UI always sends an explicit value).
3. Export CSV/XLSX is written by shared helpers in `securities_analyzer/api/exporting.py`; the existing overview export is refactored onto them with unchanged behaviour. Export files get a numeric suffix instead of overwriting when two exports happen in the same second.

## Verified facts the plan relies on (computed 2026-10-12 from the 5,309-row seed)

- **Example A** — filter trade date 2024-01-01…2024-12-31; dimensions `[isin]`; measures `[turnover, quantity, transactions, weighted_yield]`; sort by `turnover` desc; limit 5:
  - RSD: `RSMFRSD58761` 121471327158.97 / 10904256 / 541 / 5.5628; `RSMFRSD86176` 105048689266.66 / 11105945 / 685 / 5.4735; `RSMFRSD55940` 43845029342.10 / 4107635 / 289 / 4.5509; `RSMFRSD89592` 28305748426.46 / 2799899 / 185 / 4.6835; `RSMFRSD90335` 8727699321.06 / 873622 / 10 / 4.1348.
  - EUR: `RSMFRSD51436` 43154118.53 / 43261 / 48 / 3.6302; `RSMFRSD66798` 38485549.00 / 41120 / 19 / 2.4128; `RSMFRSD70022` 20734643.90 / 19860 / 8 / 3.8982; `RSMFRSD84510` 19348117.50 / 19000 / 7 / 3.5481; `RSMFRSD68802` 18076263.44 / 17992 / 14 / 3.9726.
- **Example B** — filter currency RSD, trade date up to 2022-12-31; dimensions `[date_year, remaining_bucket]`; measure `[weighted_yield]`; sort by group asc; first rows in natural order: `2020/0-1Y` 1.5359, `2020/1-3Y` 2.0573, `2020/3-5Y` 2.3980, `2020/5-10Y` 2.9846, `2020/10Y+` 3.8285, `2021/0-1Y` 1.0443.
- **Group counts** — `[date_day, isin]` over the whole seed: RSD 3887 groups, EUR 1141 groups (5028 total). With limit 5000 nothing is truncated; with limit 1000 both currencies are truncated to 1000 rows.
- Python 3.13 bundles SQLite ≥ 3.45, so `ROW_NUMBER() OVER (...)` is available.

## File structure

```
securities_analyzer/
  query/
    expressions.py        # NEW: shared SQL fragments (periods, bucket CASE)
    pivot_catalog.py      # NEW: dimensions + measures catalog, limits, catalog_payload()
    pivot.py              # NEW: PivotQuery/PivotConfig/ChartConfig models + run_pivot()
    service.py            # MODIFY: import shared fragments from expressions.py
  db/schema.py            # MODIFY: schema v2 (saved_queries.pivot_json) + migration
  api/
    app.py                # MODIFY: catalog/pivot/export routes, saved queries with pivot, use exporting.py
    exporting.py          # NEW: unique_export_path(), write_table()
  ui/
    pivot_chart.js        # NEW: pure chart/table/sort logic (browser global + CommonJS)
    analysis.js           # NEW: DOM wiring for the Analiza view
    index.html styles.css app.js   # MODIFY
tests/
  test_pivot_catalog.py test_pivot.py test_exporting.py     # NEW
  test_db.py test_api.py test_real_data.py test_ui_static.py # MODIFY
tests_js/pivot_chart.test.js                                # NEW (node:test)
.github/workflows/{ci,release}.yml  README.md  docs/…       # MODIFY (last task)
```

---

### Task 1: Shared SQL fragments, catalog and request models

**Files:**
- Create: `securities_analyzer/query/expressions.py`, `securities_analyzer/query/pivot_catalog.py`, `securities_analyzer/query/pivot.py`
- Modify: `securities_analyzer/query/service.py` (import the shared fragments instead of defining them)
- Test: `tests/test_pivot_catalog.py`

**Interfaces:**
- Produces:
  - `expressions.PERIOD_SQL: dict[str, str]` (`day`, `week`, `month`), `expressions.BUCKET_ORDER_SQL: str`, `expressions.BUCKET_NAMES: dict[int, str]`.
  - `pivot_catalog.Dimension(id, label, kind, value_sql, sort_sql)` and `Measure(id, label, unit, sql)` frozen dataclasses; `DIMENSIONS: dict[str, Dimension]`, `MEASURES: dict[str, Measure]` (insertion-ordered as in the spec); constants `MAX_DIMENSIONS=2`, `MAX_MEASURES=4`, `MAX_LIMIT=5000`, `DEFAULT_LIMIT=100`; `catalog_payload() -> dict` = `{dimensions: [{id,label,kind}], measures: [{id,label,unit}], limits: {max_dimensions, max_measures, max_limit, default_limit}}`.
  - `pivot.ChartConfig(type: Literal["bar","line","scatter","heatmap","table"]="bar", horizontal: bool=False)`; `pivot.PivotQuery(dimensions: list[str]=[], measures: list[str]=["turnover"], sort_by: str="group", order: Literal["asc","desc"]="asc", limit: int=100)` (validated); `pivot.PivotConfig(PivotQuery)` adds `chart: ChartConfig`. All with `extra="forbid"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pivot_catalog.py`:

```python
import pytest
from pydantic import ValidationError

from securities_analyzer.query.pivot import ChartConfig, PivotConfig, PivotQuery
from securities_analyzer.query.pivot_catalog import (
    DIMENSIONS, MAX_DIMENSIONS, MAX_LIMIT, MAX_MEASURES, MEASURES, catalog_payload,
)


def test_catalog_ids_and_order_match_spec():
    assert list(DIMENSIONS) == [
        "isin", "date_day", "date_week", "date_month", "date_quarter", "date_year",
        "remaining_bucket", "remaining_years", "original_years", "coupon", "settlement_lag",
    ]
    assert list(MEASURES) == [
        "turnover", "quantity", "transactions", "active_days", "isin_count",
        "weighted_yield", "yield_min", "yield_max", "price_pct_nominal", "avg_trade_size",
    ]


def test_dimension_kinds():
    assert DIMENSIONS["isin"].kind == "category"
    assert all(DIMENSIONS[d].kind == "time" for d in
               ("date_day", "date_week", "date_month", "date_quarter", "date_year"))
    assert all(DIMENSIONS[d].kind == "ordinal" for d in
               ("remaining_bucket", "remaining_years", "original_years", "coupon", "settlement_lag"))


def test_catalog_payload_shape():
    p = catalog_payload()
    assert [d["id"] for d in p["dimensions"]] == list(DIMENSIONS)
    assert {"id", "label", "kind"} == set(p["dimensions"][0])
    assert {"id", "label", "unit"} == set(p["measures"][0])
    assert p["limits"] == {"max_dimensions": 2, "max_measures": 4, "max_limit": 5000, "default_limit": 100}
    assert {m["unit"] for m in p["measures"]} == {
        "currency", "pieces", "count", "percent_points", "percent_nominal"}
    labels = {m["id"]: m["label"] for m in p["measures"]}
    assert labels["turnover"] == "Promet" and labels["weighted_yield"] == "Ponderisani prinos"
    assert {d["id"]: d["label"] for d in p["dimensions"]}["isin"] == "Hartija (ISIN)"


def test_every_catalog_expression_is_valid_sql(conn):
    for d in DIMENSIONS.values():
        conn.execute(f"SELECT {d.value_sql}, {d.sort_sql} FROM trades LIMIT 1").fetchall()
    for m in MEASURES.values():
        conn.execute(f"SELECT {m.sql} FROM trades").fetchall()


def test_query_defaults():
    q = PivotQuery()
    assert (q.dimensions, q.measures, q.sort_by, q.order, q.limit) == ([], ["turnover"], "group", "asc", 100)


def test_config_adds_chart_defaults():
    c = PivotConfig()
    assert c.chart == ChartConfig(type="bar", horizontal=False)


@pytest.mark.parametrize("kwargs", [
    dict(dimensions=["nope"]),
    dict(dimensions=["isin", "isin"]),
    dict(dimensions=["isin", "date_day", "coupon"]),
    dict(measures=[]),
    dict(measures=["nope"]),
    dict(measures=["turnover", "turnover"]),
    dict(measures=["turnover", "quantity", "transactions", "active_days", "isin_count"]),
    dict(sort_by="quantity"),                               # not among the selected measures
    dict(sort_by="nope"),
    dict(limit=0),
    dict(limit=5001),
    dict(order="sideways"),
    dict(unknown_field=1),
])
def test_query_validation_rejects(kwargs):
    with pytest.raises(ValidationError):
        PivotQuery(**kwargs)


def test_sort_by_selected_measure_and_group_are_accepted():
    assert PivotQuery(measures=["turnover", "quantity"], sort_by="quantity").sort_by == "quantity"
    assert PivotQuery(sort_by="group").sort_by == "group"
    assert MAX_DIMENSIONS == 2 and MAX_MEASURES == 4 and MAX_LIMIT == 5000


def test_config_rejects_bad_chart():
    with pytest.raises(ValidationError):
        PivotConfig(chart={"type": "pie"})
    with pytest.raises(ValidationError):
        PivotConfig(chart={"type": "bar", "colour": "red"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pivot_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.query.pivot`.

- [ ] **Step 3: Implement**

`securities_analyzer/query/expressions.py`:

```python
"""SQL fragments over the `trades` table shared by the overview queries and the pivot builder."""

PERIOD_SQL = {
    "day": "trade_date",
    "week": "date(trade_date, 'weekday 0', '-6 days')",   # Monday of the week
    "month": "strftime('%Y-%m-01', trade_date)",
}

BUCKET_ORDER_SQL = (
    "CASE WHEN remaining_maturity_days <= 365 THEN 1 WHEN remaining_maturity_days <= 1095 THEN 2 "
    "WHEN remaining_maturity_days <= 1825 THEN 3 WHEN remaining_maturity_days <= 3650 THEN 4 ELSE 5 END"
)
BUCKET_NAMES = {1: "0-1Y", 2: "1-3Y", 3: "3-5Y", 4: "5-10Y", 5: "10Y+"}
```

`securities_analyzer/query/service.py`: delete the local definitions of `_PERIOD`, `_BUCKET_CASE` and `_BUCKET_NAMES` and replace them with this import, keeping the three names used elsewhere in the file:

```python
from .expressions import BUCKET_NAMES as _BUCKET_NAMES
from .expressions import BUCKET_ORDER_SQL as _BUCKET_CASE
from .expressions import PERIOD_SQL as _PERIOD
```

`securities_analyzer/query/pivot_catalog.py`:

```python
from dataclasses import dataclass

from .expressions import BUCKET_NAMES, BUCKET_ORDER_SQL, PERIOD_SQL

MAX_DIMENSIONS = 2
MAX_MEASURES = 4
MAX_LIMIT = 5000
DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    kind: str        # "category" | "time" | "ordinal"
    value_sql: str   # what is shown for the group
    sort_sql: str    # natural order of the group


@dataclass(frozen=True)
class Measure:
    id: str
    label: str
    unit: str        # "currency" | "pieces" | "count" | "percent_points" | "percent_nominal"
    sql: str


_BUCKET_LABEL_SQL = (
    "CASE " + BUCKET_ORDER_SQL + " "
    + " ".join(f"WHEN {k} THEN '{v}'" for k, v in BUCKET_NAMES.items()) + " END"
)
_QUARTER_SQL = ("strftime('%Y', trade_date) || '-Q' || "
                "((CAST(strftime('%m', trade_date) AS INTEGER) + 2) / 3)")
_YEAR_SQL = "strftime('%Y', trade_date)"

_DIMENSIONS = [
    Dimension("isin", "Hartija (ISIN)", "category", "isin", "isin"),
    Dimension("date_day", "Dan", "time", PERIOD_SQL["day"], PERIOD_SQL["day"]),
    Dimension("date_week", "Nedelja", "time", PERIOD_SQL["week"], PERIOD_SQL["week"]),
    Dimension("date_month", "Mesec", "time", PERIOD_SQL["month"], PERIOD_SQL["month"]),
    Dimension("date_quarter", "Kvartal", "time", _QUARTER_SQL, _QUARTER_SQL),
    Dimension("date_year", "Godina", "time", _YEAR_SQL, _YEAR_SQL),
    Dimension("remaining_bucket", "Preostali rok (grupa)", "ordinal", _BUCKET_LABEL_SQL, BUCKET_ORDER_SQL),
    Dimension("remaining_years", "Preostala ročnost (cele godine)", "ordinal",
              "CAST(remaining_maturity_days / 365 AS INTEGER)", "CAST(remaining_maturity_days / 365 AS INTEGER)"),
    Dimension("original_years", "Originalna ročnost (godine)", "ordinal",
              "ROUND(original_maturity_days / 365.0, 1)", "ROUND(original_maturity_days / 365.0, 1)"),
    Dimension("coupon", "Kupon (%)", "ordinal", "coupon_pct", "coupon_pct"),
    Dimension("settlement_lag", "Dani do valutiranja", "ordinal", "settlement_lag_days", "settlement_lag_days"),
]

_MEASURES = [
    Measure("turnover", "Promet", "currency", "SUM(turnover)"),
    Measure("quantity", "Količina", "pieces", "SUM(quantity)"),
    Measure("transactions", "Broj transakcija", "count", "SUM(transaction_count)"),
    Measure("active_days", "Dana trgovanja", "count", "COUNT(DISTINCT trade_date)"),
    Measure("isin_count", "Broj hartija", "count", "COUNT(DISTINCT isin)"),
    Measure("weighted_yield", "Ponderisani prinos", "percent_points",
            "SUM(avg_yield_pct * turnover) / SUM(turnover)"),
    Measure("yield_min", "Najmanji prinos", "percent_points", "MIN(min_yield_pct)"),
    Measure("yield_max", "Najveći prinos", "percent_points", "MAX(max_yield_pct)"),
    Measure("price_pct_nominal", "Cena (% nominale)", "percent_nominal",
            "100.0 * SUM(turnover) / SUM(quantity * nominal_per_unit)"),
    Measure("avg_trade_size", "Promet po transakciji", "currency",
            "SUM(turnover) / SUM(transaction_count)"),
]

DIMENSIONS: dict[str, Dimension] = {d.id: d for d in _DIMENSIONS}
MEASURES: dict[str, Measure] = {m.id: m for m in _MEASURES}


def catalog_payload() -> dict:
    return {
        "dimensions": [{"id": d.id, "label": d.label, "kind": d.kind} for d in DIMENSIONS.values()],
        "measures": [{"id": m.id, "label": m.label, "unit": m.unit} for m in MEASURES.values()],
        "limits": {"max_dimensions": MAX_DIMENSIONS, "max_measures": MAX_MEASURES,
                   "max_limit": MAX_LIMIT, "default_limit": DEFAULT_LIMIT},
    }
```

`securities_analyzer/query/pivot.py` (models only in this task; `run_pivot` is added in Task 2):

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .pivot_catalog import DEFAULT_LIMIT, DIMENSIONS, MAX_DIMENSIONS, MAX_LIMIT, MAX_MEASURES, MEASURES


class ChartConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["bar", "line", "scatter", "heatmap", "table"] = "bar"
    horizontal: bool = False


class PivotQuery(BaseModel):
    """What to group by, what to measure, how to order and cut the result."""
    model_config = ConfigDict(extra="forbid")
    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=lambda: ["turnover"])
    sort_by: str = "group"
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)

    @field_validator("dimensions")
    @classmethod
    def _dimensions(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_DIMENSIONS:
            raise ValueError(f"najviše {MAX_DIMENSIONS} grupisanja")
        if len(set(v)) != len(v):
            raise ValueError("duplirano grupisanje")
        for d in v:
            if d not in DIMENSIONS:
                raise ValueError(f"nepoznato grupisanje {d!r}")
        return v

    @field_validator("measures")
    @classmethod
    def _measures(cls, v: list[str]) -> list[str]:
        if not 1 <= len(v) <= MAX_MEASURES:
            raise ValueError(f"izaberi od 1 do {MAX_MEASURES} mera")
        if len(set(v)) != len(v):
            raise ValueError("duplirana mera")
        for m in v:
            if m not in MEASURES:
                raise ValueError(f"nepoznata mera {m!r}")
        return v

    @model_validator(mode="after")
    def _sort_by_known(self):
        if self.sort_by != "group" and self.sort_by not in self.measures:
            raise ValueError("sortiranje mora biti 'group' ili jedna od izabranih mera")
        return self


class PivotConfig(PivotQuery):
    """A saved builder view: the query plus how it is drawn."""
    chart: ChartConfig = Field(default_factory=ChartConfig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pivot_catalog.py -v` then the full suite `.venv\Scripts\python.exe -m pytest -q`.
Expected: all PASS (the full suite proves the `service.py` refactor changed no behaviour: 132 existing + the new tests).

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat(pivot): shared SQL fragments, dimension/measure catalog and request models" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 2: Pivot engine (`run_pivot`) with golden tests

**Files:**
- Modify: `securities_analyzer/query/pivot.py` (append `run_pivot`)
- Create: `tests/test_pivot.py`
- Modify: `tests/test_real_data.py` (append golden tests)

**Interfaces:**
- Consumes: `FilterSpec`, `build_where` (`securities_analyzer.query.builder`), `DIMENSIONS`, `MEASURES`, `PivotQuery`; fixtures `conn`, `real_conn`; helpers `make_row`, `load_rows`.
- Produces: `run_pivot(conn: sqlite3.Connection, spec: FilterSpec, query: PivotQuery) -> dict` returning
  `{"dimensions": [{"id","label"}], "measures": [{"id","label","unit"}], "rows": [{"currency": str, "dims": list, "values": list}], "truncated_currencies": list[str]}`. Rows are ordered by currency, then by the requested sort. `truncated_currencies` is sorted.

- [ ] **Step 1: Write the failing tests**

`tests/test_pivot.py`:

```python
from datetime import date

import pytest

from securities_analyzer.query.filters import FilterSpec, Range
from securities_analyzer.query.pivot import PivotQuery, run_pivot
from tests.factories import load_rows, make_row

ALL = FilterSpec()
A, B, E, F = "RSMFRSD0000A", "RSMFRSD0000B", "RSMFRSD0000E", "RSMFRSD0000F"


def q(**kw) -> PivotQuery:
    return PivotQuery(**kw)


def by_currency(res):
    out: dict[str, list] = {}
    for r in res["rows"]:
        out.setdefault(r["currency"], []).append(r)
    return out


@pytest.fixture
def sample(conn):
    load_rows(conn, [
        make_row(isin=A, turnover=100.0, avg_yield_pct=4.0, transaction_count=2),
        make_row(isin=A, turnover=300.0, avg_yield_pct=6.0, transaction_count=1,
                 trade_date=date(2023, 7, 3), settlement_date=date(2023, 7, 3)),
        make_row(isin=B, turnover=500.0, avg_yield_pct=5.0, transaction_count=5,
                 remaining_maturity_days=300),
        make_row(isin=E, currency="EUR", turnover=50.0, avg_yield_pct=3.0, transaction_count=1),
        make_row(isin=F, currency="EUR", turnover=70.0, avg_yield_pct=2.0, transaction_count=2),
    ])
    return conn


def test_zero_dimensions_gives_one_row_per_currency(sample):
    res = run_pivot(sample, ALL, q(measures=["turnover", "transactions"]))
    assert [(r["currency"], r["dims"], r["values"]) for r in res["rows"]] == [
        ("EUR", [], [120.0, 3]), ("RSD", [], [900.0, 8])]
    assert res["dimensions"] == []
    assert res["measures"] == [
        {"id": "turnover", "label": "Promet", "unit": "currency"},
        {"id": "transactions", "label": "Broj transakcija", "unit": "count"}]
    assert res["truncated_currencies"] == []


def test_group_by_isin_sorted_by_measure_desc(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc"))
    got = {c: [(r["dims"][0], r["values"][0]) for r in rs] for c, rs in by_currency(res).items()}
    assert got == {"RSD": [(B, 500.0), (A, 400.0)], "EUR": [(F, 70.0), (E, 50.0)]}
    assert res["dimensions"] == [{"id": "isin", "label": "Hartija (ISIN)"}]


def test_weighted_yield_quantity_active_days_isin_count(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"],
                                    measures=["weighted_yield", "quantity", "active_days", "isin_count"],
                                    sort_by="group", order="asc"))
    rsd = {r["dims"][0]: r["values"] for r in by_currency(res)["RSD"]}
    assert rsd[A][0] == pytest.approx(5.5)          # (4*100 + 6*300) / 400
    assert rsd[A][1:] == [2, 2, 1]                  # 2 rows with quantity 1, 2 days, 1 security
    assert rsd[B][0] == pytest.approx(5.0)


def test_yield_extremes_price_and_trade_size(conn):
    load_rows(conn, [
        make_row(isin=A, quantity=10, wavg_price=9000.0, min_price=8900.0, max_price=9100.0,
                 turnover=90000.0, min_yield_pct=3.0, avg_yield_pct=3.5, max_yield_pct=4.0,
                 transaction_count=2, nominal_per_unit=10000.0),
        make_row(isin=A, trade_date=date(2023, 6, 16), settlement_date=date(2023, 6, 16),
                 quantity=30, wavg_price=9500.0, min_price=9400.0, max_price=9600.0,
                 turnover=285000.0, min_yield_pct=2.5, avg_yield_pct=3.0, max_yield_pct=3.8,
                 transaction_count=3, nominal_per_unit=10000.0),
    ])
    (r,) = run_pivot(conn, ALL, q(measures=["yield_min", "yield_max", "price_pct_nominal",
                                            "avg_trade_size"]))["rows"]
    assert r["values"][0] == 2.5 and r["values"][1] == 4.0           # true extremes, not averages
    assert r["values"][2] == pytest.approx(93.75)                    # 100 * 375000 / (40 * 10000)
    assert r["values"][3] == pytest.approx(75000.0)                  # 375000 / 5 transactions


def test_division_by_zero_gives_null_and_sorts_last(conn):
    load_rows(conn, [make_row(isin=A, turnover=100.0, avg_yield_pct=4.0),
                     make_row(isin=B, turnover=0.0, avg_yield_pct=9.0)])
    for order in ("asc", "desc"):
        res = run_pivot(conn, ALL, q(dimensions=["isin"], measures=["weighted_yield"],
                                      sort_by="weighted_yield", order=order))
        assert [(r["dims"][0], r["values"][0]) for r in res["rows"]] == [(A, 4.0), (B, None)]


def test_time_dimensions_values_and_order(conn):
    days = [date(2023, 2, 10), date(2023, 4, 1), date(2023, 6, 15), date(2024, 1, 2)]
    load_rows(conn, [make_row(isin=A, turnover=10.0, trade_date=d, settlement_date=d) for d in days])

    def vals(dim):
        res = run_pivot(conn, ALL, q(dimensions=[dim], measures=["turnover"], sort_by="group", order="asc"))
        return [r["dims"][0] for r in res["rows"]]

    assert vals("date_day") == ["2023-02-10", "2023-04-01", "2023-06-15", "2024-01-02"]
    assert vals("date_week") == ["2023-02-06", "2023-03-27", "2023-06-12", "2024-01-01"]   # Mondays
    assert vals("date_month") == ["2023-02-01", "2023-04-01", "2023-06-01", "2024-01-01"]
    assert vals("date_quarter") == ["2023-Q1", "2023-Q2", "2024-Q1"]
    assert vals("date_year") == ["2023", "2024"]


def test_bucket_dimension_uses_natural_order_not_alphabetical(conn):
    days = [300, 1000, 1500, 2600, 4000]
    load_rows(conn, [make_row(isin=f"RSMFRSD0000{i}", remaining_maturity_days=d, turnover=10.0)
                     for i, d in enumerate(days, 1)])
    base = dict(dimensions=["remaining_bucket"], measures=["turnover"], sort_by="group")
    asc = [r["dims"][0] for r in run_pivot(conn, ALL, q(**base, order="asc"))["rows"]]
    desc = [r["dims"][0] for r in run_pivot(conn, ALL, q(**base, order="desc"))["rows"]]
    assert asc == ["0-1Y", "1-3Y", "3-5Y", "5-10Y", "10Y+"]
    assert desc == list(reversed(asc))


def test_numeric_dimensions(conn):
    load_rows(conn, [
        make_row(isin=A, original_maturity_days=2556, remaining_maturity_days=1094,
                 coupon_pct=5.0, turnover=10.0),
        make_row(isin=B, original_maturity_days=4565, remaining_maturity_days=1095,
                 coupon_pct=4.5, turnover=10.0, settlement_date=date(2023, 6, 19)),
    ])

    def vals(dim):
        res = run_pivot(conn, ALL, q(dimensions=[dim], measures=["turnover"], sort_by="group", order="asc"))
        return [r["dims"][0] for r in res["rows"]]

    assert vals("original_years") == [7.0, 12.5]
    assert vals("remaining_years") == [2, 3]
    assert vals("coupon") == [4.5, 5.0]
    assert vals("settlement_lag") == [0, 4]


def test_two_dimensions_group_order(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin", "date_month"], measures=["turnover"],
                                    sort_by="group", order="asc"))
    rsd = [(r["dims"], r["values"][0]) for r in by_currency(res)["RSD"]]
    assert rsd == [([A, "2023-06-01"], 100.0), ([A, "2023-07-01"], 300.0), ([B, "2023-06-01"], 500.0)]


def test_limit_is_per_currency_and_truncation_is_reported(sample):
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc", limit=1))
    assert {r["currency"]: r["dims"][0] for r in res["rows"]} == {"RSD": B, "EUR": F}
    assert res["truncated_currencies"] == ["EUR", "RSD"]
    res = run_pivot(sample, ALL, q(dimensions=["isin"], measures=["turnover"],
                                    sort_by="turnover", order="desc", limit=2))
    assert res["truncated_currencies"] == [] and len(res["rows"]) == 4
    zero = run_pivot(sample, ALL, q(measures=["turnover"], limit=1))
    assert zero["truncated_currencies"] == [] and len(zero["rows"]) == 2


def test_filters_apply_before_grouping(sample):
    res = run_pivot(sample, FilterSpec(currency=["EUR"]), q(dimensions=["isin"], measures=["turnover"]))
    assert {r["currency"] for r in res["rows"]} == {"EUR"}
    res = run_pivot(sample, FilterSpec(remaining_maturity_years=Range(min=3)), q(measures=["turnover"]))
    assert {r["currency"]: r["values"][0] for r in res["rows"]} == {"EUR": 120.0, "RSD": 400.0}


def test_ties_are_broken_by_dimension_ascending(conn):
    load_rows(conn, [make_row(isin=B, turnover=10.0), make_row(isin=A, turnover=10.0)])
    res = run_pivot(conn, ALL, q(dimensions=["isin"], measures=["turnover"],
                                  sort_by="turnover", order="desc"))
    assert [r["dims"][0] for r in res["rows"]] == [A, B]


def test_empty_result(conn):
    res = run_pivot(conn, ALL, q(dimensions=["isin"], measures=["turnover"]))
    assert res["rows"] == [] and res["truncated_currencies"] == []
```

Append to `tests/test_real_data.py` (add the imports it lacks):

```python
from securities_analyzer.query.pivot import PivotQuery, run_pivot


def _rows(res, currency):
    return [r for r in res["rows"] if r["currency"] == currency]


def test_golden_pivot_most_traded_securities_2024(real_conn):
    spec = FilterSpec(date_from="2024-01-01", date_to="2024-12-31")
    res = run_pivot(real_conn, spec, PivotQuery(
        dimensions=["isin"], measures=["turnover", "quantity", "transactions", "weighted_yield"],
        sort_by="turnover", order="desc", limit=5))
    expected = {
        "RSD": [("RSMFRSD58761", 121471327158.97, 10904256, 541, 5.5628),
                ("RSMFRSD86176", 105048689266.66, 11105945, 685, 5.4735),
                ("RSMFRSD55940", 43845029342.10, 4107635, 289, 4.5509),
                ("RSMFRSD89592", 28305748426.46, 2799899, 185, 4.6835),
                ("RSMFRSD90335", 8727699321.06, 873622, 10, 4.1348)],
        "EUR": [("RSMFRSD51436", 43154118.53, 43261, 48, 3.6302),
                ("RSMFRSD66798", 38485549.00, 41120, 19, 2.4128),
                ("RSMFRSD70022", 20734643.90, 19860, 8, 3.8982),
                ("RSMFRSD84510", 19348117.50, 19000, 7, 3.5481),
                ("RSMFRSD68802", 18076263.44, 17992, 14, 3.9726)],
    }
    for cur, exp in expected.items():
        got = _rows(res, cur)
        assert len(got) == 5
        for row, (isin, turnover, qty, tx, wy) in zip(got, exp):
            assert row["dims"] == [isin]
            assert row["values"][0] == pytest.approx(turnover, rel=1e-9)
            assert row["values"][1] == qty and row["values"][2] == tx
            assert row["values"][3] == pytest.approx(wy, abs=5e-5)


def test_golden_pivot_yield_by_year_and_bucket(real_conn):
    spec = FilterSpec(currency=["RSD"], date_to="2022-12-31")
    res = run_pivot(real_conn, spec, PivotQuery(
        dimensions=["date_year", "remaining_bucket"], measures=["weighted_yield"],
        sort_by="group", order="asc"))
    first = [(r["dims"], r["values"][0]) for r in res["rows"][:6]]
    assert [d for d, _ in first] == [
        ["2020", "0-1Y"], ["2020", "1-3Y"], ["2020", "3-5Y"], ["2020", "5-10Y"],
        ["2020", "10Y+"], ["2021", "0-1Y"]]
    for (_, value), exp in zip(first, [1.5359, 2.0573, 2.3980, 2.9846, 3.8285, 1.0443]):
        assert value == pytest.approx(exp, abs=5e-5)


def test_golden_pivot_group_counts_and_truncation(real_conn):
    base = dict(dimensions=["date_day", "isin"], measures=["turnover"], sort_by="group", order="asc")
    full = run_pivot(real_conn, FilterSpec(), PivotQuery(**base, limit=5000))
    assert len(_rows(full, "RSD")) == 3887 and len(_rows(full, "EUR")) == 1141
    assert full["truncated_currencies"] == []
    cut = run_pivot(real_conn, FilterSpec(), PivotQuery(**base, limit=1000))
    assert len(_rows(cut, "RSD")) == 1000 and len(_rows(cut, "EUR")) == 1000
    assert cut["truncated_currencies"] == ["EUR", "RSD"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pivot.py tests/test_real_data.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_pivot'`.

- [ ] **Step 3: Implement**

Append to `securities_analyzer/query/pivot.py` (add the imports at the top of the file with the existing ones):

```python
import sqlite3

from .builder import build_where
from .filters import FilterSpec


def run_pivot(conn: sqlite3.Connection, spec: FilterSpec, query: PivotQuery) -> dict:
    """Group the filtered rows by currency + the chosen dimensions and compute the chosen measures.

    Only catalog expressions reach the SQL text; the filter values and the row limit are bound
    parameters. `limit` applies per currency (ROW_NUMBER partitioned by currency); one extra row
    per currency is fetched to detect truncation.
    """
    where, params = build_where(spec)
    dims = [DIMENSIONS[d] for d in query.dimensions]
    measures = [MEASURES[m] for m in query.measures]

    select = ["currency"]
    group = ["currency"]
    for i, d in enumerate(dims):
        select += [f"{d.value_sql} AS d{i}", f"{d.sort_sql} AS s{i}"]
        group.append(d.value_sql)
        if d.sort_sql != d.value_sql:
            group.append(d.sort_sql)
    select += [f"{m.sql} AS m{j}" for j, m in enumerate(measures)]

    direction = "ASC" if query.order == "asc" else "DESC"
    if query.sort_by == "group":
        order_by = [f"s{i} {direction}" for i in range(len(dims))] or ["currency"]
    else:
        j = query.measures.index(query.sort_by)
        order_by = [f"(m{j} IS NULL)", f"m{j} {direction}", *[f"s{i} ASC" for i in range(len(dims))]]

    sql = f"""
        WITH g AS (
          SELECT {', '.join(select)}
          FROM trades WHERE {where}
          GROUP BY {', '.join(group)}),
        r AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY currency ORDER BY {', '.join(order_by)}) AS rn
          FROM g)
        SELECT * FROM r WHERE rn <= ? ORDER BY currency, rn"""

    rows: list[dict] = []
    truncated: set[str] = set()
    for r in conn.execute(sql, [*params, query.limit + 1]):
        if r["rn"] > query.limit:
            truncated.add(r["currency"])
            continue
        rows.append({
            "currency": r["currency"],
            "dims": [r[f"d{i}"] for i in range(len(dims))],
            "values": [r[f"m{j}"] for j in range(len(measures))],
        })
    return {
        "dimensions": [{"id": d.id, "label": d.label} for d in dims],
        "measures": [{"id": m.id, "label": m.label, "unit": m.unit} for m in measures],
        "rows": rows,
        "truncated_currencies": sorted(truncated),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pivot.py tests/test_real_data.py -v`, then the full suite.
Expected: all PASS. If a golden number differs, STOP and cross-check with "Verified facts" (independent plain-Python computation) before touching the SQL — never edit the expected values to match.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat(pivot): run_pivot engine with per-currency top-N, NULL-last sorting, golden tests" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 3: Schema v2 and saved queries with a pivot config

**Files:**
- Modify: `securities_analyzer/db/schema.py`, `securities_analyzer/api/app.py` (saved-query routes only), `tests/test_db.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `PivotConfig` (Task 1), existing `SaveBody`, saved-query routes, `connect`, `init_schema`, `get_meta`; the existing `client` fixture in `tests/test_api.py`.
- Produces:
  - `SCHEMA_VERSION = 2`; `saved_queries(name, filter_json, pivot_json TEXT NULL)`; `init_schema` migrates a v1 database in place (adds the column), is idempotent, and sets `meta.schema_version` to `"2"`.
  - `PUT /api/saved-queries` body `{name, filter, pivot?}` (`pivot` is a `PivotConfig`); `GET /api/saved-queries` → `[{name, filter, pivot}]` where `pivot` is the stored object or `null`. Saving without `pivot` clears a previously stored one.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, change the existing assertion in `test_schema_objects` from `== "1"` to `== "2"`, add `import sqlite3` at the top, and append:

```python
def test_v1_database_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
        INSERT INTO saved_queries VALUES ('stari', '{"currency": ["RSD"]}');
    """)
    raw.close()
    conn = connect(path)
    init_schema(conn)
    init_schema(conn)                                    # idempotent
    assert get_meta(conn, "schema_version") == "2"
    row = conn.execute("SELECT name, filter_json, pivot_json FROM saved_queries").fetchone()
    assert (row["name"], row["filter_json"], row["pivot_json"]) == ("stari", '{"currency": ["RSD"]}', None)
    conn.close()


def test_fresh_database_has_pivot_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(saved_queries)")]
    assert cols == ["name", "filter_json", "pivot_json"]
```

Append to `tests/test_api.py`:

```python
def test_saved_query_with_pivot_roundtrip(client):
    pivot = {"dimensions": ["isin"], "measures": ["turnover", "quantity"], "sort_by": "turnover",
             "order": "desc", "limit": 10, "chart": {"type": "bar", "horizontal": True}}
    body = {"name": "Top hartije", "filter": {"currency": ["RSD"]}, "pivot": pivot}
    assert client.put("/api/saved-queries", json=body).status_code == 200
    (item,) = client.get("/api/saved-queries").json()
    assert item["name"] == "Top hartije" and item["filter"]["currency"] == ["RSD"]
    assert item["pivot"] == pivot


def test_saved_query_without_pivot_has_null_and_overwrite_clears(client):
    pivot = {"dimensions": [], "measures": ["turnover"], "sort_by": "group", "order": "asc",
             "limit": 100, "chart": {"type": "table", "horizontal": False}}
    client.put("/api/saved-queries", json={"name": "x", "filter": {}, "pivot": pivot})
    assert client.get("/api/saved-queries").json()[0]["pivot"] == pivot
    client.put("/api/saved-queries", json={"name": "x", "filter": {}})
    assert client.get("/api/saved-queries").json()[0]["pivot"] is None


@pytest.mark.parametrize("pivot", [
    {"dimensions": ["nope"]},
    {"measures": []},
    {"sort_by": "quantity"},
    {"chart": {"type": "pie"}},
    {"limit": 99999},
])
def test_saved_query_rejects_invalid_pivot(client, pivot):
    r = client.put("/api/saved-queries", json={"name": "bad", "filter": {}, "pivot": pivot})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_api.py -v`
Expected: FAIL (`"1" != "2"`, missing `pivot_json` column, `pivot` not returned).

- [ ] **Step 3: Implement**

`securities_analyzer/db/schema.py`:
- set `SCHEMA_VERSION = 2`;
- change the `saved_queries` DDL in `SCHEMA` to `CREATE TABLE IF NOT EXISTS saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL, pivot_json TEXT);`;
- replace `init_schema` with:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(saved_queries)")}
    if "pivot_json" not in cols:
        conn.execute("ALTER TABLE saved_queries ADD COLUMN pivot_json TEXT")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
```

`securities_analyzer/api/app.py` (saved-query part; keep the existing name validation on `SaveBody` untouched):

```python
from ..query.pivot import PivotConfig          # with the other query imports
```

```python
class SaveBody(BaseModel):
    # ... existing `name` field and its validator stay as they are ...
    filter: FilterSpec
    pivot: PivotConfig | None = None
```

```python
    @app.get("/api/saved-queries")
    def saved_list(conn=Depends(get_conn)):
        return [
            {"name": r["name"], "filter": json.loads(r["filter_json"]),
             "pivot": json.loads(r["pivot_json"]) if r["pivot_json"] else None}
            for r in conn.execute(
                "SELECT name, filter_json, pivot_json FROM saved_queries ORDER BY name")
        ]

    @app.put("/api/saved-queries")
    def saved_put(body: SaveBody, conn=Depends(get_conn)):
        with conn:
            conn.execute(
                "INSERT INTO saved_queries (name, filter_json, pivot_json) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET filter_json = excluded.filter_json, "
                "pivot_json = excluded.pivot_json",
                (body.name, body.filter.model_dump_json(),
                 body.pivot.model_dump_json() if body.pivot else None))
        return {"saved": body.name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_api.py -v`, then the full suite.
Expected: all PASS (existing saved-query tests keep passing: the response only gained a `pivot` key).

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat(db,api): schema v2 with saved-query pivot config and in-place migration" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 4: Catalog, pivot query and pivot export endpoints

**Files:**
- Create: `securities_analyzer/api/exporting.py`, `tests/test_exporting.py`
- Modify: `securities_analyzer/api/app.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `PivotQuery`, `run_pivot`, `catalog_payload`, existing `export_dir`, `service.ROW_COLUMNS`, the overview export route.
- Produces:
  - `exporting.unique_export_path(export_dir: Path, stem: str, ext: str) -> Path` (creates the directory; name `<stem>_<YYYYmmdd_HHMMSS>.<ext>`, with `_2`, `_3`… appended if it already exists); `exporting.write_table(path: Path, header: list[str], rows: list[list], fmt: Literal["csv","xlsx"]) -> None` (CSV `utf-8-sig`; XLSX sheet title `Podaci`).
  - `GET /api/pivot/catalog` → `catalog_payload()`.
  - `POST /api/query/pivot` body `{filter?, dimensions?, measures?, sort_by?, order?, limit?}` → the `run_pivot` result.
  - `POST /api/export/pivot` body as above + `format` (`csv`|`xlsx`) → `{path, rows}`; header row: `Valuta`, dimension labels…, measure labels…
  - The existing `POST /api/export` keeps its behaviour and file naming (`securities_<ts>.<ext>`) but is implemented with the helpers.

- [ ] **Step 1: Write the failing tests**

`tests/test_exporting.py`:

```python
from datetime import datetime

from openpyxl import load_workbook

from securities_analyzer.api import exporting


def test_unique_export_path_appends_counter_on_collision(tmp_path, monkeypatch):
    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 9, 30, 15)

    monkeypatch.setattr(exporting, "datetime", FixedNow)
    d = tmp_path / "out"
    p1 = exporting.unique_export_path(d, "securities", "csv")
    p1.write_text("x")
    p2 = exporting.unique_export_path(d, "securities", "csv")
    p2.write_text("x")
    p3 = exporting.unique_export_path(d, "securities", "csv")
    assert [p.name for p in (p1, p2, p3)] == [
        "securities_20261012_093015.csv", "securities_20261012_093015_2.csv",
        "securities_20261012_093015_3.csv"]


def test_write_table_csv_has_bom_header_and_rows(tmp_path):
    path = tmp_path / "t.csv"
    exporting.write_table(path, ["A", "B"], [[1, "x"], [2, None]], "csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_text(encoding="utf-8-sig").splitlines() == ["A,B", "1,x", "2,"]


def test_write_table_xlsx_sheet_header_and_rows(tmp_path):
    path = tmp_path / "t.xlsx"
    exporting.write_table(path, ["A", "B"], [[1, "x"], [2, None]], "xlsx")
    ws = load_workbook(path).active
    assert ws.title == "Podaci"
    assert [[c.value for c in row] for row in ws.iter_rows()] == [["A", "B"], [1, "x"], [2, None]]
```

Append to `tests/test_api.py` (the existing `client` fixture holds three rows on 2023-06-15: `RSMFRSD0000A` RSD turnover 100, `RSMFRSD0000B` RSD turnover 300, `RSMFRSD0000C` EUR turnover 50):

```python
def test_pivot_catalog(client):
    j = client.get("/api/pivot/catalog").json()
    assert [d["id"] for d in j["dimensions"]][:2] == ["isin", "date_day"]
    assert "weighted_yield" in [m["id"] for m in j["measures"]]
    assert j["limits"]["max_limit"] == 5000


def test_pivot_query_default_body_totals_per_currency(client):
    j = client.post("/api/query/pivot", json={}).json()
    assert [(r["currency"], r["values"][0]) for r in j["rows"]] == [("EUR", 50.0), ("RSD", 400.0)]
    assert j["dimensions"] == [] and j["truncated_currencies"] == []


def test_pivot_query_group_sort_and_filter(client):
    body = {"dimensions": ["isin"], "measures": ["turnover"], "sort_by": "turnover", "order": "desc"}
    j = client.post("/api/query/pivot", json=body).json()
    assert [(r["currency"], r["dims"][0], r["values"][0]) for r in j["rows"]] == [
        ("EUR", "RSMFRSD0000C", 50.0), ("RSD", "RSMFRSD0000B", 300.0), ("RSD", "RSMFRSD0000A", 100.0)]
    j = client.post("/api/query/pivot", json={**body, "filter": {"currency": ["RSD"]}}).json()
    assert {r["currency"] for r in j["rows"]} == {"RSD"}


@pytest.mark.parametrize("body", [
    {"dimensions": ["nope"]},
    {"dimensions": ["isin", "date_day", "coupon"]},
    {"measures": []},
    {"measures": ["turnover", "turnover"]},
    {"sort_by": "quantity"},
    {"limit": 0},
    {"limit": 5001},
    {"filter": {"currency": ["rsd"]}},
    {"unknown": 1},
])
def test_pivot_query_rejects_invalid_requests(client, body):
    assert client.post("/api/query/pivot", json=body).status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_pivot_export_content(client, tmp_path, fmt):
    body = {"dimensions": ["isin"], "measures": ["turnover", "weighted_yield"],
            "sort_by": "turnover", "order": "desc", "format": fmt}
    j = client.post("/api/export/pivot", json=body).json()
    assert j["rows"] == 3
    p = Path(j["path"])
    assert p.exists() and p.suffix == f".{fmt}" and p.parent == tmp_path / "exports"
    header = ["Valuta", "Hartija (ISIN)", "Promet", "Ponderisani prinos"]
    if fmt == "csv":
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0].split(",") == header and len(lines) == 4
    else:
        ws = load_workbook(p).active
        assert [c.value for c in ws[1]] == header and ws.max_row == 4
```
(Add `from openpyxl import load_workbook` and `from pathlib import Path` to the imports of `tests/test_api.py` if they are not already there.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_exporting.py tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: securities_analyzer.api.exporting` / 404 on the new routes.

- [ ] **Step 3: Implement**

`securities_analyzer/api/exporting.py`:

```python
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
```

`securities_analyzer/api/app.py`:
- add imports: `from .exporting import unique_export_path, write_table`, `from ..query.pivot import PivotQuery, run_pivot`, `from ..query.pivot_catalog import catalog_payload`;
- refactor the existing `export` route body so it builds `header = list(service.ROW_COLUMNS)` and `rows = [[r[c] for c in header] for r in data]`, then `path = unique_export_path(export_dir, "securities", body.format)` and `write_table(path, header, rows, body.format)`; the response stays `{"path": str(path), "rows": len(rows)}`. Remove the now-unused `csv`/`datetime` imports if nothing else uses them. The existing export tests must pass unchanged;
- add the models and routes:

```python
class PivotBody(PivotQuery):
    filter: FilterSpec = Field(default_factory=FilterSpec)


class PivotExportBody(PivotBody):
    format: Literal["csv", "xlsx"] = "csv"
```

```python
    @app.get("/api/pivot/catalog")
    def pivot_catalog():
        return catalog_payload()

    @app.post("/api/query/pivot")
    def q_pivot(body: PivotBody, conn=Depends(get_conn)):
        return run_pivot(conn, body.filter, body)

    @app.post("/api/export/pivot")
    def export_pivot(body: PivotExportBody, conn=Depends(get_conn)):
        res = run_pivot(conn, body.filter, body)
        header = ["Valuta"] + [d["label"] for d in res["dimensions"]] + [m["label"] for m in res["measures"]]
        rows = [[r["currency"], *r["dims"], *r["values"]] for r in res["rows"]]
        path = unique_export_path(export_dir, "securities_pivot", body.format)
        write_table(path, header, rows, body.format)
        return {"path": str(path), "rows": len(rows)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_exporting.py tests/test_api.py -v`, then the full suite.
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat(api): pivot catalog, query and export endpoints; shared export helpers" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 5: Pure chart logic module with Node unit tests

**Files:**
- Create: `securities_analyzer/ui/pivot_chart.js`, `tests_js/pivot_chart.test.js`

**Interfaces:**
- Produces `PivotChart` (browser global `window.PivotChart`; also `module.exports` under Node):
  - `chartHint(type, nDims, nMeasures) -> {ok: boolean, note: string|null}`
  - `defaultSort(firstDimKind: string|undefined, firstMeasureId: string) -> {sort_by: string, order: "asc"|"desc"}` — `category` → `{firstMeasureId, "desc"}`, otherwise `{"group", "asc"}`
  - `buildFigure(result, config, helpers) -> {data, layout} | null` — `result` is the `/api/query/pivot` payload, `config` is `{type, horizontal}`, `helpers` is `{labelFor?: (dimId, value) => string, colorFor?: (currency) => string}`; returns `null` for `table`, an invalid combination, or no rows
  - `tableModel(result, labelFor?) -> {header: string[], rows: any[][], units: string[]}` — header `["Valuta", ...dimension labels, ...measure labels]`
- Plotly figure conventions: one panel per currency (columns); for bar/line with 1 dimension and N measures one extra row per measure (grid `rows = N`); subplot `k` uses axes `x`/`y` for `k=1` and `x{k}`/`y{k}` otherwise, layout keys `xaxis`/`yaxis` and `xaxis{k}`/`yaxis{k}`; panel titles are layout annotations.

- [ ] **Step 1: Write the failing tests**

`tests_js/pivot_chart.test.js` (run with `node --test tests_js/pivot_chart.test.js`):

```javascript
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const PC = require("../securities_analyzer/ui/pivot_chart.js");

const colorFor = (c) => ({RSD: "#1f6feb", EUR: "#d9480f"}[c] || "#888");

const oneDim = {
  dimensions: [{id: "isin", label: "Hartija (ISIN)"}],
  measures: [
    {id: "turnover", label: "Promet", unit: "currency"},
    {id: "weighted_yield", label: "Ponderisani prinos", unit: "percent_points"},
  ],
  rows: [
    {currency: "EUR", dims: ["E1"], values: [50, 3.0]},
    {currency: "EUR", dims: ["E2"], values: [70, 2.0]},
    {currency: "RSD", dims: ["A"], values: [400, 5.5]},
    {currency: "RSD", dims: ["B"], values: [500, 5.0]},
  ],
  truncated_currencies: [],
};
const oneMeasure = {...oneDim, measures: [oneDim.measures[0]], rows: oneDim.rows.map((r) => ({...r, values: [r.values[0]]}))};

const twoDims = {
  dimensions: [{id: "date_year", label: "Godina"}, {id: "remaining_bucket", label: "Preostali rok (grupa)"}],
  measures: [{id: "weighted_yield", label: "Ponderisani prinos", unit: "percent_points"}],
  rows: [
    {currency: "RSD", dims: ["2020", "0-1Y"], values: [1.5]},
    {currency: "RSD", dims: ["2020", "1-3Y"], values: [2.0]},
    {currency: "RSD", dims: ["2021", "0-1Y"], values: [1.0]},
  ],
  truncated_currencies: [],
};

test("chartHint rules", () => {
  assert.deepEqual(PC.chartHint("table", 0, 1), {ok: true, note: null});
  assert.equal(PC.chartHint("bar", 0, 1).ok, false);
  assert.deepEqual(PC.chartHint("bar", 1, 2), {ok: true, note: null});
  assert.match(PC.chartHint("bar", 2, 2).note, /prva mera/);
  assert.equal(PC.chartHint("line", 0, 1).ok, false);
  assert.equal(PC.chartHint("scatter", 1, 1).ok, false);
  assert.equal(PC.chartHint("scatter", 0, 2).ok, false);
  assert.deepEqual(PC.chartHint("scatter", 1, 2), {ok: true, note: null});
  assert.equal(PC.chartHint("heatmap", 1, 1).ok, false);
  assert.equal(PC.chartHint("heatmap", 3, 1).ok, false);
  assert.deepEqual(PC.chartHint("heatmap", 2, 1), {ok: true, note: null});
  assert.equal(PC.chartHint("bar", 1, 0).ok, false);
  assert.equal(PC.chartHint("pie", 1, 1).ok, false);
});

test("defaultSort: category by measure, ordered kinds by group", () => {
  assert.deepEqual(PC.defaultSort("category", "turnover"), {sort_by: "turnover", order: "desc"});
  assert.deepEqual(PC.defaultSort("time", "turnover"), {sort_by: "group", order: "asc"});
  assert.deepEqual(PC.defaultSort("ordinal", "turnover"), {sort_by: "group", order: "asc"});
  assert.deepEqual(PC.defaultSort(undefined, "turnover"), {sort_by: "group", order: "asc"});
});

test("buildFigure returns null for table, invalid combos and empty results", () => {
  assert.equal(PC.buildFigure(oneDim, {type: "table"}, {colorFor}), null);
  assert.equal(PC.buildFigure(oneDim, {type: "heatmap"}, {colorFor}), null);
  assert.equal(PC.buildFigure({...oneDim, rows: []}, {type: "bar"}, {colorFor}), null);
});

test("vertical bars: one panel per currency, currency colour, titles", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.data.length, 2);
  const [eur, rsd] = fig.data;
  assert.equal(eur.type, "bar");
  assert.deepEqual(eur.x, ["E1", "E2"]);
  assert.deepEqual(eur.y, [50, 70]);
  assert.equal(eur.marker.color, "#d9480f");
  assert.equal(eur.xaxis, "x");
  assert.equal(eur.yaxis, "y");
  assert.deepEqual(rsd.x, ["A", "B"]);
  assert.equal(rsd.xaxis, "x2");
  assert.equal(rsd.yaxis, "y2");
  assert.equal(fig.layout.grid.rows, 1);
  assert.equal(fig.layout.grid.columns, 2);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text), ["EUR", "RSD"]);
  assert.equal(fig.layout.yaxis.title.text, "Promet");
});

test("horizontal bars swap axes and put the first category on top", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar", horizontal: true}, {colorFor});
  const eur = fig.data[0];
  assert.equal(eur.orientation, "h");
  assert.deepEqual(eur.y, ["E1", "E2"]);
  assert.deepEqual(eur.x, [50, 70]);
  assert.equal(fig.layout.yaxis.autorange, "reversed");
  assert.equal(fig.layout.xaxis.title.text, "Promet");
});

test("several measures with one dimension get one row of panels per measure", () => {
  const fig = PC.buildFigure(oneDim, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.layout.grid.rows, 2);
  assert.equal(fig.layout.grid.columns, 2);
  assert.equal(fig.data.length, 4);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text),
    ["EUR · Promet", "RSD · Promet", "EUR · Ponderisani prinos", "RSD · Ponderisani prinos"]);
  assert.deepEqual(fig.data[2].y, [3.0, 2.0]);
  assert.equal(fig.data[2].xaxis, "x3");
  assert.equal(fig.data[3].yaxis, "y4");
});

test("two dimensions: series per second dimension, null for missing cells, one legend entry each", () => {
  const fig = PC.buildFigure(twoDims, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.data.length, 2);
  const byName = Object.fromEntries(fig.data.map((t) => [t.name, t]));
  assert.deepEqual(byName["0-1Y"].x, ["2020", "2021"]);
  assert.deepEqual(byName["0-1Y"].y, [1.5, 1.0]);
  assert.deepEqual(byName["1-3Y"].y, [2.0, null]);
  assert.equal(fig.data.filter((t) => t.showlegend).length, 2);
  assert.equal(fig.layout.showlegend, true);
});

test("line charts use scatter traces with lines+markers", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "line"}, {colorFor});
  assert.equal(fig.data[0].type, "scatter");
  assert.equal(fig.data[0].mode, "lines+markers");
  assert.equal(fig.data[0].line.color, "#d9480f");
});

test("scatter: x and y are the first two measures, size from the third", () => {
  const three = {
    ...oneDim,
    measures: [...oneDim.measures, {id: "quantity", label: "Količina", unit: "pieces"}],
    rows: [
      {currency: "RSD", dims: ["A"], values: [400, 5.5, 4]},
      {currency: "RSD", dims: ["B"], values: [500, 5.0, 1]},
    ],
  };
  const fig = PC.buildFigure(three, {type: "scatter"}, {colorFor, labelFor: (id, v) => `${id}:${v}`});
  assert.equal(fig.data.length, 1);
  const t = fig.data[0];
  assert.deepEqual(t.x, [400, 500]);
  assert.deepEqual(t.y, [5.5, 5.0]);
  assert.deepEqual(t.text, ["isin:A", "isin:B"]);
  assert.equal(t.marker.size[0], 28);
  assert.equal(t.marker.size[1], 14);
  assert.equal(fig.layout.xaxis.title.text, "Promet");
  assert.equal(fig.layout.yaxis.title.text, "Ponderisani prinos");
  const noSize = PC.buildFigure(oneDim, {type: "scatter"}, {colorFor});
  assert.equal(noSize.data[0].marker.size[0], 10);
});

test("heatmap: matrix of the first measure with null gaps", () => {
  const fig = PC.buildFigure(twoDims, {type: "heatmap"}, {colorFor});
  assert.equal(fig.data.length, 1);
  const t = fig.data[0];
  assert.equal(t.type, "heatmap");
  assert.deepEqual(t.x, ["2020", "2021"]);
  assert.deepEqual(t.y, ["0-1Y", "1-3Y"]);
  assert.deepEqual(t.z, [[1.5, 1.0], [2.0, null]]);
});

test("labelFor is applied to category labels", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar"}, {colorFor, labelFor: (id, v) => `<${v}>`});
  assert.deepEqual(fig.data[1].x, ["<A>", "<B>"]);
});

test("tableModel header, rows and units", () => {
  const m = PC.tableModel(oneDim, (id, v) => `#${v}`);
  assert.deepEqual(m.header, ["Valuta", "Hartija (ISIN)", "Promet", "Ponderisani prinos"]);
  assert.deepEqual(m.rows[0], ["EUR", "#E1", 50, 3.0]);
  assert.deepEqual(m.units, ["currency", "percent_points"]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests_js/pivot_chart.test.js`
Expected: FAIL — `Cannot find module '../securities_analyzer/ui/pivot_chart.js'`.

- [ ] **Step 3: Implement**

`securities_analyzer/ui/pivot_chart.js`:

```javascript
"use strict";
/* Pure chart/table logic for the Analiza view. No DOM, no network: unit-tested with `node --test`. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PivotChart = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const PALETTE = ["#1f6feb", "#d9480f", "#2f9e44", "#9c36b5", "#e8590c", "#0c8599", "#c2255c", "#5f3dc4", "#868e96", "#f08c00"];

  const uniq = (values) => [...new Set(values)];
  const suffix = (k) => (k === 1 ? "" : String(k));
  const axisRef = (prefix, k) => prefix + suffix(k);       // trace.xaxis: "x", "x2", ...
  const axisKey = (prefix, k) => prefix + "axis" + suffix(k); // layout key: "xaxis", "xaxis2", ...

  function chartHint(type, nDims, nMeasures) {
    if (type === "table") return {ok: true, note: null};
    if (nMeasures < 1) return {ok: false, note: "Izaberi bar jednu meru."};
    if (type === "bar" || type === "line") {
      if (nDims < 1) return {ok: false, note: "Stubići i linija traže bar jedno grupisanje."};
      return {ok: true, note: nDims === 2 && nMeasures > 1 ? "Uz dva grupisanja crta se samo prva mera." : null};
    }
    if (type === "scatter") {
      if (nDims < 1) return {ok: false, note: "Tačkasti grafik traži bar jedno grupisanje (jedna tačka je jedna grupa)."};
      if (nMeasures < 2) return {ok: false, note: "Tačkasti grafik traži bar dve mere (x i y)."};
      return {ok: true, note: null};
    }
    if (type === "heatmap") {
      if (nDims !== 2) return {ok: false, note: "Toplotna mapa traži tačno dva grupisanja."};
      return {ok: true, note: nMeasures > 1 ? "Crta se samo prva mera." : null};
    }
    return {ok: false, note: "Nepoznata vrsta grafika."};
  }

  function defaultSort(firstDimKind, firstMeasureId) {
    if (firstDimKind === "category") return {sort_by: firstMeasureId, order: "desc"};
    return {sort_by: "group", order: "asc"};
  }

  function dimLabel(result, row, i, labelFor) {
    const id = result.dimensions[i].id;
    const v = row.dims[i];
    return String(labelFor ? labelFor(id, v) : v);
  }

  function panelTitle(text, r, c, nRows, nCols) {
    return {text, showarrow: false, xref: "paper", yref: "paper", x: (c + 0.5) / nCols,
            y: 1 - r / nRows, xanchor: "center", yanchor: "bottom", font: {size: 12}};
  }

  const gridOf = (rows, columns) => ({rows, columns, pattern: "independent", xgap: 0.12, ygap: 0.35});

  function barLine(result, config, h, currencies) {
    const twoDims = result.dimensions.length === 2;
    const measureIdx = twoDims ? [0] : result.measures.map((_, i) => i);
    const nRows = measureIdx.length;
    const nCols = currencies.length;
    const isLine = config.type === "line";
    const horizontal = !!config.horizontal && !isLine;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(nRows, nCols), annotations, barmode: "group", showlegend: twoDims};
    const seen = new Set();
    measureIdx.forEach((mi, r) => {
      const measure = result.measures[mi];
      currencies.forEach((cur, c) => {
        const k = r * nCols + c + 1;
        const rows = result.rows.filter((x) => x.currency === cur);
        const cats = uniq(rows.map((x) => dimLabel(result, x, 0, h.labelFor)));
        const names = twoDims ? uniq(rows.map((x) => dimLabel(result, x, 1, h.labelFor))) : [measure.label];
        const lookup = new Map();
        rows.forEach((x) => {
          const key = dimLabel(result, x, 0, h.labelFor) + "\u0000" + (twoDims ? dimLabel(result, x, 1, h.labelFor) : "");
          lookup.set(key, x.values[mi]);
        });
        names.forEach((name, si) => {
          const vals = cats.map((cat) => {
            const v = lookup.get(cat + "\u0000" + (twoDims ? name : ""));
            return v === undefined ? null : v;
          });
          const color = twoDims ? PALETTE[si % PALETTE.length] : h.colorFor(cur);
          const trace = {
            type: isLine ? "scatter" : "bar", name, legendgroup: name,
            showlegend: twoDims && !seen.has(name), xaxis: axisRef("x", k), yaxis: axisRef("y", k),
          };
          if (isLine) { trace.mode = "lines+markers"; trace.line = {color}; } else { trace.marker = {color}; }
          if (horizontal) { trace.x = vals; trace.y = cats; trace.orientation = "h"; } else { trace.x = cats; trace.y = vals; }
          seen.add(name);
          data.push(trace);
        });
        layout[axisKey("x", k)] = horizontal ? {title: {text: measure.label}} : {type: "category"};
        layout[axisKey("y", k)] = horizontal
          ? {type: "category", autorange: "reversed", automargin: true}
          : {title: {text: measure.label}};
        annotations.push(panelTitle(nRows > 1 ? `${cur} · ${measure.label}` : cur, r, c, nRows, nCols));
      });
    });
    return {data, layout};
  }

  function scatter(result, h, currencies) {
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const hasSize = result.measures.length >= 3;
      const maxSize = hasSize ? Math.max(...rows.map((x) => Math.abs(x.values[2] || 0)), 0) || 1 : 1;
      data.push({
        type: "scatter", mode: "markers", name: cur,
        x: rows.map((x) => x.values[0]), y: rows.map((x) => x.values[1]),
        text: rows.map((x) => result.dimensions.map((_, i) => dimLabel(result, x, i, h.labelFor)).join(" · ")),
        marker: {
          color: h.colorFor(cur), opacity: 0.7,
          size: rows.map((x) => (hasSize ? Math.max(6, Math.sqrt(Math.abs(x.values[2] || 0) / maxSize) * 28) : 10)),
        },
        xaxis: axisRef("x", k), yaxis: axisRef("y", k),
        hovertemplate: "%{text}<br>%{x}<br>%{y}<extra>" + cur + "</extra>",
      });
      layout[axisKey("x", k)] = {title: {text: result.measures[0].label}};
      layout[axisKey("y", k)] = {title: {text: result.measures[1].label}};
      annotations.push(panelTitle(cur, 0, c, 1, nCols));
    });
    return {data, layout};
  }

  function heatmap(result, h, currencies) {
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const xs = uniq(rows.map((x) => dimLabel(result, x, 0, h.labelFor)));
      const ys = uniq(rows.map((x) => dimLabel(result, x, 1, h.labelFor)));
      const lookup = new Map();
      rows.forEach((x) => lookup.set(dimLabel(result, x, 0, h.labelFor) + "\u0000" + dimLabel(result, x, 1, h.labelFor), x.values[0]));
      data.push({
        type: "heatmap", name: cur, x: xs, y: ys, colorscale: "Blues", hoverongaps: false,
        z: ys.map((y) => xs.map((x) => { const v = lookup.get(x + "\u0000" + y); return v === undefined ? null : v; })),
        showscale: nCols === 1, xaxis: axisRef("x", k), yaxis: axisRef("y", k),
      });
      layout[axisKey("x", k)] = {type: "category"};
      layout[axisKey("y", k)] = {type: "category", autorange: "reversed"};
      annotations.push(panelTitle(cur, 0, c, 1, nCols));
    });
    return {data, layout};
  }

  function buildFigure(result, config, helpers) {
    const h = Object.assign({labelFor: null, colorFor: () => PALETTE[0]}, helpers || {});
    const hint = chartHint(config.type, result.dimensions.length, result.measures.length);
    if (config.type === "table" || !hint.ok || !result.rows.length) return null;
    const currencies = uniq(result.rows.map((r) => r.currency));
    if (config.type === "scatter") return scatter(result, h, currencies);
    if (config.type === "heatmap") return heatmap(result, h, currencies);
    return barLine(result, config, h, currencies);
  }

  function tableModel(result, labelFor) {
    const header = ["Valuta", ...result.dimensions.map((d) => d.label), ...result.measures.map((m) => m.label)];
    const rows = result.rows.map((r) => [
      r.currency,
      ...r.dims.map((v, i) => (labelFor ? labelFor(result.dimensions[i].id, v) : v)),
      ...r.values,
    ]);
    return {header, rows, units: result.measures.map((m) => m.unit)};
  }

  return {chartHint, defaultSort, buildFigure, tableModel};
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests_js/pivot_chart.test.js`
Expected: all tests PASS. Also run `node --check securities_analyzer/ui/pivot_chart.js` and the Python suite (`.venv\Scripts\python.exe -m pytest -q`) to confirm nothing else changed.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat(ui): pure pivot chart/table logic with node unit tests" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 6: Analiza view — HTML, CSS, `analysis.js`, `app.js` wiring

**Files:**
- Create: `securities_analyzer/ui/analysis.js`
- Modify: `securities_analyzer/ui/index.html`, `securities_analyzer/ui/styles.css`, `securities_analyzer/ui/app.js`, `tests/test_ui_static.py`

**Interfaces:**
- Consumes: `PivotChart` (Task 5), `/api/pivot/catalog`, `/api/query/pivot`, `/api/export/pivot`, `/api/saved-queries` (with `pivot`), `/api/securities`; from `app.js` the existing `api`, `readFilter`, `writeFilter`, `showError`, `fmt`, `esc`, `colorFor`, the Plotly wrapper and the securities list.
- Produces:
  - `window.App` (created in `app.js`) = `{api, readFilter, writeFilter, showError, fmt, esc, colorFor, plot(traces, layout, divId = "chart"), securities() -> {isin: {coupon_pct, maturity_date, currency, …}}}`.
  - `window.Analysis` (`analysis.js`) = `{init(): Promise<void>, setActive(bool), getConfig() -> PivotConfig-shaped object, setConfig(cfg), onFilterChange()}`.
  - A mode switch `#mode-overview` / `#mode-analysis`; views `#view-overview` (the existing KPIs, tabs, charts, table) and `#view-analysis`.
  - Saving a query in Analiza mode stores `pivot: Analysis.getConfig()`; loading a saved query with a `pivot` switches to Analiza and restores it; one without switches to Pregled.

- [ ] **Step 1: Extend the static smoke test (failing)**

Append to `tests/test_ui_static.py` (reuse its existing `db_path` client construction with `base_url="http://127.0.0.1"`):

```python
def test_analysis_assets_and_mode_switch_are_served(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    for needle in ('id="mode-overview"', 'id="mode-analysis"', 'id="view-overview"',
                   'id="view-analysis"', "pivot_chart.js", "analysis.js"):
        assert needle in html, needle
    for asset in ("pivot_chart.js", "analysis.js"):
        r = c.get("/" + asset)
        assert r.status_code == 200 and len(r.text) > 500
    assert html.index("pivot_chart.js") < html.index("analysis.js") < html.index("app.js")
```

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui_static.py -v` → Expected: FAIL.

- [ ] **Step 2: `index.html`**

Make these edits (read the current file first; ids below already exist unless marked new):

1. In the header, next to the title, add the mode switch:

```html
<nav id="mode-switch" aria-label="Režim">
  <button id="mode-overview" class="active">Pregled</button>
  <button id="mode-analysis">Analiza</button>
</nav>
```

2. Wrap the existing overview content of `<main>` — `#kpis`, `#tabs`, `#chart-toolbar`, `#chart`, `#extremes-table`, `#table-section` (and anything else that belongs to the old right-hand column) — in `<div id="view-overview"> … </div>`. Do not change any id inside it.

3. Add the new view as a sibling, right after `#view-overview` and still inside `<main>`:

```html
<div id="view-analysis" hidden>
  <section id="builder">
    <div class="b-row">
      <label>Grupiši po <select id="b-dim1"></select></label>
      <label>zatim po <select id="b-dim2"></select></label>
      <fieldset id="b-measures"><legend>Mere (najviše 4)</legend></fieldset>
    </div>
    <div class="b-row">
      <label>Prikaz
        <select id="b-chart">
          <option value="bar">Stubići</option>
          <option value="line">Linija</option>
          <option value="scatter">Tačkasti grafik</option>
          <option value="heatmap">Toplotna mapa</option>
          <option value="table">Samo tabela</option>
        </select>
      </label>
      <label class="chk"><input type="checkbox" id="b-horizontal"> horizontalno</label>
      <label>Sortiraj <select id="b-sort"></select></label>
      <label><select id="b-order">
        <option value="desc">opadajuće</option><option value="asc">rastuće</option>
      </select></label>
      <label>Prvih N po valuti <input type="number" id="b-limit" min="1" max="5000" step="1" value="25"></label>
    </div>
    <div id="b-hint" class="muted"></div>
  </section>
  <div id="a-chart"></div>
  <div id="a-notice" class="muted"></div>
  <section id="a-table-section">
    <div class="table-bar">
      <strong id="a-table-title">Rezultat</strong>
      <span class="spacer"></span>
      <button id="a-csv">Izvezi CSV</button>
      <button id="a-xlsx">Izvezi XLSX</button>
    </div>
    <div class="table-wrap"><table id="a-rows"></table></div>
  </section>
</div>
```

4. Script order at the bottom: `vendor/plotly.min.js`, then `pivot_chart.js`, then `analysis.js`, then `app.js`.

- [ ] **Step 3: `styles.css`** — append (reuse the existing CSS variables):

```css
#mode-switch { display: flex; gap: 6px; }
#mode-switch button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
#builder { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
.b-row { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: flex-end; margin-bottom: 6px; }
.b-row label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
.b-row label.chk { flex-direction: row; align-items: center; gap: 4px; }
#b-measures { display: flex; flex-wrap: wrap; gap: 4px 12px; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; }
#b-measures label { flex-direction: row; align-items: center; gap: 4px; color: var(--ink); }
#b-hint.warn { color: var(--warn); }
#a-chart { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; height: 420px; }
#a-notice { margin: 6px 2px; }
#a-table-section { margin-top: 8px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
```

- [ ] **Step 4: `analysis.js`** (new file, complete):

```javascript
"use strict";
/* Analiza view: builder controls, chart, result table, export. Business rules live on the server;
   chart/axis logic lives in pivot_chart.js. Depends on window.App (app.js) and window.PivotChart. */
const Analysis = (function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    catalog: null, dim1: "isin", dim2: "", measures: ["turnover"], sortBy: "turnover", order: "desc",
    limit: 25, chart: {type: "bar", horizontal: true},
    sortTouched: false, limitTouched: false, horizontalTouched: false,
    seq: 0, last: null, timer: null, active: false,
  };

  const dimIds = () => [state.dim1, state.dim2].filter(Boolean);
  const kindOf = (id) => ((state.catalog.dimensions.find((d) => d.id === id) || {}).kind);
  const measureLabel = (id) => (state.catalog.measures.find((m) => m.id === id) || {}).label || id;

  function labelFor(id, v) {
    if (id === "isin") {
      const s = App.securities()[v];
      return s ? `${v} · ${App.fmt(s.coupon_pct, 2)}% · ${String(s.maturity_date).slice(0, 4)}` : String(v);
    }
    if (id === "coupon") return `${App.fmt(v, 2)}%`;
    if (id === "remaining_years" || id === "original_years") return `${v} god.`;
    if (id === "settlement_lag") return `${v} d.`;
    return v;
  }

  function applyDefaults() {
    const dims = dimIds();
    if (!state.sortTouched) {
      const s = PivotChart.defaultSort(dims.length ? kindOf(dims[0]) : undefined, state.measures[0]);
      state.sortBy = s.sort_by;
      state.order = s.order;
    }
    if (!state.limitTouched) state.limit = dims.length && kindOf(dims[0]) === "category" ? 25 : 1000;
    if (!state.horizontalTouched) state.chart.horizontal = dims.length > 0 && kindOf(dims[0]) === "category";
    if (state.sortBy !== "group" && !state.measures.includes(state.sortBy)) {
      state.sortTouched = false;
      applyDefaults();
    }
  }

  function renderSortOptions() {
    const opts = [["group", "po grupi"], ...state.measures.map((m) => [m, `po meri: ${measureLabel(m)}`])];
    $("b-sort").innerHTML = opts.map(([v, t]) => `<option value="${App.esc(v)}">${App.esc(t)}</option>`).join("");
    $("b-sort").value = state.sortBy;
  }

  function syncControls() {
    $("b-dim1").value = state.dim1;
    $("b-dim2").value = state.dim2;
    document.querySelectorAll("input[name=b-measure]").forEach((i) => { i.checked = state.measures.includes(i.value); });
    updateMeasureLimits();
    $("b-chart").value = state.chart.type;
    $("b-horizontal").checked = !!state.chart.horizontal;
    renderSortOptions();
    $("b-order").value = state.order;
    $("b-limit").value = state.limit;
  }

  function updateMeasureLimits() {
    const max = state.catalog.limits.max_measures;
    document.querySelectorAll("input[name=b-measure]").forEach((i) => {
      i.disabled = !i.checked && state.measures.length >= max;
    });
  }

  function query() {
    return {filter: App.readFilter(), dimensions: dimIds(), measures: state.measures,
            sort_by: state.sortBy, order: state.order, limit: state.limit};
  }

  function schedule() {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, 250);
  }

  function fmtValue(v, unit) {
    if (v === null || v === undefined) return "–";
    return App.fmt(v, unit === "pieces" || unit === "count" ? 0 : 2);
  }

  function drawTable(res) {
    const m = PivotChart.tableModel(res, labelFor);
    const nDims = res.dimensions.length;
    const head = "<thead><tr>" + m.header.map((h, i) => `<th class="${i <= nDims ? "l" : ""}">${App.esc(h)}</th>`).join("") + "</tr></thead>";
    const body = "<tbody>" + m.rows.map((row) => "<tr>" + row.map((v, i) =>
      i <= nDims ? `<td class="l">${App.esc(v)}</td>` : `<td>${App.esc(fmtValue(v, m.units[i - nDims - 1]))}</td>`).join("") + "</tr>").join("") + "</tbody>";
    $("a-rows").innerHTML = head + body;
    $("a-table-title").textContent = `Rezultat (${App.fmt(res.rows.length)} redova)`;
  }

  function drawChart(res, hint) {
    const fig = hint.ok ? PivotChart.buildFigure(res, state.chart, {labelFor, colorFor: App.colorFor}) : null;
    $("a-chart").hidden = !fig;
    if (fig) App.plot(fig.data, fig.layout, "a-chart");
    else if (window.Plotly) Plotly.purge("a-chart");
  }

  function drawNotice(res) {
    const parts = [];
    if (!res.rows.length) parts.push("Nema rezultata za izabrane filtere.");
    if (res.truncated_currencies.length) parts.push(`Prikazano prvih ${App.fmt(state.limit)} po valuti; ima još redova za: ${res.truncated_currencies.join(", ")}.`);
    $("a-notice").textContent = parts.join(" ");
  }

  async function refresh() {
    if (!state.active || !state.catalog) return;
    const token = ++state.seq;
    const hint = PivotChart.chartHint(state.chart.type, dimIds().length, state.measures.length);
    $("b-hint").textContent = hint.note || "";
    $("b-hint").classList.toggle("warn", !hint.ok);
    if (!state.measures.length) { $("a-chart").hidden = true; $("a-rows").innerHTML = ""; return; }
    try {
      const res = await App.api("/api/query/pivot", {body: query()});
      if (token !== state.seq) return;
      state.last = res;
      App.showError("");
      drawChart(res, hint);
      drawTable(res);
      drawNotice(res);
    } catch (e) {
      if (token === state.seq) App.showError(e.message);
    }
  }

  async function doExport(format) {
    try {
      const r = await App.api("/api/export/pivot", {body: {...query(), format}});
      $("a-notice").textContent = `Sačuvano (${App.fmt(r.rows)} redova): ${r.path}`;
    } catch (e) { App.showError(e.message); }
  }

  function getConfig() {
    return {dimensions: dimIds(), measures: [...state.measures], sort_by: state.sortBy, order: state.order,
            limit: state.limit, chart: {type: state.chart.type, horizontal: !!state.chart.horizontal}};
  }

  function setConfig(cfg) {
    if (!state.catalog || !cfg) return;
    const knownDims = new Set(state.catalog.dimensions.map((d) => d.id));
    const knownMeasures = new Set(state.catalog.measures.map((m) => m.id));
    const dims = (cfg.dimensions || []).filter((d) => knownDims.has(d));
    state.dim1 = dims[0] || "";
    state.dim2 = dims[1] || "";
    const ms = (cfg.measures || []).filter((m) => knownMeasures.has(m));
    state.measures = ms.length ? ms : ["turnover"];
    state.sortBy = cfg.sort_by === "group" || state.measures.includes(cfg.sort_by) ? cfg.sort_by : "group";
    state.order = cfg.order === "asc" ? "asc" : "desc";
    state.limit = Math.min(Math.max(parseInt(cfg.limit, 10) || 100, 1), state.catalog.limits.max_limit);
    state.chart = {type: (cfg.chart && cfg.chart.type) || "bar", horizontal: !!(cfg.chart && cfg.chart.horizontal)};
    state.sortTouched = state.limitTouched = state.horizontalTouched = true;
    syncControls();
    schedule();
  }

  function fillSelects() {
    const opts = state.catalog.dimensions.map((d) => `<option value="${App.esc(d.id)}">${App.esc(d.label)}</option>`).join("");
    $("b-dim1").innerHTML = `<option value="">(bez grupisanja)</option>` + opts;
    $("b-dim2").innerHTML = `<option value="">(bez)</option>` + opts;
    $("b-measures").innerHTML = `<legend>Mere (najviše ${state.catalog.limits.max_measures})</legend>` + state.catalog.measures.map((m) =>
      `<label><input type="checkbox" name="b-measure" value="${App.esc(m.id)}"> ${App.esc(m.label)}</label>`).join("");
    $("b-limit").max = state.catalog.limits.max_limit;
  }

  function wire() {
    $("b-dim1").onchange = () => { state.dim1 = $("b-dim1").value; if (state.dim2 === state.dim1) state.dim2 = ""; applyDefaults(); syncControls(); schedule(); };
    $("b-dim2").onchange = () => { state.dim2 = $("b-dim2").value; if (state.dim2 && state.dim2 === state.dim1) state.dim2 = ""; applyDefaults(); syncControls(); schedule(); };
    $("b-measures").addEventListener("change", () => {
      state.measures = [...document.querySelectorAll("input[name=b-measure]:checked")].map((i) => i.value);
      applyDefaults();
      syncControls();
      schedule();
    });
    $("b-chart").onchange = () => { state.chart.type = $("b-chart").value; schedule(); };
    $("b-horizontal").onchange = () => { state.chart.horizontal = $("b-horizontal").checked; state.horizontalTouched = true; schedule(); };
    $("b-sort").onchange = () => { state.sortBy = $("b-sort").value; state.sortTouched = true; schedule(); };
    $("b-order").onchange = () => { state.order = $("b-order").value; state.sortTouched = true; schedule(); };
    $("b-limit").oninput = () => {
      const n = parseInt($("b-limit").value, 10);
      if (n >= 1 && n <= state.catalog.limits.max_limit) { state.limit = n; state.limitTouched = true; schedule(); }
    };
    $("a-csv").onclick = () => doExport("csv");
    $("a-xlsx").onclick = () => doExport("xlsx");
  }

  async function init() {
    state.catalog = await App.api("/api/pivot/catalog");
    fillSelects();
    wire();
    applyDefaults();
    syncControls();
  }

  function setActive(flag) {
    state.active = !!flag;
    if (state.active) refresh();
  }

  return {init, setActive, getConfig, setConfig, onFilterChange: schedule};
})();
```

- [ ] **Step 5: `app.js` wiring** (read the file; make exactly these changes, keep everything else):

1. Generalize the Plotly wrapper: `plot(traces, layout, div = "chart")` → use `div` in `Plotly.purge(div)` / `Plotly.newPlot(div, …)`. Existing callers keep working.
2. Keep the securities list: where `loadIsins` fetches `/api/securities`, also store `state.securities = Object.fromEntries(list.map((s) => [s.isin, s]))`.
3. After the helper functions (`api`, `readFilter`, `writeFilter`, `showError`, `fmt`, `esc`, `colorFor`, `plot`) are defined, create `window.App = {api, readFilter, writeFilter, showError, fmt, esc, colorFor, plot, securities: () => state.securities || {}}`.
4. Mode handling: add `state.mode = "overview"` and

```javascript
function setMode(mode) {
  state.mode = mode;
  $("view-overview").hidden = mode !== "overview";
  $("view-analysis").hidden = mode !== "analysis";
  $("mode-overview").classList.toggle("active", mode === "overview");
  $("mode-analysis").classList.toggle("active", mode === "analysis");
  Analysis.setActive(mode === "analysis");
  if (mode === "overview") refreshAll(true);
}
const refreshCurrent = () => (state.mode === "analysis" ? Analysis.onFilterChange() : refreshAll(true));
```

   Wire `$("mode-overview").onclick = () => setMode("overview")` and `$("mode-analysis").onclick = () => setMode("analysis")`.
5. Make filter-driven refreshes mode-aware: the debounced filter handler, the Reset button, the saved-query Load button and the end of `runUpdate` call `refreshCurrent()` instead of `refreshAll()`/`refreshAll(true)`.
6. Saved queries: `window.__saved` stores the whole item (`Object.fromEntries(items.map((i) => [i.name, i]))`); Save sends `{name, filter: readFilter(), pivot: state.mode === "analysis" ? Analysis.getConfig() : null}`; Load does `writeFilter(item.filter)`, then `if (item.pivot) { setMode("analysis"); Analysis.setConfig(item.pivot); } else { setMode("overview"); }` and finally `refreshCurrent()`.
7. In `init()`: after the existing loads, `try { await Analysis.init(); } catch (e) { state.loadError = e.message; }` (the overview must keep working if the catalog fails).

- [ ] **Step 6: Run checks**

Run: `node --check securities_analyzer/ui/app.js`, `node --check securities_analyzer/ui/analysis.js`, `node --test tests_js/pivot_chart.test.js`, `.venv\Scripts\python.exe -m pytest tests/test_ui_static.py -v`, then the full suite.
Expected: all pass. The in-browser behaviour is verified by the controller afterwards against this checklist (do not launch the GUI yourself):
- Pregled works exactly as before (golden query: RSD 6,09% / EUR 4,13% / 388 rows).
- Analiza → defaults to "Hartija (ISIN)" × "Promet", horizontal bars, one panel per currency.
- Example A (2024, top 5 by turnover) matches the "Verified facts" table; changing the chart type, dimensions, measures, sorting and "Prvih N" redraws; heatmap needs exactly two dimensions and shows a hint otherwise.
- Export CSV/XLSX writes a file; saving and loading a view restores mode, builder and filters.

- [ ] **Step 7: Commit**

```powershell
git add -A
git commit -m "feat(ui): Analiza mode with query builder, charts, table, export and saved views" -m "<Co-Authored-By trailer from your harness>"
```

---

### Task 7: CI, README and spec sync

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `README.md`, `docs/superpowers/specs/2026-10-12-query-builder-design.md`

**Interfaces:** none produced; consumes `tests_js/pivot_chart.test.js` and the new UI files.

- [ ] **Step 1: Workflows** — in both files add, directly after the Python test step:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: JS unit tests
        run: node --test tests_js/pivot_chart.test.js
```
(In `release.yml` the new steps must come before "Build seed database" so a failing JS test stops the release.)

- [ ] **Step 2: README** — in "Develop" add `node --test tests_js/pivot_chart.test.js   # chart logic unit tests`; add a short "Analiza" paragraph under the feature description: grouping (up to 2), measures (up to 4), chart types (bar, line, scatter, heatmap, table), top N per currency, currencies never mixed, export and saved views.

- [ ] **Step 3: Spec sync** — update the query-builder spec so it matches what was built:
  - §3: dimension `kind` is `time` / `ordinal` / `category`; bucket, years, coupon and lag are `ordinal`.
  - §7: default sort is group-ascending for `time` and `ordinal` dimensions and first-measure-descending for `category` (ISIN).
  - §4/§5: `order` defaults to `"asc"`.
  - §5: export files get a numeric suffix on same-second collisions; the overview export shares the same helpers.
  - Note that the JS module and its Node tests exist (`tests_js/`), run in CI.

- [ ] **Step 4: Verify and commit**

Run: `.venv\Scripts\python.exe -m pytest -q` and `node --test tests_js/pivot_chart.test.js` — both green.

```powershell
git add -A
git commit -m "docs,ci: node tests in CI/release, README for Analiza, spec sync" -m "<Co-Authored-By trailer from your harness>"
```

---

## Self-review (spec coverage)

| Spec section | Task |
|---|---|
| §2 concepts: implicit currency grouping, filters first | 2 (`GROUP BY currency`, `build_where`) |
| §3 dimensions (11, natural order incl. bucket 1…5) and measures (10) with exact formulas | 1 (catalog), 2 (tests per measure/dimension) |
| §4 limit per currency, NULL last, deterministic tie-break, `limit + 1` truncation | 2 |
| §5 `GET /api/pivot/catalog`, `POST /api/query/pivot`, `POST /api/export/pivot`, saved-query `pivot`, 422 matrix | 1 (validation), 3, 4 |
| §6 storage: `pivot_json` + in-place migration, schema v2 | 3 |
| §7 UI: mode switch, builder bar, chart-type rules, per-currency panels, ISIN enrichment, export, saved views | 5 (logic), 6 (wiring) |
| §8 errors/empty states, stale responses | 6 (`seq` token, notice, hint, banner) |
| §9 testing: service, golden, API, JS unit tests, manual checklist | 2, 3, 4, 5, 6 (checklist) |
| §10 acceptance examples A/B/C | 2 (golden tests); A and B also in the Task 6 checklist |

Type/name consistency checked across tasks: `PivotQuery` fields (`dimensions, measures, sort_by, order, limit`) are identical in `pivot.py`, the API bodies, `analysis.js` `query()` and `getConfig()`; `run_pivot` result keys (`dimensions, measures, rows[currency, dims, values], truncated_currencies`) are the ones `pivot_chart.js` consumes; catalog labels used in tests (`Promet`, `Ponderisani prinos`, `Hartija (ISIN)`) exist in `pivot_catalog.py`; `chart` is `{type, horizontal}` everywhere. No placeholders.
