"""Australian capital gains tax arithmetic for share parcels.

A record-keeping aid, not tax advice. It implements the parts of the ATO
rules that follow mechanically from your trade records:

- Cost base = units x buy price + buy brokerage.
- Capital proceeds = units x sell price - sell brokerage.
- The CGT discount needs the parcel held for at least 12 months, excluding
  the day of acquisition and the day of disposal - so a sale qualifies only
  if it's after the first anniversary of the purchase date.
- Capital losses are applied to non-discountable gains first (the order
  most favourable to an individual), then the discount is applied to what
  remains of the discountable gains.

The 50% rate is for individuals and trusts; complying super funds get
33 1/3% and companies none. Prior-year carried-forward losses, dividend
income and franking credits are not tracked here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CGT_DISCOUNT_RATE = Decimal("0.5")
CENTS = Decimal("0.01")


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def cgt_discount_date(buy_date: date) -> date:
    """The first anniversary of the purchase; a sale strictly after this
    date is discount-eligible. A 29 February purchase anniversaries on 28
    February in a non-leap year."""
    try:
        return buy_date.replace(year=buy_date.year + 1)
    except ValueError:
        return date(buy_date.year + 1, 2, 28)


def discount_eligible_from(buy_date: date) -> date:
    """The first sale date that qualifies for the CGT discount."""
    return cgt_discount_date(buy_date) + timedelta(days=1)


def is_discount_eligible(buy_date: date, sell_date: date) -> bool:
    return sell_date > cgt_discount_date(buy_date)


def cost_base(units: Decimal, buy_price: Decimal, buy_brokerage: Decimal) -> Decimal:
    return to_cents(units * buy_price + buy_brokerage)


def capital_proceeds(units: Decimal, sell_price: Decimal, sell_brokerage: Decimal) -> Decimal:
    return to_cents(units * sell_price - sell_brokerage)


def financial_year(d: date) -> str:
    """Australian financial year label, e.g. 15 Aug 2025 -> '2025-26'."""
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


@dataclass(frozen=True)
class RealisedGain:
    asx_code: str
    units: Decimal
    buy_date: date
    sell_date: date
    cost_base: Decimal
    proceeds: Decimal
    discount_eligible: bool

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost_base


@dataclass(frozen=True)
class CgtSummary:
    financial_year: str
    discountable_gains: Decimal
    non_discountable_gains: Decimal
    capital_losses: Decimal
    net_capital_gain: Decimal  # what would go on the tax return, before any carried-forward losses
    unused_losses: Decimal  # losses left over to carry forward


def summarise(financial_year_label: str, gains: list[RealisedGain]) -> CgtSummary:
    discountable = sum((g.gain for g in gains if g.gain > 0 and g.discount_eligible), Decimal("0"))
    non_discountable = sum((g.gain for g in gains if g.gain > 0 and not g.discount_eligible), Decimal("0"))
    losses = sum((-g.gain for g in gains if g.gain < 0), Decimal("0"))

    remaining_losses = losses
    applied = min(remaining_losses, non_discountable)
    non_discountable_after = non_discountable - applied
    remaining_losses -= applied

    applied = min(remaining_losses, discountable)
    discountable_after = discountable - applied
    remaining_losses -= applied

    net = non_discountable_after + discountable_after * (1 - CGT_DISCOUNT_RATE)
    return CgtSummary(
        financial_year=financial_year_label,
        discountable_gains=to_cents(discountable),
        non_discountable_gains=to_cents(non_discountable),
        capital_losses=to_cents(losses),
        net_capital_gain=to_cents(net),
        unused_losses=to_cents(remaining_losses),
    )
