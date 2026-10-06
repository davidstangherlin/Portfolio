"""The weekly refresh spread across the week (docs/AS_BUILT.md §16)."""

from datetime import date, datetime, timezone

from src.ingestion.rolling import nightly_share

TODAY = date(2026, 10, 7)
CODES = [f"C{i:02d}" for i in range(14)]


def test_never_fetched_first_then_oldest_a_seventh_a_night():
    fetched = {c: datetime(2026, 10, 6, 18, 30) for c in CODES}          # all fresh
    fetched |= {"C05": datetime(2026, 9, 29, 18, 30), "C02": datetime(2026, 9, 28, 18, 30), "C09": None}
    del fetched["C11"]                                                    # not in the database yet
    assert nightly_share(CODES, fetched, TODAY) == ["C09", "C11"]         # 14 / 7 = 2 a night
    assert nightly_share(CODES, fetched, TODAY, all_now=True) == ["C09", "C11", "C02", "C05"]


def test_a_week_after_its_fetch_a_share_is_due_again():
    fetched = {"A": datetime(2026, 10, 1, 18, 30), "B": datetime(2026, 9, 30, 18, 30)}
    assert nightly_share(["A", "B"], fetched, TODAY, all_now=True) == ["B"]  # A was six days ago
    aware = {"B": datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc)}
    assert nightly_share(["B"], aware, TODAY) == ["B"]


def test_small_lists_still_move():
    assert nightly_share(["ONE"], {}, TODAY) == ["ONE"]
    assert nightly_share([], {}, TODAY) == []
