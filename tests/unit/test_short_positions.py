"""ASIC's daily short position files (src/ingestion/short_positions.py) and
the short-selling caution (src/screening/short_caution.py)."""

from datetime import date
from decimal import Decimal

import pytest

from src.ingestion import short_positions as sp
from src.screening import short_caution
from src.screening.actions import red_flags, suggest_action

HEAD = ["Product", "Product Code", "Reported Short Positions", "Total Product in Issue",
        "% of Total Product in Issue Reported as Short Positions"]
ROWS = [["BHP GROUP LIMITED", "BHP", "12,345,678", "5,070,000,000", "0.24"],
        ["PILBARA MIN LIMITED", "PLS", "600,000,000", "3,000,000,000", "20.00"],
        ["", "", "", "", ""]]


def test_utf16_tab_separated_as_asic_publishes():
    body = "\n".join("\t".join(r) for r in [HEAD] + ROWS).encode("utf-16")
    rows = {r.asx_code: r for r in sp.parse(body)}
    assert set(rows) == {"BHP", "PLS"}
    assert (rows["BHP"].short_positions, rows["BHP"].shares_on_issue, rows["BHP"].short_percent) == (12345678, 5070000000, Decimal("0.2400"))


def test_comma_separated_without_a_percentage_column():
    head = HEAD[:4]
    body = "\n".join(",".join(f'"{c}"' for c in r[:4]) for r in [head] + ROWS[:2]).encode("utf-8-sig")
    rows = {r.asx_code: r for r in sp.parse(body)}
    assert rows["PLS"].short_percent == Decimal("20.0000")  # worked out from positions and shares on issue


def test_file_dates_and_days_to_fetch():
    assert sp.date_of("RR20261003-001-SSDailyAggShortPos.csv") == date(2026, 10, 3) and sp.date_of("x.csv") is None


def test_shorting_is_a_caution_not_a_red_flag():
    assert red_flags({"short_percent": Decimal("12.5")}) == []


@pytest.mark.parametrize("short, days, change, expected", [
    (None, None, None, None),          # no ASIC report
    ("0.8", "30", "0.5", None),        # a trivial short: days to cover doesn't count
    ("1.9", "8", "3", None),           # still under the 2% floor
    ("2.5", "4", "0.4", None),
    ("2.5", "6", None, "ELEVATED"),    # crowded: six days of trading to buy back
    ("3", None, "2.1", "ELEVATED"),    # building quickly
    ("5", None, None, "ELEVATED"),
    ("6", "12", None, "HIGH"),         # elevated and slow to cover
    ("4", "40", None, "ELEVATED"),     # days to cover alone never makes HIGH
    ("10", None, None, "HIGH"),
])
def test_caution_levels(short, days, change, expected):
    assert short_caution.level(short, days, change) == expected


def test_caution_in_words_and_beside_an_unchanged_action():
    row = {"short_percent": Decimal("6"), "days_to_cover": Decimal("12.4"), "short_change": Decimal("2.5"),
           "mos_ok": "Y", "roe_ok": "Y", "de_ok": "Y", "yield_ok": "Y"}
    found = short_caution.caution(row)
    assert found == {"level": "HIGH", "advice": "expect sharp price swings; keep any position small", "text": "heavily shorted (6.0% of shares sold short, 12.4 days to cover, "
                     "up 2.5 points in a month): expect sharp price swings; keep any position small"}
    action, reason = suggest_action(row)
    assert action == "BUY" and reason.endswith("; caution: " + found["text"])
    assert suggest_action({**row, "short_percent": Decimal("1")})[1] == "passes all four value tests with no red flags"
