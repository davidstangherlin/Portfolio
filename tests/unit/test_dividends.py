"""src/valuation/dividends.py - grossed-up (franked) dividend yield."""

from decimal import Decimal

import pytest

from src.valuation.dividends import dividend_yields, gross_dividend


def test_gross_dividend_fully_franked_standard_rate():
    # $1.00 DPS, 100% franked, 30% corporate tax -> franking credit = $0.30/0.70 = $0.4286
    result = gross_dividend(Decimal("1.00"), Decimal("1.0"), Decimal("0.30"))
    assert result == pytest.approx(Decimal("1.428571"), abs=Decimal("0.000001"))


def test_gross_dividend_unfranked_equals_cash_dividend():
    result = gross_dividend(Decimal("1.00"), Decimal("0"), Decimal("0.30"))
    assert result == Decimal("1.00")


def test_gross_dividend_rejects_invalid_tax_rate():
    with pytest.raises(ValueError):
        gross_dividend(Decimal("1.00"), Decimal("1.0"), Decimal("1.0"))


def test_dividend_yields_whole_number_percentages_from_db():
    # Exercises the documented /100 conversion: financial_reports stores
    # 100.0/30.0 (whole-number percentages), not 1.0/0.30 (fractions) -
    # this is the single most important formula detail per docs/AS_BUILT.md §8.1.
    yields = dividend_yields(
        dividend_per_share=Decimal("0.70"),
        price=Decimal("10.00"),
        franking_percentage=Decimal("100.0"),
        corporate_tax_rate=Decimal("30.0"),
    )
    assert yields.uncapped_dividend_yield == Decimal("7.00")
    assert yields.grossed_up_dividend_yield == pytest.approx(Decimal("10.00"), abs=Decimal("0.01"))


def test_dividend_yields_none_when_no_dividend():
    yields = dividend_yields(None, Decimal("10.00"), Decimal("100.0"), Decimal("30.0"))
    assert yields.uncapped_dividend_yield is None
    assert yields.grossed_up_dividend_yield is None


def test_dividend_yields_none_when_price_zero_or_missing():
    assert dividend_yields(Decimal("0.50"), Decimal("0"), Decimal("100.0"), Decimal("30.0")).uncapped_dividend_yield is None
    assert dividend_yields(Decimal("0.50"), None, Decimal("100.0"), Decimal("30.0")).uncapped_dividend_yield is None


def test_dividend_yields_defaults_missing_franking_and_tax_rate():
    # franking_percentage=None -> treated as 0% franked (no credit);
    # corporate_tax_rate=None -> defaults to the standard 30%.
    yields = dividend_yields(Decimal("1.00"), Decimal("10.00"), None, None)
    assert yields.uncapped_dividend_yield == Decimal("10.00")
    assert yields.grossed_up_dividend_yield == Decimal("10.00")  # 0% franked -> grossed == uncapped


def test_dividend_yields_twr_special_dividend_case():
    # Real case from docs/AS_BUILT.md §8.1: TWR's FY2025 dividend
    # ($1.1930/share, fully franked) produced a 106.85% grossed-up yield
    # against its then price - a special dividend, not sustainable income
    # (it was 519% of that year's EPS - see test_engine_payout_ratio_twr_case).
    # Price back-computed from the documented 106.85% figure and pinned
    # here as a regression, not independently sourced.
    yields = dividend_yields(
        dividend_per_share=Decimal("1.1930"),
        price=Decimal("1.595026405508389598235176149"),
        franking_percentage=Decimal("100.0"),
        corporate_tax_rate=Decimal("30.0"),
    )
    assert yields.grossed_up_dividend_yield == pytest.approx(Decimal("106.85"), abs=Decimal("0.01"))
