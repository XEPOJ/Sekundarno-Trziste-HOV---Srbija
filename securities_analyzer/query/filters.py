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
    remaining_maturity_days: Range = Field(default_factory=Range)   # same column as the years filter, entered in days
    original_maturity_years: Range = Field(default_factory=Range)
    coupon_pct: Range = Field(default_factory=Range)
    settlement_lag_days: Range = Field(default_factory=Range)       # no longer shown in the UI; still accepted
    quantity: Range = Field(default_factory=Range)                  # per daily row (one ISIN, one day)
    turnover: Range = Field(default_factory=Range)                  # per daily row, in the row's own currency
    min_price: Range = Field(default_factory=Range)                 # the day's lowest price
    max_price: Range = Field(default_factory=Range)                 # the day's highest price
    turnover_min: float | None = None                               # legacy single minimum (old saved queries)
    currency: list[str] = Field(default_factory=list, max_length=50)
    isin: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("currency")
    @classmethod
    def _currencies(cls, v):
        for c in v:
            if not _CURRENCY.fullmatch(c):
                raise ValueError(f"neispravna valuta {c!r}")
        return v

    @field_validator("isin")
    @classmethod
    def _isins(cls, v):
        for i in v:
            if not _ISIN.fullmatch(i):
                raise ValueError(f"neispravan ISIN {i!r}")
        return v

    @model_validator(mode="after")
    def _dates_ordered(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("datum 'od' je posle datuma 'do'")
        return self
