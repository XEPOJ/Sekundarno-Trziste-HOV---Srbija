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
