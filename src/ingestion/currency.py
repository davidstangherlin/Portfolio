"""Converts financial-statement figures into the currency the share trades
in (docs/AS_BUILT.md §7.7, known-issue #25).

Yahoo reports many ASX companies' statements in their reporting currency -
US dollars for most of the big miners (BHP, RIO, S32), New Zealand dollars
for NZ listings - while the ASX share price is in Australian dollars.
Comparing a US-dollar EPS or free cash flow with an Australian-dollar price
distorted P/E, P/B, intrinsic value, margin of safety and the Graham Number
by the exchange rate (roughly 50% at the time). Each report is now
converted at the exchange rate on its own balance date, before it is
stored, so everything downstream works in one currency.

Dividends are not converted: Yahoo already records them per share in the
trading currency.

Pure functions only: the exchange-rate history is fetched by
YahooClient.get_fx_history().
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

# Every monetary FundamentalsSnapshot field that comes from the financial
# statements. dividends_per_share / abnormal_distributions_per_share come
# from the dividend feed (trading currency) and are deliberately absent.
MONETARY_FIELDS = (
    "revenue", "ebit", "net_profit_after_tax", "operating_cash_flow", "free_cash_flow",
    "capital_expenditure", "eps", "total_assets", "total_liabilities", "total_equity",
    "total_debt", "cash_and_equivalents", "net_tangible_assets",
)
MAX_RATE_GAP_DAYS = 10  # the nearest earlier rate must be within this many days of the balance date
FX_RATE_PLACES = Decimal("0.000001")


class CurrencyConversionError(RuntimeError):
    """No usable exchange rate - the company's statements are left
    unconverted rather than stored in the wrong currency."""


def rate_on(closes: list[tuple[date, Decimal]], on: date) -> Decimal | None:
    """The last daily close on or before `on` (balance dates often fall on
    a weekend), provided it is no more than MAX_RATE_GAP_DAYS old."""
    eligible = [(d, r) for d, r in closes if d <= on and r and r > 0]
    if not eligible:
        return None
    d, r = max(eligible, key=lambda dr: dr[0])
    return r if on - d <= timedelta(days=MAX_RATE_GAP_DAYS) else None


def invert(closes: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """A rate history quoted the other way round (USD per PGK from PGK per USD)."""
    return [(d, (Decimal(1) / r).quantize(Decimal("0.0000000001"))) for d, r in closes if r and r > 0]


def cross_rates(first: list[tuple[date, Decimal]], second: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """Chain two histories through a common currency: A->USD then USD->B
    gives A->B on each date of the first, using the second's latest rate on
    or before it. For currencies Yahoo has no direct pair for (the Papua New
    Guinea kina, known issue #36)."""
    out = []
    for d, r in first:
        r2 = rate_on(second, d)
        if r2 is not None:
            out.append((d, r * r2))
    return out


def convert_snapshot(snapshot, reporting_currency: str, rate: Decimal) -> None:
    """Multiply every statement figure by `rate` in place and record what was done."""
    for field in MONETARY_FIELDS:
        value = getattr(snapshot, field)
        if value is not None:
            setattr(snapshot, field, value * rate)
    snapshot.reporting_currency = reporting_currency
    snapshot.fx_rate = rate.quantize(FX_RATE_PLACES)


def apply_conversion(snapshots, reporting_currency: str, trading_currency: str, closes) -> None:
    """Convert every snapshot from `reporting_currency` to `trading_currency`.
    `closes` is the exchange-rate history as [(date, rate)], where rate is
    trading-currency units per reporting-currency unit. Same currency:
    nothing changes beyond recording a rate of 1."""
    if reporting_currency == trading_currency:
        for snapshot in snapshots:
            snapshot.reporting_currency = reporting_currency
            snapshot.fx_rate = Decimal("1")
        return
    for snapshot in snapshots:
        rate = rate_on(closes, snapshot.report_date)
        if rate is None:
            raise CurrencyConversionError(
                f"no {reporting_currency}/{trading_currency} rate within {MAX_RATE_GAP_DAYS} days of {snapshot.report_date}")
        convert_snapshot(snapshot, reporting_currency, rate)
