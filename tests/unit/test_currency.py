"""src/ingestion/currency.py - converting statement figures into the
share price's currency (known-issue #25)."""

from datetime import date
from decimal import Decimal as D

import pytest

from src.ingestion.currency import (
    MONETARY_FIELDS, CurrencyConversionError, apply_conversion, convert_snapshot, rate_on,
)
from src.ingestion.yahoo_client import FundamentalsSnapshot

CLOSES = [(date(2025, 6, 26), D("1.52")), (date(2025, 6, 27), D("1.53")), (date(2025, 6, 30), D("1.5234"))]


def _snapshot(report_date=date(2025, 6, 30), **kw):
    values = {f: D("100") for f in MONETARY_FIELDS} | {"eps": D("1.50")}
    values |= kw
    return FundamentalsSnapshot(fiscal_year=report_date.year, period_type="FY", report_date=report_date,
                                dividends_per_share=D("0.80"), **values)


def test_rate_on_the_balance_date():
    assert rate_on(CLOSES, date(2025, 6, 30)) == D("1.5234")


def test_weekend_balance_date_uses_the_last_trading_day():
    assert rate_on(CLOSES[:2], date(2025, 6, 29)) == D("1.53")


def test_stale_or_missing_rate_is_none():
    assert rate_on(CLOSES, date(2025, 8, 30)) is None  # nearest rate is two months old
    assert rate_on([], date(2025, 6, 30)) is None


def test_us_dollar_statements_convert_but_dividends_do_not():
    snap = _snapshot()
    apply_conversion([snap], "USD", "AUD", CLOSES)
    assert snap.eps == D("1.50") * D("1.5234")
    assert snap.free_cash_flow == D("100") * D("1.5234")
    assert snap.dividends_per_share == D("0.80")  # already in AUD from the dividend feed
    assert (snap.reporting_currency, snap.fx_rate) == ("USD", D("1.523400"))


def test_each_year_uses_its_own_balance_date_rate():
    older = _snapshot(date(2024, 6, 30))
    apply_conversion([_snapshot(), older], "USD", "AUD", CLOSES + [(date(2024, 6, 28), D("1.50"))])
    assert older.fx_rate == D("1.500000")


def test_same_currency_is_unchanged_and_recorded():
    snap = _snapshot()
    apply_conversion([snap], "AUD", "AUD", [])
    assert snap.eps == D("1.50") and (snap.reporting_currency, snap.fx_rate) == ("AUD", D("1"))


def test_missing_values_stay_missing():
    snap = _snapshot(ebit=None)
    convert_snapshot(snap, "NZD", D("0.91"))
    assert snap.ebit is None


def test_no_rate_refuses_rather_than_storing_the_wrong_currency():
    with pytest.raises(CurrencyConversionError, match="USD/AUD"):
        apply_conversion([_snapshot()], "USD", "AUD", [])
