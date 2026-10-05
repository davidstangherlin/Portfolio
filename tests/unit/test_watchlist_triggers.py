"""Watchlist triggers and entry checks (src/watchlist/lists.py)."""

from decimal import Decimal

import pytest

from src.models import WatchlistItem
from src.watchlist.lists import WatchlistError, entry_fields, triggers


def _item(mos=None, price=None):
    return WatchlistItem(mos_above=None if mos is None else Decimal(mos), price_below=None if price is None else Decimal(price))


def test_no_triggers_set():
    assert triggers(_item(), {"margin_of_safety_percent": Decimal("50"), "current_price": Decimal("1")}) == []


@pytest.mark.parametrize("mos, met", [("25.01", True), ("25", False), (None, False)])
def test_margin_of_safety_trigger_is_strictly_above(mos, met):
    row = {"margin_of_safety_percent": None if mos is None else Decimal(mos), "current_price": Decimal("10")}
    [t] = triggers(_item(mos="25.00"), row)
    assert t["met"] is met and t["label"] == "Margin of safety above 25%"


@pytest.mark.parametrize("price, met", [("38.50", True), ("38.49", True), ("38.51", False)])
def test_price_trigger_is_at_or_below(price, met):
    [t] = triggers(_item(price="38.50"), {"margin_of_safety_percent": None, "current_price": Decimal(price)})
    assert t["met"] is met and t["label"] == "Price at or below $38.50"


def test_a_company_no_longer_valued_meets_nothing():
    assert [t["met"] for t in triggers(_item(mos="10", price="5"), None)] == [False, False]


def test_entry_fields_are_cleaned():
    assert entry_fields({"note": "  watch  ", "mos_above": "25%", "price_below": "$38.50"}) == {
        "note": "watch", "mos_above": Decimal("25"), "price_below": Decimal("38.50")}
    assert entry_fields({}) == {"note": None, "mos_above": None, "price_below": None}
    assert entry_fields({"mos_above": "-10"})["mos_above"] == Decimal("-10")  # "less overvalued than -10%" is allowed


@pytest.mark.parametrize("body, message", [
    ({"price_below": "0"}, "more than zero"),
    ({"mos_above": "abc"}, "must be a number"),
    ({"mos_above": "12.345"}, "at most 2 decimal places"),
    ({"note": "x" * 501}, "at most 500 characters"),
])
def test_entry_mistakes(body, message):
    with pytest.raises(WatchlistError, match=message):
        entry_fields(body)
