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
