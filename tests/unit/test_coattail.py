"""Coattail (docs/AS_BUILT.md §31): index funds, the manager behind a holder,
and the shares bought or sold."""

import pytest

from src.coattail.views import is_index_fund, manager_of, shares_change, slug


@pytest.mark.parametrize("holder, kind, expected", [
    ("Vanguard Total International Stock Index Fund", "FUND", True),
    ("iShares Core MSCI EAFE ETF", "FUND", True),
    ("SPDR S&P/ASX 200 Fund", "FUND", True),
    ("DFA International Small Cap Value Portfolio", "FUND", False),
    ("Fidelity Series International Value Fund", "FUND", False),
    ("Vanguard Group Inc", "INSTITUTION", False),       # institutions run both kinds
    ("BlackRock Institutional Index Trust", "INSTITUTION", False),
])
def test_index_funds_are_marked_by_name(holder, kind, expected):
    assert is_index_fund(holder, kind) is expected


@pytest.mark.parametrize("holder, manager", [
    ("Vanguard Total International Stock Index Fund", "Vanguard"),
    ("Vanguard Group Inc", "Vanguard"),
    ("iShares Core MSCI EAFE ETF", "BlackRock"),
    ("BlackRock Inc.", "BlackRock"),
    ("DFA International Core Equity Portfolio", "Dimensional"),
    ("Dimensional Fund Advisors LP", "Dimensional"),
    ("FMR LLC", "Fidelity"),
    ("Geode Capital Management, LLC", "Geode Capital"),
    ("Some Boutique Partners Pty Ltd", "Some Boutique Partners"),
    ("Acme Holdings Inc.", "Acme"),
])
def test_holders_group_under_their_manager(holder, manager):
    assert manager_of(holder) == manager


def test_shares_bought_or_sold_from_the_percent_change():
    assert shares_change(1250, 25) == 250         # held 1,000, bought 250
    assert shares_change(600, -40) == -400        # held 1,000, sold 400
    assert shares_change(1000, None) is None and shares_change(None, 5) is None
    assert slug("J.P. Morgan") == "j-p-morgan"
