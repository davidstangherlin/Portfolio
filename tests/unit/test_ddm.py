"""src/valuation/ddm.py - two-stage Dividend Discount Model (Financial
Services / Real Estate - see docs/AS_BUILT.md known-issue #8)."""

from decimal import Decimal

import pytest

from src.valuation.ddm import two_stage_ddm


def test_two_stage_ddm_basic():
    result = two_stage_ddm(
        base_dividend_per_share=Decimal("2.0984"),
        growth_rate=Decimal("0.08"),
        stage1_years=5,
        terminal_growth_rate=Decimal("0.025"),
        discount_rate=Decimal("0.09"),
    )
    assert result.intrinsic_value_per_share == pytest.approx(Decimal("41.81"), abs=Decimal("0.01"))


def test_two_stage_ddm_lower_growth_rate_produces_lower_intrinsic_value():
    # Confirms the DDM's own 5% default growth is genuinely more
    # conservative than reusing the DCF's 8% would be - see
    # docs/AS_BUILT.md §8.6 for why engine.py picks per-model defaults.
    higher_growth = two_stage_ddm(Decimal("2.0984"), growth_rate=Decimal("0.08"))
    lower_growth = two_stage_ddm(Decimal("2.0984"), growth_rate=Decimal("0.05"))
    assert lower_growth.intrinsic_value_per_share < higher_growth.intrinsic_value_per_share
    assert lower_growth.intrinsic_value_per_share == pytest.approx(Decimal("36.84"), abs=Decimal("0.01"))


@pytest.mark.parametrize("dividend", [Decimal("0"), Decimal("-1.00"), None])
def test_two_stage_ddm_none_for_zero_negative_or_missing_dividend(dividend):
    # No dividend to discount (or a nonsensical negative one) -> None,
    # not a fabricated intrinsic value. A non-dividend-paying Financial
    # Services/Real Estate company correctly gets no DDM result at all.
    result = two_stage_ddm(dividend)
    assert result.intrinsic_value_per_share is None


def test_two_stage_ddm_rejects_discount_rate_not_exceeding_terminal_growth():
    with pytest.raises(ValueError):
        two_stage_ddm(
            Decimal("2.00"),
            terminal_growth_rate=Decimal("0.09"),
            discount_rate=Decimal("0.09"),
        )


def test_two_stage_ddm_no_cash_debt_netting_unlike_dcf():
    # Unlike two_stage_dcf, the DDM takes no shares_outstanding or
    # cash/debt arguments at all - it's already a per-share figure,
    # since dividends are paid out of post-tax, post-financing earnings.
    # This test exists to catch an accidental signature regression that
    # would silently reintroduce double-counting if those params were
    # ever added back.
    import inspect

    from src.valuation.ddm import two_stage_ddm as fn

    params = set(inspect.signature(fn).parameters)
    assert "shares_outstanding" not in params
    assert "cash_and_equivalents" not in params
    assert "total_debt" not in params
