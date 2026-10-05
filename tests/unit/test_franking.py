"""src/ingestion/fundamentals_ingestion.py - franking by domicile.

Foreign-domiciled ASX listings (NZ, US, Irish and others) pay no
Australian franking credits; grossing up their yields as if fully franked
overstated them by ~43% (known-issue #2)."""

from datetime import date
from decimal import Decimal

import pytest

from src.ingestion.fundamentals_ingestion import franking_percentage_for, is_foreign
from src.ingestion.yahoo_client import FundamentalsSnapshot


def _snapshot(**kw):
    return FundamentalsSnapshot(fiscal_year=2026, period_type="FY", report_date=date(2026, 6, 30), **kw)


@pytest.mark.parametrize("country,expected", [
    ("Australia", False),
    ("australia ", False),
    (None, False),  # unknown keeps the long-standing Australian default
    ("New Zealand", True),
    ("United States", True),
    ("Ireland", True),
])
def test_is_foreign(country, expected):
    assert is_foreign(country) is expected


def test_foreign_company_is_unfranked():
    assert franking_percentage_for(_snapshot(), "New Zealand") == Decimal("0")


def test_australian_company_defaults_to_fully_franked():
    assert franking_percentage_for(_snapshot(), "Australia") == Decimal("100")
    assert franking_percentage_for(_snapshot(), None) == Decimal("100")


def test_supplied_franking_figure_still_wins_for_australian_company():
    assert franking_percentage_for(_snapshot(franking_percentage=Decimal("70")), "Australia") == Decimal("70")
