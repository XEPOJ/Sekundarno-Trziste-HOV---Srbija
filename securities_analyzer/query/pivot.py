import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .builder import build_where
from .filters import FilterSpec
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
