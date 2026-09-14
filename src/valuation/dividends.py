"""ASX grossed-up dividend yield.

ASX dividends can carry franking credits: tax the company has already paid
on the profit distributed as a dividend, which resident shareholders can
claim back. The grossed-up ("franked") dividend an investor effectively
receives is the cash dividend plus the attached franking credit:

    franking_credit = DPS * franking_percentage * (tax_rate / (1 - tax_rate))
    gross_dividend  = DPS + franking_credit
                     = DPS * (1 + franking_percentage * (tax_rate / (1 - tax_rate)))

`franking_percentage` and `tax_rate` must be fractions in [0, 1] for this
formula (e.g. 1.0 for fully franked, 0.30 for the 30% corporate rate) -
`financial_reports.franking_percentage` / `corporate_tax_rate` are stored
as whole-number percentages (100.0, 30.0), so callers pulling values
straight from the database should divide by 100 first, or use
`grossed_up_yield_from_report`, which does that conversion for you.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DividendYields:
    uncapped_dividend_yield: Decimal | None  # cash yield, no franking credit (%)
    grossed_up_dividend_yield: Decimal | None  # yield including franking credit (%)


def gross_dividend(dividend_per_share: Decimal, franking_fraction: Decimal, tax_rate_fraction: Decimal) -> Decimal:
    """Grossed-up dividend per share, given fractional (0-1) franking % and tax rate."""
    if tax_rate_fraction >= 1:
        raise ValueError("tax_rate_fraction must be < 1")
    franking_credit_factor = franking_fraction * (tax_rate_fraction / (1 - tax_rate_fraction))
    return dividend_per_share * (1 + franking_credit_factor)


def dividend_yields(
    dividend_per_share: Decimal | None,
    price: Decimal | None,
    franking_percentage: Decimal | None,
    corporate_tax_rate: Decimal | None,
) -> DividendYields:
    """Compute uncapped and grossed-up dividend yield (%) from raw DB values.

    `franking_percentage` and `corporate_tax_rate` are whole-number
    percentages as stored in `financial_reports` (e.g. 100.0, 30.0).
    """
    if not dividend_per_share or not price or price <= 0:
        return DividendYields(None, None)

    uncapped = (dividend_per_share / price) * 100

    franking_fraction = (franking_percentage or Decimal("0")) / Decimal("100")
    tax_rate_fraction = (corporate_tax_rate or Decimal("30")) / Decimal("100")

    grossed = gross_dividend(dividend_per_share, franking_fraction, tax_rate_fraction)
    grossed_yield = (grossed / price) * 100

    return DividendYields(
        uncapped_dividend_yield=uncapped,
        grossed_up_dividend_yield=grossed_yield,
    )
