"""src/valuation/dcf.py - two-stage DCF and the margin-of-safety sanity cap."""

from decimal import Decimal

import pytest

from src.valuation.dcf import margin_of_safety_percent, two_stage_dcf


def test_two_stage_dcf_basic():
    result = two_stage_dcf(
        base_fcf=Decimal("1000000"),
        shares_outstanding=Decimal("1000000"),
        cash_and_equivalents=Decimal("500000"),
        total_debt=Decimal("200000"),
        growth_rate=Decimal("0.08"),
        stage1_years=5,
        terminal_growth_rate=Decimal("0.025"),
        discount_rate=Decimal("0.09"),
    )
    assert result.equity_value == pytest.approx(Decimal("20223080.14"), abs=Decimal("0.01"))
    assert result.intrinsic_value_per_share == pytest.approx(Decimal("20.22"), abs=Decimal("0.01"))


def test_two_stage_dcf_no_shares_outstanding_returns_equity_value_only():
    # Equity value is still computed (useful for debugging/logging), but
    # intrinsic_value_per_share can't be derived without a share count -
    # None, not a divide-by-zero crash.
    result = two_stage_dcf(base_fcf=Decimal("1000000"), shares_outstanding=None)
    assert result.equity_value is not None
    assert result.intrinsic_value_per_share is None


def test_two_stage_dcf_zero_shares_outstanding_returns_none_per_share():
    result = two_stage_dcf(base_fcf=Decimal("1000000"), shares_outstanding=Decimal("0"))
    assert result.intrinsic_value_per_share is None


def test_two_stage_dcf_rejects_discount_rate_not_exceeding_terminal_growth():
    # The Gordon Growth perpetuity formula diverges (or goes negative)
    # unless discount_rate > terminal_growth_rate - must raise, not return
    # a silently wrong number.
    with pytest.raises(ValueError):
        two_stage_dcf(
            base_fcf=Decimal("1000000"),
            shares_outstanding=Decimal("1000000"),
            terminal_growth_rate=Decimal("0.09"),
            discount_rate=Decimal("0.09"),
        )


def test_margin_of_safety_percent_basic():
    assert margin_of_safety_percent(Decimal("10.00"), Decimal("8.00")) == Decimal("20.0")


@pytest.mark.parametrize("intrinsic,price", [
    (Decimal("10.00"), None),
    (None, Decimal("8.00")),
    (Decimal("-5.00"), Decimal("8.00")),
    (Decimal("0"), Decimal("8.00")),
])
def test_margin_of_safety_percent_none_for_unusable_inputs(intrinsic, price):
    assert margin_of_safety_percent(intrinsic, price) is None


def test_margin_of_safety_percent_sanity_cap_on_near_zero_intrinsic_value():
    # Regression for docs/AS_BUILT.md known-issue #12: a micro-cap with a
    # near-zero DCF intrinsic value (bad shares-outstanding estimate)
    # produced a -128,521.87% "margin of safety" that overflowed
    # NUMERIC(6,2) and crashed run_valuation --all before this guard
    # existed. A $0.01 intrinsic value against a $100 price is the same
    # shape of failure - must return None, not a NUMERIC(6,2)-busting number.
    result = margin_of_safety_percent(Decimal("0.01"), Decimal("100.00"))
    assert result is None


def test_margin_of_safety_percent_just_under_sanity_threshold_is_not_capped():
    # -4900% should still pass through - only magnitude > 5000% is capped.
    result = margin_of_safety_percent(Decimal("100.00"), Decimal("5000.00"))
    assert result == Decimal("-4900")
