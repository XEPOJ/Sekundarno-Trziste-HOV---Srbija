from dataclasses import dataclass
from datetime import date

EXPECTED_HEADER = [
    "Датум трговања", "Датум салдирања", "Датум доспећа", "ISIN", "Рочност у данима",
    "Валута", "Купонска стопа", "Преостала рочност у данима", "Количина",
    "Број трансакција", "Номинална цена по комаду", "Минимална цена", "Максимална цена",
    "Просечна пондерисана цена", "Укупан промет", "Минимални принос",
    "Максимални принос", "Просечни принос",
]


@dataclass(frozen=True)
class TradeRow:
    trade_date: date
    settlement_date: date
    maturity_date: date
    isin: str
    original_maturity_days: int
    currency: str
    coupon_pct: float
    remaining_maturity_days: int
    quantity: int
    transaction_count: int
    nominal_per_unit: float
    min_price: float
    max_price: float
    wavg_price: float
    turnover: float
    min_yield_pct: float
    max_yield_pct: float
    avg_yield_pct: float

    @property
    def key(self) -> tuple[date, date, str]:
        return (self.trade_date, self.settlement_date, self.isin)
