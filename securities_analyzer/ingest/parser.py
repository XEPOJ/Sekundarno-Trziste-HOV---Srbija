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
        coupon_pct=0.0 if c[6] == "-" else float(c[6]),  # NBS prints "-" for zero-coupon bills
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
