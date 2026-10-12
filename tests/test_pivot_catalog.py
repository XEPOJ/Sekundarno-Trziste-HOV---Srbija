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
