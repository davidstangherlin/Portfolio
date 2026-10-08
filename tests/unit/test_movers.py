"""The dashboard's biggest movers: ranking by percentage, and only moves
from the latest trading day."""

from datetime import date
from decimal import Decimal

from src.screening.movers import day_change, top_movers

DAY = date(2026, 10, 7)


def _row(code, change, day=DAY):
    return {"asx_code": code, "company_name": code, "price": Decimal("1"), "price_date": day,
            "change_percent": None if change is None else Decimal(change), "held": False, "watchlists": []}


def test_biggest_rises_and_falls_by_percentage():
    rows = [_row("A", "3.5"), _row("B", "12"), _row("C", "-8"), _row("D", "-1.2"), _row("E", "0"), _row("F", "0.4")]
    out = top_movers(rows, 2)
    assert [r["asx_code"] for r in out["up"]] == ["B", "A"]
    assert [r["asx_code"] for r in out["down"]] == ["C", "D"]
    assert out["as_of"] == DAY and out["traded"] == 6


def test_a_stale_price_is_not_todays_move():
    # Z last traded a week ago (suspended): its big move then isn't today's.
    rows = [_row("A", "2"), _row("Z", "40", date(2026, 9, 30)), _row("N", None)]
    out = top_movers(rows, 10)
    assert [r["asx_code"] for r in out["up"]] == ["A"] and out["traded"] == 1


def test_nothing_priced_yet():
    assert top_movers([_row("A", None)], 5) == {"as_of": None, "traded": 0, "up": [], "down": []}


def test_day_change():
    assert day_change(Decimal("2.00"), Decimal("2.10")) == Decimal("5.00")
    assert day_change(None, Decimal("2.10")) is None and day_change(Decimal("0"), Decimal("1")) is None
