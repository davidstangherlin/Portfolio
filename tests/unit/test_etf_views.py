"""ETF page helpers (src/etf/views.py, src/etf/performance.py): the growth
index behind "Growth of $10,000", weekly sampling, distributions by
financial year, category averages and the default reference fund."""

from datetime import date
from decimal import Decimal

import pytest

from src.etf.performance import History, growth, growth_index
from src.etf.views import category_averages, default_reference, distributions_by_year, weekly


def test_growth_index_matches_growth_between_any_two_dates():
    h = History([date(2026, 1, 2), date(2026, 1, 15), date(2026, 2, 2), date(2026, 3, 2)], [10.0, 10.0, 11.0, 12.0],
                [(date(2026, 1, 15), 1.0)])
    idx = dict(growth_index(h))
    assert idx[date(2026, 1, 2)] == 10.0
    assert idx[date(2026, 3, 2)] / idx[date(2026, 1, 2)] == pytest.approx(growth(h, date(2026, 1, 2), date(2026, 3, 2)))
    assert idx[date(2026, 3, 2)] / idx[date(2026, 2, 2)] == pytest.approx(12 / 11)  # no distribution in between


def test_weekly_keeps_each_weeks_last_point_and_the_last():
    pts = [(date(2026, 9, d), float(d)) for d in (21, 22, 25, 28, 29)]  # Mon Tue Fri | Mon Tue
    assert weekly(pts) == [(date(2026, 9, 25), 25.0), (date(2026, 9, 29), 29.0)]


def test_distributions_by_financial_year():
    h = History([date(2023, 8, 1)], [10.0], [(date(2024, 1, 2), 0.5), (date(2024, 7, 1), 0.25), (date(2026, 7, 1), 0.3)])
    years = distributions_by_year(h, date(2026, 10, 6))
    assert [y["financial_year"] for y in years] == ["FY24", "FY25", "FY26", "FY27"]  # from the first price's year
    assert [y["amount"] for y in years] == [0.5, 0.25, 0.0, 0.3]
    assert [y["partial"] for y in years] == [False, False, False, True]


def _row(code, category, fum, r1y=None, mer=None):
    return {"asx_code": code, "category": category, "fum_aud": Decimal(fum), "mer_percent": mer,
            "distribution_yield_12m": None, **{k: None for k in ("return_1m", "return_3m", "return_6m", "return_3y",
                                                                  "return_5y", "return_10y", "return_since_inception")},
            "return_1y": r1y}


def test_category_averages_use_only_funds_with_a_figure():
    rows = [_row("A", "Aus", 10, Decimal("10")), _row("B", "Aus", 20, Decimal("20")), _row("C", "Aus", 5),
            _row("D", "Bonds", 5, Decimal("2"))]
    avg = category_averages(rows)
    assert avg["Aus"]["etfs"] == 3 and avg["Aus"]["return_1y"] == Decimal("15.00") and avg["Aus"]["return_1y_n"] == 2
    assert avg["Aus"]["return_5y"] is None
    assert avg["Bonds"]["return_1y"] == Decimal("2.00")


def test_default_reference_is_the_largest_other_fund_in_the_category():
    rows = [_row("A", "Aus", 10), _row("B", "Aus", 20), _row("C", "Bonds", 99)]
    assert default_reference(rows[1], rows)["asx_code"] == "A"
    assert default_reference(rows[0], rows)["asx_code"] == "B"
    assert default_reference(rows[2], rows)["asx_code"] == "B"  # alone in its category: largest anywhere
    assert default_reference(rows[0], rows[:1]) is None
