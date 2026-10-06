"""ETF total returns and trailing distributions (src/etf/performance.py)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.etf.performance import History, growth, month_end, returns_as_at, trailing_distributions


def weekdays(start: date, end: date, price) -> History:
    """A close every weekday; `price(day)` gives each close."""
    dates, d = [], start
    while d <= end:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return History(dates, [price(x) for x in dates], [])


def test_price_only_growth():
    h = History([date(2026, 1, 2), date(2026, 2, 2)], [10.0, 11.0], [])
    assert growth(h, date(2026, 1, 2), date(2026, 2, 2)) == pytest.approx(1.1)


def test_distribution_reinvested_at_the_ex_date_close():
    # $1 paid when the price is $10 buys 0.1 units, worth $1.10 at the end.
    h = History([date(2026, 1, 2), date(2026, 1, 15), date(2026, 2, 2)], [10.0, 10.0, 11.0],
                [(date(2026, 1, 15), 1.0)])
    assert growth(h, date(2026, 1, 2), date(2026, 2, 2)) == pytest.approx(1.1 * 11 / 10)


def test_ex_date_without_a_close_uses_the_next_close():
    h = History([date(2026, 1, 2), date(2026, 1, 19), date(2026, 2, 2)], [10.0, 8.0, 8.0],
                [(date(2026, 1, 17), 2.0)])  # a Saturday
    assert growth(h, date(2026, 1, 2), date(2026, 2, 2)) == pytest.approx(1.25 * 8 / 10)


def test_distributions_outside_the_period_are_ignored():
    h = History([date(2026, 1, 2), date(2026, 2, 2)], [10.0, 10.0],
                [(date(2026, 1, 2), 5.0), (date(2026, 3, 1), 5.0)])  # on the start date, and after the end
    assert growth(h, date(2026, 1, 2), date(2026, 2, 2)) == pytest.approx(1.0)


def test_no_close_near_the_start_or_end_means_no_figure():
    h = History([date(2026, 1, 2), date(2026, 3, 2)], [10.0, 12.0], [])
    assert growth(h, date(2025, 12, 1), date(2026, 3, 2)) is None   # younger than the period
    assert growth(h, date(2026, 1, 20), date(2026, 3, 2)) is None   # last close before start is 18 days earlier
    assert growth(h, date(2026, 1, 2), date(2026, 4, 1)) is None    # stale at the end


def test_periods_and_annualising():
    # 10% a year, compounding daily, for just over ten years.
    start = date(2016, 1, 4)
    h = weekdays(start, date(2026, 9, 30), lambda d: 10 * 1.1 ** ((d - start).days / 365.25))
    r = returns_as_at(h, date(2026, 9, 30))
    assert r["return_1y"] == pytest.approx(Decimal("10.0"), abs=Decimal("0.15"))
    for key in ("return_3y", "return_5y", "return_10y", "return_since_inception"):
        assert r[key] == pytest.approx(Decimal("10.0"), abs=Decimal("0.15")), key  # annualised
    assert r["return_1m"] == pytest.approx(Decimal("0.8"), abs=Decimal("0.1"))  # not annualised


def test_young_fund_has_short_periods_only():
    h = weekdays(date(2025, 3, 3), date(2026, 9, 30), lambda d: 20.0)
    r = returns_as_at(h, date(2026, 9, 30))
    assert r["return_1y"] == Decimal("0.00")
    assert r["return_3y"] is None and r["return_5y"] is None and r["return_10y"] is None
    assert r["return_since_inception"] == Decimal("0.00")


def test_since_inception_under_a_year_is_not_annualised():
    h = History([date(2026, 4, 1), date(2026, 9, 30)], [10.0, 12.0], [])
    assert returns_as_at(h, date(2026, 9, 30))["return_since_inception"] == Decimal("20.00")


def test_trailing_distributions_and_yield():
    h = History([date(2026, 9, 30)], [20.0],
                [(date(2025, 9, 30), 9.0), (date(2025, 10, 1), 0.3), (date(2026, 1, 2), 0.3),
                 (date(2026, 4, 1), 0.2), (date(2026, 7, 1), 0.2)])
    total, yield_pct = trailing_distributions(h, date(2026, 9, 30))
    assert total == Decimal("1.0000")        # the one exactly 12 months ago is outside
    assert yield_pct == Decimal("5.00")
    assert trailing_distributions(h, date(2026, 11, 30)) == (None, None)  # no recent close


def test_month_end():
    assert month_end(date(2026, 2, 1)) == date(2026, 2, 28)
    assert month_end(date(2024, 2, 1)) == date(2024, 2, 29)
