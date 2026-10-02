"""src/valuation/graham.py - Graham Number."""

from decimal import Decimal

import pytest

from src.valuation.graham import book_value_per_share, graham_number


def test_graham_number_basic():
    # sqrt(22.5 * 2.00 * 10.00) = sqrt(450) = 21.2132...
    result = graham_number(Decimal("2.00"), Decimal("10.00"))
    assert result == pytest.approx(Decimal("21.2132"), abs=Decimal("0.0001"))


@pytest.mark.parametrize("eps,bvps", [
    (Decimal("-1.00"), Decimal("10.00")),
    (Decimal("2.00"), Decimal("-10.00")),
    (Decimal("0"), Decimal("10.00")),
    (Decimal("2.00"), Decimal("0")),
    (None, Decimal("10.00")),
    (Decimal("2.00"), None),
])
def test_graham_number_undefined_cases_return_none(eps, bvps):
    # Graham's method is explicitly undefined for loss-making or
    # negative-equity companies - None, not a fabricated or complex number.
    assert graham_number(eps, bvps) is None


def test_book_value_per_share_basic():
    assert book_value_per_share(Decimal("1000000"), Decimal("500000")) == Decimal("2.00")


def test_book_value_per_share_none_when_no_shares_outstanding():
    assert book_value_per_share(Decimal("1000000"), None) is None
    assert book_value_per_share(Decimal("1000000"), Decimal("0")) is None
    assert book_value_per_share(Decimal("1000000"), Decimal("-5")) is None


def test_book_value_per_share_none_when_no_equity():
    assert book_value_per_share(None, Decimal("500000")) is None
    assert book_value_per_share(Decimal("0"), Decimal("500000")) is None
