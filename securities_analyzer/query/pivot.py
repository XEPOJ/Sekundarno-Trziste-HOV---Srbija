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
