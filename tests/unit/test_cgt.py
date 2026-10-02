"""src/portfolio/cgt.py - Australian CGT arithmetic."""

from datetime import date
from decimal import Decimal

import pytest

from src.portfolio import cgt


@pytest.mark.parametrize("buy,sell,eligible", [
    (date(2025, 1, 1), date(2026, 1, 1), False),  # exactly 12 months - acquisition and disposal days excluded
    (date(2025, 1, 1), date(2026, 1, 2), True),
    (date(2025, 7, 15), date(2025, 12, 31), False),
    (date(2024, 2, 29), date(2025, 2, 28), False),  # leap-day purchase
    (date(2024, 2, 29), date(2025, 3, 1), True),
])
def test_discount_eligibility_boundary(buy, sell, eligible):
    assert cgt.is_discount_eligible(buy, sell) is eligible


def test_discount_eligible_from_is_day_after_anniversary():
    assert cgt.discount_eligible_from(date(2025, 3, 14)) == date(2026, 3, 15)
    assert cgt.discount_eligible_from(date(2024, 2, 29)) == date(2025, 3, 1)


def test_cost_base_includes_brokerage():
    assert cgt.cost_base(Decimal("100"), Decimal("42.50"), Decimal("9.95")) == Decimal("4259.95")


def test_proceeds_net_of_brokerage():
    assert cgt.capital_proceeds(Decimal("100"), Decimal("48.10"), Decimal("9.95")) == Decimal("4800.05")


@pytest.mark.parametrize("d,label", [
    (date(2025, 6, 30), "2024-25"),
    (date(2025, 7, 1), "2025-26"),
    (date(2026, 1, 15), "2025-26"),
    (date(2099, 12, 31), "2099-00"),
])
def test_financial_year(d, label):
    assert cgt.financial_year(d) == label


def _gain(gain: str, eligible: bool) -> cgt.RealisedGain:
    return cgt.RealisedGain(
        asx_code="TST", units=Decimal("1"), buy_date=date(2024, 1, 1), sell_date=date(2025, 8, 1),
        cost_base=Decimal("1000"), proceeds=Decimal("1000") + Decimal(gain), discount_eligible=eligible,
    )


def test_summarise_applies_losses_to_non_discountable_gains_first():
    # $1,000 discountable + $400 non-discountable - $300 loss.
    # Loss wipes $300 of the non-discountable gain first: $100 + $1,000 x 50% = $600.
    s = cgt.summarise("2025-26", [_gain("1000", True), _gain("400", False), _gain("-300", True)])
    assert s.discountable_gains == Decimal("1000.00")
    assert s.non_discountable_gains == Decimal("400.00")
    assert s.capital_losses == Decimal("300.00")
    assert s.net_capital_gain == Decimal("600.00")
    assert s.unused_losses == Decimal("0.00")


def test_summarise_excess_loss_spills_into_discountable_then_carries_forward():
    s = cgt.summarise("2025-26", [_gain("200", False), _gain("300", True), _gain("-600", False)])
    assert s.net_capital_gain == Decimal("0.00")
    assert s.unused_losses == Decimal("100.00")


def test_summarise_discount_only_on_eligible_gains():
    s = cgt.summarise("2025-26", [_gain("1000", True), _gain("1000", False)])
    assert s.net_capital_gain == Decimal("1500.00")
