"""Coattail (docs/AS_BUILT.md §31): which holders count as index funds."""

import pytest

from src.coattail.views import is_index_fund


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
