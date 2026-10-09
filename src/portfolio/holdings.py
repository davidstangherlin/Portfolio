"""Parcel-level record keeping against the `holdings` and `portfolios`
tables (db/schema.sql, docs/AS_BUILT.md §19).

Every parcel belongs to a portfolio. Functions that take an optional
portfolio use the only active one when none is given, creating "My
portfolio" on first use, and refuse to guess when there are several.

Everything here is scoped to the current user (src/accounts.py, §33): a
portfolio or parcel belonging to someone else is simply not found."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from src.accounts import current_user_id
from src.models import Company, DailyPrice, Holding, Portfolio
from src.portfolio import cgt

ACQUISITION_METHODS = ("PURCHASE", "DRP", "BONUS", "TRANSFER", "OTHER")
SELL_ORDERS = ("fifo", "min-tax")


DEFAULT_PORTFOLIO_NAME = "My portfolio"
MAX_PORTFOLIO_NAME = 60


class HoldingsError(ValueError):
    pass


# ---------- portfolios ----------

def _mine(session: Session):
    """The condition for the current user's portfolios."""
    return Portfolio.owner_id == current_user_id(session)


def owned_portfolio_ids(session: Session):
    """The current user's portfolio IDs, as a subquery for parcel queries."""
    return select(Portfolio.portfolio_id).where(_mine(session)).scalar_subquery()


def get_portfolio(session: Session, portfolio_id) -> Portfolio | None:
    """One of the current user's portfolios by ID, or None."""
    try:
        key = uuid.UUID(str(portfolio_id))
    except ValueError:
        return None
    found = session.get(Portfolio, key)
    return found if found is not None and found.owner_id == current_user_id(session) else None


def list_portfolios(session: Session, include_archived: bool = True) -> list[Portfolio]:
    """Active portfolios first, then archived; oldest first within each."""
    stmt = select(Portfolio).where(_mine(session))
    if not include_archived:
        stmt = stmt.where(Portfolio.archived_at.is_(None))
    stmt = stmt.order_by(Portfolio.archived_at.is_not(None), Portfolio.created_at, Portfolio.name)
    return list(session.execute(stmt).scalars())


def find_portfolio(session: Session, key: str) -> Portfolio:
    """A portfolio by its ID or its name (not case-sensitive)."""
    key = key.strip()
    found = get_portfolio(session, key) or session.execute(
        select(Portfolio).where(_mine(session), func.lower(Portfolio.name) == key.lower())).scalar_one_or_none()
    if found is None:
        names = ", ".join(p.name for p in list_portfolios(session)) or "none yet"
        raise HoldingsError(f"no portfolio called {key!r} (portfolios: {names})")
    return found


def default_portfolio(session: Session) -> Portfolio:
    """The only active portfolio, creating "My portfolio" if there are none."""
    active = list_portfolios(session, include_archived=False)
    if len(active) == 1:
        return active[0]
    if not active:
        return create_portfolio(session, DEFAULT_PORTFOLIO_NAME)
    raise HoldingsError(f"you have {len(active)} portfolios, so say which one: {', '.join(p.name for p in active)}")


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HoldingsError("a portfolio needs a name")
    if len(name) > MAX_PORTFOLIO_NAME:
        raise HoldingsError(f"portfolio names can be at most {MAX_PORTFOLIO_NAME} characters")
    return name


def _check_tax_type(tax_type: str) -> str:
    tax_type = (tax_type or "").strip().upper()
    if tax_type not in cgt.TAX_TYPES:
        raise HoldingsError(f"tax type must be one of {', '.join(cgt.TAX_TYPES)}")
    return tax_type


def _check_unique(session: Session, name: str, except_id=None) -> None:
    clash = session.execute(
        select(Portfolio).where(_mine(session), func.lower(Portfolio.name) == name.lower())).scalar_one_or_none()
    if clash is not None and clash.portfolio_id != except_id:
        raise HoldingsError(f"there is already a portfolio called {clash.name!r}")


def create_portfolio(session: Session, name: str, tax_type: str = "INDIVIDUAL") -> Portfolio:
    name = _clean_name(name)
    _check_unique(session, name)
    portfolio = Portfolio(name=name, tax_type=_check_tax_type(tax_type), owner_id=current_user_id(session))
    session.add(portfolio)
    session.flush()
    return portfolio


def update_portfolio(session: Session, portfolio: Portfolio, name: str | None = None,
                     tax_type: str | None = None) -> Portfolio:
    """Rename, or change the tax type. A new tax type changes the CGT
    discount on every sale already recorded in the portfolio's reports."""
    if name is not None:
        name = _clean_name(name)
        _check_unique(session, name, except_id=portfolio.portfolio_id)
        portfolio.name = name
    if tax_type is not None:
        portfolio.tax_type = _check_tax_type(tax_type)
    session.flush()
    return portfolio


def _count(session: Session, portfolio: Portfolio, sold: bool) -> int:
    condition = Holding.sell_date.is_not(None) if sold else Holding.sell_date.is_(None)
    return session.execute(
        select(func.count()).where(Holding.portfolio_id == portfolio.portfolio_id, condition)
    ).scalar_one()


def archive_portfolio(session: Session, portfolio: Portfolio, now: datetime | None = None) -> Portfolio:
    """Retire a portfolio whose shares have all been sold, keeping its sale
    records (the ATO expects them kept for five years after each sale)."""
    open_count = _count(session, portfolio, sold=False)
    if open_count:
        raise HoldingsError(f"{portfolio.name} still holds {open_count} open parcel(s): sell or move them before archiving")
    portfolio.archived_at = now or datetime.now(timezone.utc)
    session.flush()
    return portfolio


def unarchive_portfolio(session: Session, portfolio: Portfolio) -> Portfolio:
    portfolio.archived_at = None
    session.flush()
    return portfolio


def delete_portfolio(session: Session, portfolio: Portfolio) -> int:
    """Delete a portfolio and its open parcels. Refused once it has any
    sales, because those are tax records: archive it instead. Returns the
    number of parcels deleted."""
    sold_count = _count(session, portfolio, sold=True)
    if sold_count:
        raise HoldingsError(f"{portfolio.name} has {sold_count} sale record(s), which are kept for tax: archive it instead")
    parcels = list(session.execute(select(Holding).where(Holding.portfolio_id == portfolio.portfolio_id)).scalars())
    for parcel in parcels:
        session.delete(parcel)
    session.flush()
    session.delete(portfolio)
    session.flush()
    return len(parcels)


def discount_rate(portfolio: Portfolio) -> Decimal:
    return cgt.DISCOUNT_RATES[portfolio.tax_type]


def _writable(session: Session, portfolio: Portfolio | None) -> Portfolio:
    portfolio = portfolio or default_portfolio(session)
    if portfolio.owner_id != current_user_id(session):
        raise HoldingsError("no such portfolio")
    if portfolio.is_archived:
        raise HoldingsError(f"{portfolio.name} is archived: unarchive it before recording trades")
    return portfolio


# ---------- parcels ----------


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
    portfolio: Portfolio | None = None,
) -> Holding:
    if units <= 0:
        raise HoldingsError("units must be greater than zero")
    if buy_price < 0 or buy_brokerage < 0:
        raise HoldingsError("price and brokerage can't be negative")
    acquisition_method = acquisition_method.upper()
    if acquisition_method not in ACQUISITION_METHODS:
        raise HoldingsError(f"method must be one of {', '.join(ACQUISITION_METHODS)}")

    portfolio = _writable(session, portfolio)
    parcel = Holding(
        portfolio_id=portfolio.portfolio_id, asx_code=asx_code.strip().upper(), units=units, buy_price=buy_price, buy_date=buy_date,
        buy_brokerage=buy_brokerage, acquisition_method=acquisition_method, broker=broker, notes=notes,
    )
    session.add(parcel)
    session.flush()
    return parcel


def open_parcels(session: Session, asx_code: str | None = None, portfolio_id=None) -> list[Holding]:
    stmt = select(Holding).where(Holding.sell_date.is_(None), Holding.portfolio_id.in_(owned_portfolio_ids(session)))
    if portfolio_id is not None:
        stmt = stmt.where(Holding.portfolio_id == portfolio_id)
    if asx_code:
        stmt = stmt.where(Holding.asx_code == asx_code.strip().upper())
    stmt = stmt.order_by(Holding.asx_code, Holding.buy_date, Holding.created_at)
    return list(session.execute(stmt).scalars())


def sold_parcels(session: Session, portfolio_id=None) -> list[Holding]:
    stmt = select(Holding).where(Holding.sell_date.is_not(None), Holding.portfolio_id.in_(owned_portfolio_ids(session)))
    if portfolio_id is not None:
        stmt = stmt.where(Holding.portfolio_id == portfolio_id)
    stmt = stmt.order_by(Holding.sell_date, Holding.asx_code)
    return list(session.execute(stmt).scalars())


def find_parcel(session: Session, id_prefix: str) -> Holding:
    """Look a parcel up by its ID or any unique leading part of it (the
    8-character short ID `portfolio.py list` shows)."""
    stmt = select(Holding).where(cast(Holding.holding_id, String).like(f"{id_prefix.strip().lower()}%"),
                                 Holding.portfolio_id.in_(owned_portfolio_ids(session)))
    matches = list(session.execute(stmt).scalars())
    if not matches:
        raise HoldingsError(f"no parcel with ID starting {id_prefix!r}")
    if len(matches) > 1:
        raise HoldingsError(f"{id_prefix!r} matches {len(matches)} parcels - use more of the ID")
    return matches[0]


def _cost_per_unit(parcel: Holding) -> Decimal:
    return (parcel.units * parcel.buy_price + parcel.buy_brokerage) / parcel.units


def _sale_order(parcels: list[Holding], order: str, sell_price: Decimal, sell_date: date,
                rate: Decimal = cgt.CGT_DISCOUNT_RATE) -> list[Holding]:
    if order == "fifo":
        return sorted(parcels, key=lambda p: (p.buy_date, p.created_at))

    # min-tax: sell the parcels that produce the least taxable gain first.
    # A discount-eligible gain is only partly taxable (half, for an
    # individual), so it can beat a smaller gain that isn't eligible;
    # losses (negative) sort first.
    def taxable_gain_per_unit(p: Holding) -> Decimal:
        gain = sell_price - _cost_per_unit(p)
        if gain > 0 and cgt.is_discount_eligible(p.buy_date, sell_date):
            gain *= 1 - rate
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
    portfolio: Portfolio | None = None,
) -> list[Holding]:
    """Record a sale, consuming open parcels in `order` (or one specific
    parcel). A partly-sold parcel is split: the sold portion becomes a new
    row pointing back via split_from_id, and buy brokerage is apportioned
    by units so the combined cost base is unchanged. Sale brokerage is
    apportioned across the parcels sold. Only the portfolio's own parcels
    are sold. Returns the sold rows."""
    if units <= 0:
        raise HoldingsError("units must be greater than zero")
    if sell_price < 0 or sell_brokerage < 0:
        raise HoldingsError("price and brokerage can't be negative")
    if order not in SELL_ORDERS:
        raise HoldingsError(f"order must be one of {', '.join(SELL_ORDERS)}")

    code = asx_code.strip().upper()
    if parcel_id:
        parcel = find_parcel(session, parcel_id)
        portfolio = portfolio or session.get(Portfolio, parcel.portfolio_id)
        if parcel.asx_code != code or not parcel.is_open or parcel.portfolio_id != portfolio.portfolio_id:
            raise HoldingsError(f"parcel {parcel_id} isn't an open {code} parcel in {portfolio.name}")
    portfolio = _writable(session, portfolio)
    if parcel_id:
        candidates = [parcel]
    else:
        candidates = open_parcels(session, code, portfolio.portfolio_id)
    candidates = [p for p in candidates if p.buy_date <= sell_date]

    available = sum((p.units for p in candidates), Decimal("0"))
    if available < units:
        raise HoldingsError(
            f"only {available.normalize():f} units of {code} held in {portfolio.name} on {sell_date}, "
            f"can't sell {units.normalize():f}"
        )

    takes: list[tuple[Holding, Decimal]] = []
    remaining = units
    for parcel in _sale_order(candidates, order, sell_price, sell_date, discount_rate(portfolio)):
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
            portfolio_id=parcel.portfolio_id, asx_code=parcel.asx_code, units=take, acquisition_method=parcel.acquisition_method,
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


def undo_sale(session: Session, id_prefix: str) -> Holding:
    """Reverse a sale recorded by mistake. A sold portion split off a
    parcel that is still open goes back into it (units and buy brokerage
    restored); otherwise the parcel simply becomes open again. Returns the
    open parcel."""
    parcel = find_parcel(session, id_prefix)
    if parcel.is_open:
        raise HoldingsError("that parcel hasn't been sold")
    _writable(session, session.get(Portfolio, parcel.portfolio_id))
    original = session.get(Holding, parcel.split_from_id) if parcel.split_from_id else None
    if original is not None and original.is_open:
        original.units += parcel.units
        original.buy_brokerage += parcel.buy_brokerage
        session.delete(parcel)
        session.flush()
        return original
    parcel.sell_date = parcel.sell_price = parcel.sell_brokerage = None
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


def position_summaries(session: Session, today: date, portfolio_id=None) -> dict[str, PositionSummary]:
    """Open units per company, across every portfolio unless one is given.
    The CGT discount date only counts parcels in portfolios that get a
    discount (not companies)."""
    no_discount = {p.portfolio_id for p in list_portfolios(session) if discount_rate(p) == 0}
    by_code: dict[str, list[Holding]] = defaultdict(list)
    for parcel in open_parcels(session, portfolio_id=portfolio_id):
        by_code[parcel.asx_code].append(parcel)

    summaries = {}
    for code, parcels in by_code.items():
        pending = [p for p in parcels
                   if p.portfolio_id not in no_discount and not cgt.is_discount_eligible(p.buy_date, today)]
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
