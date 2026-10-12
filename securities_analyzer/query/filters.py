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
