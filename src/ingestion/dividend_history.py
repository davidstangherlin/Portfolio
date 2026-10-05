"""Turns a company's raw dividend payment history into a per-financial-year
dividend per share (docs/AS_BUILT.md §7.6).

Two corrections to the raw Yahoo Finance feed, both found on Tower (TWR):

1. Abnormal distributions are excluded. Yahoo records some one-off
   payments as ordinary dividends: Tower's March 2025 capital return paid
   NZ$1.1858 per *cancelled* share (1 in 10 were cancelled), but the feed
   applied it to every share, as if it were a dividend roughly ten times
   Tower's usual annual payout. Left in, it produced a 519% payout ratio, a
   107% yield, an inflated dividend-discount valuation and a false
   "dividend cut" the following year. A payment is treated as abnormal when
   it is more than ABNORMAL_DISTRIBUTION_MULTIPLE times the company's
   typical annual dividend. The excluded amount is kept, not discarded, so
   it can be shown.

2. Dividends are matched to the financial year they belong to. Summing by
   calendar year put Tower's (September year-end) and December year-end
   companies' dividends half a year out of step with their earnings. Each
   financial year now takes the twelve months of ex-dividend dates ending
   FY_DIVIDEND_LAG_MONTHS after its balance date, which captures that
   year's interim (paid during the year) and final (paid after it) for
   half-yearly payers on any year-end, and still totals twelve months for
   quarterly payers.

Pure functions only: no network, no database.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

ABNORMAL_DISTRIBUTION_MULTIPLE = Decimal("2")  # x the typical annual dividend
COMPARISON_WINDOW_DAYS = 3 * 365  # payments within this distance set the "typical" level
MIN_COMPARABLE_PAYMENTS = 2  # fewer than this and nothing is judged abnormal
FY_DIVIDEND_LAG_MONTHS = 4


@dataclass(frozen=True)
class Payment:
    ex_date: date
    amount: Decimal


@dataclass(frozen=True)
class FiscalYearDividends:
    ordinary: Decimal | None  # dividend per share used everywhere; None = no dividend history at all
    abnormal: Decimal  # excluded one-off distributions per share in the same window


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _typical_annual_dividend(others: list[Payment]) -> Decimal | None:
    """Median of the trailing-twelve-month totals at each comparable
    payment: a run rate that works for quarterly, half-yearly and uneven
    interim/final payers alike."""
    if len(others) < MIN_COMPARABLE_PAYMENTS:
        return None
    totals = [
        sum((o.amount for o in others if q.ex_date - timedelta(days=365) < o.ex_date <= q.ex_date), Decimal("0"))
        for q in others
    ]
    return Decimal(str(median(totals)))


def split_abnormal(payments: list[Payment]) -> tuple[list[Payment], list[Payment]]:
    """(ordinary, abnormal). Each payment is judged against the others
    within COMPARISON_WINDOW_DAYS of it, excluding itself."""
    ordinary, abnormal = [], []
    for p in payments:
        others = [q for q in payments
                  if q is not p and q.amount > 0 and abs((q.ex_date - p.ex_date).days) <= COMPARISON_WINDOW_DAYS]
        typical = _typical_annual_dividend(others)
        if typical and p.amount > ABNORMAL_DISTRIBUTION_MULTIPLE * typical:
            abnormal.append(p)
        else:
            ordinary.append(p)
    return ordinary, abnormal


def fiscal_year_window(report_date: date, today: date) -> tuple[date, date]:
    """(start, end] of ex-dividend dates that belong to the financial year
    ending `report_date`. If the window hasn't closed yet (the final
    dividend may still be to come) it falls back to the twelve months to
    today, so a year in progress isn't under-counted as a cut."""
    end = min(add_months(report_date, FY_DIVIDEND_LAG_MONTHS), today)
    return add_months(end, -12), end


def dividends_for_fiscal_year(payments: list[Payment], report_date: date, today: date) -> FiscalYearDividends:
    if not payments:
        return FiscalYearDividends(ordinary=None, abnormal=Decimal("0"))
    ordinary, abnormal = split_abnormal(payments)
    start, end = fiscal_year_window(report_date, today)
    in_window = lambda ps: sum((p.amount for p in ps if start < p.ex_date <= end), Decimal("0"))  # noqa: E731
    # A company with a dividend history that paid nothing in this window
    # genuinely paid zero, so 0 (not None) - which also lets a corrected
    # zero overwrite a stale stored figure on re-ingestion.
    return FiscalYearDividends(ordinary=in_window(ordinary), abnormal=in_window(abnormal))
