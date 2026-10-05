"""src/ingestion/dividend_history.py - abnormal distributions and
financial-year matching of dividends."""

from datetime import date
from decimal import Decimal as D

from src.ingestion.dividend_history import (
    Payment, add_months, dividends_for_fiscal_year, fiscal_year_window, split_abnormal,
)

TODAY = date(2026, 10, 5)


def _pays(*pairs):
    return [Payment(date.fromisoformat(d), D(a)) for d, a in pairs]


# Tower Limited (TWR, September year-end) as Yahoo records it in AUD: the
# 20 March 2025 capital return (A$1.0777 per cancelled share) appears as a
# dividend on every share.
TOWER = _pays(
    ("2023-01-17", "0.040"), ("2023-06-14", "0.030"), ("2024-01-16", "0.000"), ("2024-06-12", "0.030"),
    ("2025-01-15", "0.065"), ("2025-03-18", "1.0777"), ("2025-06-11", "0.072"),
    ("2026-01-14", "0.150"), ("2026-06-10", "0.045"),
)


def test_tower_capital_return_is_held_out_as_abnormal():
    ordinary, abnormal = split_abnormal(TOWER)
    assert [p.amount for p in abnormal] == [D("1.0777")]
    assert len(ordinary) == len(TOWER) - 1


def test_tower_fy25_dividend_excludes_the_capital_return_and_reports_it():
    fy = dividends_for_fiscal_year(TOWER, date(2025, 9, 30), TODAY)
    # FY25 window: ex-dates after 31 Jan 2025 up to 31 Jan 2026 -
    # interim (June 2025) + final (January 2026), not the FY24 final.
    assert fy.ordinary == D("0.072") + D("0.150")
    assert fy.abnormal == D("1.0777")


def test_uneven_interim_and_final_is_not_mistaken_for_abnormal():
    # Small interim, large final: the final is 5x the interim but well
    # under twice a typical year's total, so it's ordinary.
    skewed = _pays(*[(f"{y}-03-10", "0.02") for y in range(2021, 2026)], *[(f"{y}-09-10", "0.10") for y in range(2021, 2026)])
    assert split_abnormal(skewed)[1] == []


def test_quarterly_payer_keeps_every_payment_and_totals_a_full_year():
    quarterly = _pays(*[(f"{y}-{m:02d}-28", "0.05") for y in (2024, 2025) for m in (3, 6, 9, 12)])
    assert split_abnormal(quarterly)[1] == []
    assert dividends_for_fiscal_year(quarterly, date(2025, 6, 30), TODAY).ordinary == D("0.20")


def test_too_little_history_to_judge_keeps_everything():
    assert split_abnormal(_pays(("2025-03-01", "0.10"), ("2025-09-01", "5.00")))[1] == []


def test_june_year_end_takes_that_years_interim_and_final():
    # Interim in March (during FY25), final in September (after year end);
    # the previous year's September final belongs to FY24.
    june = _pays(("2024-09-05", "0.50"), ("2025-03-06", "0.40"), ("2025-09-04", "0.55"))
    assert dividends_for_fiscal_year(june, date(2025, 6, 30), TODAY).ordinary == D("0.95")


def test_december_year_end_takes_the_final_paid_early_next_year():
    dec = _pays(("2024-03-01", "0.30"), ("2024-08-20", "0.25"), ("2025-03-03", "0.35"))
    assert dividends_for_fiscal_year(dec, date(2024, 12, 31), TODAY).ordinary == D("0.60")


def test_open_window_falls_back_to_the_last_twelve_months():
    # FY ended 30 June 2026; on 5 Aug 2026 the final hasn't gone ex yet, so
    # count the twelve months to today rather than report a half year as a cut.
    assert fiscal_year_window(date(2026, 6, 30), date(2026, 8, 5)) == (date(2025, 8, 5), date(2026, 8, 5))


def test_dividend_history_but_nothing_this_year_is_zero_not_missing():
    fy = dividends_for_fiscal_year(_pays(("2019-03-01", "0.10"), ("2019-09-01", "0.10")), date(2025, 6, 30), TODAY)
    assert fy.ordinary == D("0") and fy.abnormal == D("0")


def test_no_dividend_history_at_all_is_missing():
    assert dividends_for_fiscal_year([], date(2025, 6, 30), TODAY).ordinary is None


def test_add_months_clamps_to_month_end():
    assert add_months(date(2025, 10, 31), 4) == date(2026, 2, 28)
    assert add_months(date(2024, 10, 31), 4) == date(2025, 2, 28)
    assert add_months(date(2025, 6, 30), -12) == date(2024, 6, 30)
