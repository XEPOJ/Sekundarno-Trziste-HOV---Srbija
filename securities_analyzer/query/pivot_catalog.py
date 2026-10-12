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
