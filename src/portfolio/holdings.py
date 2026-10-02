"""Parcel-level record keeping against the `holdings` table (db/schema.sql)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from src.models import Company, DailyPrice, Holding
from src.portfolio import cgt

ACQUISITION_METHODS = ("PURCHASE", "DRP", "BONUS", "TRANSFER", "OTHER")
SELL_ORDERS = ("fifo", "min-tax")


class HoldingsError(ValueError):
    pass


def add_parcel(
    session: Session,
    asx_code: str,
    units: Decimal,
    buy_price: Decimal,
    buy_date: date,
    buy_brokerage: Decimal = Decimal("0"),
    acquisition_method: str = "PURCHASE",
    broker: str | None = None,
    notes: str | None = None,
) -> Holding:
    if units <= 0:
        raise HoldingsError("units must be greater than zero")
    if buy_price < 0 or buy_brokerage < 0:
        raise HoldingsError("price and brokerage can't be negative")
    acquisition_method = acquisition_method.upper()
    if acquisition_method not in ACQUISITION_METHODS:
        raise HoldingsError(f"method must be one of {', '.join(ACQUISITION_METHODS)}")

    parcel = Holding(
        asx_code=asx_code.strip().upper(), units=units, buy_price=buy_price, buy_date=buy_date,
        buy_brokerage=buy_brokerage, acquisition_method=acquisition_method, broker=broker, notes=notes,
    )
    session.add(parcel)
    session.flush()
    return parcel


def open_parcels(session: Session, asx_code: str | None = None) -> list[Holding]:
    stmt = select(Holding).where(Holding.sell_date.is_(None))
    if asx_code:
        stmt = stmt.where(Holding.asx_code == asx_code.strip().upper())
    stmt = stmt.order_by(Holding.asx_code, Holding.buy_date, Holding.created_at)
    return list(session.execute(stmt).scalars())


def sold_parcels(session: Session) -> list[Holding]:
    stmt = select(Holding).where(Holding.sell_date.is_not(None)).order_by(Holding.sell_date, Holding.asx_code)
    return list(session.execute(stmt).scalars())


def find_parcel(session: Session, id_prefix: str) -> Holding:
    """Look a parcel up by its ID or any unique leading part of it (the
    8-character short ID `portfolio.py list` shows)."""
    stmt = select(Holding).where(cast(Holding.holding_id, String).like(f"{id_prefix.strip().lower()}%"))
    matches = list(session.execute(stmt).scalars())
    if not matches:
        raise HoldingsError(f"no parcel with ID starting {id_prefix!r}")
    if len(matches) > 1:
        raise HoldingsError(f"{id_prefix!r} matches {len(matches)} parcels - use more of the ID")
    return matches[0]


def _cost_per_unit(parcel: Holding) -> Decimal:
    return (parcel.units * parcel.buy_price + parcel.buy_brokerage) / parcel.units


def _sale_order(parcels: list[Holding], order: str, sell_price: Decimal, sell_date: date) -> list[Holding]:
    if order == "fifo":
        return sorted(parcels, key=lambda p: (p.buy_date, p.created_at))

    # min-tax: sell the parcels that produce the least taxable gain first.
    # A discount-eligible gain is only half taxable, so it can beat a
    # smaller gain that isn't eligible; losses (negative) sort first.
    def taxable_gain_per_unit(p: Holding) -> Decimal:
        gain = sell_price - _cost_per_unit(p)
        if gain > 0 and cgt.is_discount_eligible(p.buy_date, sell_date):
            gain *= 1 - cgt.CGT_DISCOUNT_RATE
        return gain

    return sorted(parcels, key=lambda p: (taxable_gain_per_unit(p), p.buy_date))


def sell(
    session: Session,
    asx_code: str,
    units: Decimal,
    sell_price: Decimal,
    sell_date: date,
    sell_brokerage: Decimal = Decimal("0"),
    order: str = "fifo",
    parcel_id: str | None = None,
) -> list[Holding]:
    """Record a sale, consuming open parcels in `order` (or one specific
    parcel). A partly-sold parcel is split: the sold portion becomes a new
    row pointing back via split_from_id, and buy brokerage is apportioned
    by units so the combined cost base is unchanged. Sale brokerage is
    apportioned across the parcels sold. Returns the sold rows."""
    if units <= 0:
        raise HoldingsError("units must be greater than zero")
    if sell_price < 0 or sell_brokerage < 0:
        raise HoldingsError("price and brokerage can't be negative")
    if order not in SELL_ORDERS:
        raise HoldingsError(f"order must be one of {', '.join(SELL_ORDERS)}")

    code = asx_code.strip().upper()
    if parcel_id:
        parcel = find_parcel(session, parcel_id)
        if parcel.asx_code != code or not parcel.is_open:
            raise HoldingsError(f"parcel {parcel_id} isn't an open {code} parcel")
        candidates = [parcel]
    else:
        candidates = open_parcels(session, code)
    candidates = [p for p in candidates if p.buy_date <= sell_date]

    available = sum((p.units for p in candidates), Decimal("0"))
    if available < units:
        raise HoldingsError(
            f"only {available.normalize():f} units of {code} held on {sell_date}, can't sell {units.normalize():f}"
        )

    takes: list[tuple[Holding, Decimal]] = []
    remaining = units
    for parcel in _sale_order(candidates, order, sell_price, sell_date):
        if remaining <= 0:
            break
        take = min(remaining, parcel.units)
        takes.append((parcel, take))
        remaining -= take

    sold: list[Holding] = []
    brokerage_left = sell_brokerage
    for i, (parcel, take) in enumerate(takes):
        if i == len(takes) - 1:
            brokerage_share = brokerage_left
        else:
            brokerage_share = cgt.to_cents(sell_brokerage * take / units)
            brokerage_left -= brokerage_share

        if take == parcel.units:
            parcel.sell_date, parcel.sell_price, parcel.sell_brokerage = sell_date, sell_price, brokerage_share
            sold.append(parcel)
            continue

        buy_brokerage_share = cgt.to_cents(parcel.buy_brokerage * take / parcel.units)
        sold_portion = Holding(
            asx_code=parcel.asx_code, units=take, acquisition_method=parcel.acquisition_method,
            buy_date=parcel.buy_date, buy_price=parcel.buy_price, buy_brokerage=buy_brokerage_share,
            sell_date=sell_date, sell_price=sell_price, sell_brokerage=brokerage_share,
            broker=parcel.broker, notes=parcel.notes, split_from_id=parcel.holding_id,
        )
        parcel.units -= take
        parcel.buy_brokerage -= buy_brokerage_share
        session.add(sold_portion)
        sold.append(sold_portion)

    session.flush()
    return sold


def delete_parcel(session: Session, id_prefix: str) -> Holding:
    parcel = find_parcel(session, id_prefix)
    session.delete(parcel)
    session.flush()
    return parcel


def realised_gain(parcel: Holding) -> cgt.RealisedGain:
    return cgt.RealisedGain(
        asx_code=parcel.asx_code,
        units=parcel.units,
        buy_date=parcel.buy_date,
        sell_date=parcel.sell_date,
        cost_base=cgt.cost_base(parcel.units, parcel.buy_price, parcel.buy_brokerage),
        proceeds=cgt.capital_proceeds(parcel.units, parcel.sell_price, parcel.sell_brokerage or Decimal("0")),
        discount_eligible=cgt.is_discount_eligible(parcel.buy_date, parcel.sell_date),
    )


def latest_prices(session: Session, asx_codes: set[str]) -> dict[str, Decimal]:
    """Most recent close for each code that's in the companies table."""
    if not asx_codes:
        return {}
    stmt = (
        select(Company.asx_code, DailyPrice.close_price)
        .join(DailyPrice, DailyPrice.company_id == Company.company_id)
        .where(Company.asx_code.in_(asx_codes))
        .order_by(Company.asx_code, DailyPrice.price_date.desc())
        .distinct(Company.asx_code)
    )
    return {code: price for code, price in session.execute(stmt)}


@dataclass(frozen=True)
class PositionSummary:
    asx_code: str
    units: Decimal
    cost_base: Decimal
    next_discount_date: date | None  # earliest date a still-pending parcel becomes CGT-discount eligible
    units_pending_discount: Decimal  # units reaching eligibility on next_discount_date

    @property
    def average_cost(self) -> Decimal:
        return self.cost_base / self.units


def position_summaries(session: Session, today: date) -> dict[str, PositionSummary]:
    by_code: dict[str, list[Holding]] = defaultdict(list)
    for parcel in open_parcels(session):
        by_code[parcel.asx_code].append(parcel)

    summaries = {}
    for code, parcels in by_code.items():
        pending = [p for p in parcels if not cgt.is_discount_eligible(p.buy_date, today)]
        next_date = min((cgt.discount_eligible_from(p.buy_date) for p in pending), default=None)
        summaries[code] = PositionSummary(
            asx_code=code,
            units=sum((p.units for p in parcels), Decimal("0")),
            cost_base=sum((cgt.cost_base(p.units, p.buy_price, p.buy_brokerage) for p in parcels), Decimal("0")),
            next_discount_date=next_date,
            units_pending_discount=sum(
                (p.units for p in pending if cgt.discount_eligible_from(p.buy_date) == next_date), Decimal("0")
            ),
        )
    return summaries
