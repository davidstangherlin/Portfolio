"""Thin wrapper around `yfinance` for ASX-listed tickers.

ASX codes are 3-letter codes (e.g. "BHP"); Yahoo Finance addresses them
with a ".AX" suffix ("BHP.AX"). This module only ever talks to Yahoo -
all persistence lives in `src.ingestion.price_ingestion` /
`fundamentals_ingestion`.

`yfinance`'s `.info` / `.financials` / `.balance_sheet` / `.cashflow`
fields are not a stable, versioned API - Yahoo changes field names and
availability without notice, and some fields are simply absent for
smaller ASX-listed companies. Every extraction below is defensive
(`.get(..., None)` / try-except) and returns `None` for anything it
can't find rather than raising, so a partial/missing field never aborts
an entire ingestion run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.dividend_history import Payment

logger = logging.getLogger(__name__)


def to_yahoo_symbol(asx_code: str) -> str:
    asx_code = asx_code.strip().upper()
    return asx_code if asx_code.endswith(".AX") else f"{asx_code}.AX"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and (value != value):  # NaN
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class PriceBar:
    price_date: date
    close_price: Decimal
    volume: int | None
    market_cap: Decimal | None


@dataclass
class FundamentalsSnapshot:
    fiscal_year: int
    period_type: str  # 'FY' (yfinance only exposes annual statements reliably)
    report_date: date
    revenue: Decimal | None = None
    ebit: Decimal | None = None
    net_profit_after_tax: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    free_cash_flow: Decimal | None = None
    capital_expenditure: Decimal | None = None
    eps: Decimal | None = None
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    total_equity: Decimal | None = None
    total_debt: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    net_tangible_assets: Decimal | None = None
    dividends_per_share: Decimal | None = None
    abnormal_distributions_per_share: Decimal | None = None  # excluded one-offs, see dividend_history.py
    reporting_currency: str | None = None  # currency the statements were published in (see currency.py)
    fx_rate: Decimal | None = None  # rate applied to convert them into the trading currency
    franking_percentage: Decimal | None = None  # Yahoo does not expose this - left None
    corporate_tax_rate: Decimal | None = None  # Yahoo does not expose this - left None


class YahooClient:
    def __init__(self, asx_code: str):
        self.asx_code = asx_code.strip().upper()
        self.symbol = to_yahoo_symbol(self.asx_code)
        self._ticker = yf.Ticker(self.symbol)
        # Filled by get_price_history() from the same request: splits and
        # cash distributions in the period fetched, oldest first.
        self.last_splits: list[tuple[date, Decimal]] = []
        self.last_dividends: list[Payment] = []

    def get_profile(self) -> dict:
        """Company name / sector / industry / country / currencies / business
        summary, for populating `companies`."""
        try:
            info = self._ticker.get_info()
        except Exception:  # yfinance raises a variety of network/parsing errors
            logger.exception("Failed to fetch profile for %s", self.symbol)
            return {}
        return {
            "company_name": info.get("longName") or info.get("shortName") or self.asx_code,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "trading_currency": info.get("currency"),  # the share price's currency (AUD on the ASX)
            "financial_currency": info.get("financialCurrency"),  # the statements' currency
            "business_summary": (info.get("longBusinessSummary") or "").strip(),
        }

    def get_price_history(self, period: str = "1mo", include_market_cap: bool = True) -> list[PriceBar]:
        """Daily close/volume/market-cap bars for the given yfinance period
        (e.g. '1mo', '6mo', '1y', 'max').

        Closes are the prices actually traded (adjusted for splits only).
        yfinance's default also scales every earlier close down by each
        later dividend, which, refetched a month at a time, left a step in
        the stored history at each ex-date and would count distributions
        twice in a total return (docs/AS_BUILT.md §25). Splits and cash
        distributions in the period are kept in last_splits and
        last_dividends."""
        self.last_splits, self.last_dividends = [], []
        try:
            history = self._ticker.history(period=period, interval="1d", auto_adjust=False, actions=True)
        except Exception:
            logger.exception("Failed to fetch price history for %s", self.symbol)
            return []

        if history is None or history.empty:
            return []

        for column, target in (("Stock Splits", self.last_splits), ("Dividends", self.last_dividends)):
            if column not in history:
                continue
            for idx, value in history[column].items():
                amount = _to_decimal(float(value)) if pd.notna(value) else None
                if amount:
                    day = idx.date() if hasattr(idx, "date") else idx
                    target.append((day, amount) if column == "Stock Splits" else Payment(ex_date=day, amount=amount))

        shares_outstanding = None
        if include_market_cap:
            try:
                shares_outstanding = self._ticker.get_info().get("sharesOutstanding")
            except Exception:
                logger.debug("sharesOutstanding unavailable for %s", self.symbol, exc_info=True)

        bars: list[PriceBar] = []
        for idx, row in history.iterrows():
            close = _to_decimal(row.get("Close"))
            if close is None:
                continue
            volume = int(row["Volume"]) if pd.notna(row.get("Volume")) else None
            market_cap = close * Decimal(str(shares_outstanding)) if shares_outstanding else None
            price_date = idx.date() if hasattr(idx, "date") else idx
            bars.append(PriceBar(price_date=price_date, close_price=close, volume=volume, market_cap=market_cap))
        return bars

    def get_annual_fundamentals(self, max_years: int = 4) -> list[FundamentalsSnapshot]:
        """Best-effort annual financial-report snapshots from Yahoo's income
        statement / balance sheet / cash flow statement."""
        try:
            income_stmt = self._ticker.get_income_stmt(freq="yearly")
            balance_sheet = self._ticker.get_balance_sheet(freq="yearly")
            cash_flow = self._ticker.get_cash_flow(freq="yearly")
        except Exception:
            logger.exception("Failed to fetch financial statements for %s", self.symbol)
            return []

        if income_stmt is None or income_stmt.empty:
            return []

        snapshots: list[FundamentalsSnapshot] = []
        for period_end in list(income_stmt.columns)[:max_years]:
            report_date = period_end.date() if hasattr(period_end, "date") else period_end

            def inc(row: str) -> Decimal | None:
                return _to_decimal(income_stmt.loc[row, period_end]) if row in income_stmt.index else None

            def bal(row: str) -> Decimal | None:
                if balance_sheet is None or period_end not in balance_sheet.columns or row not in balance_sheet.index:
                    return None
                return _to_decimal(balance_sheet.loc[row, period_end])

            def cf(row: str) -> Decimal | None:
                if cash_flow is None or period_end not in cash_flow.columns or row not in cash_flow.index:
                    return None
                return _to_decimal(cash_flow.loc[row, period_end])

            # NOTE: yfinance 1.7.x returns PascalCase, no-space row labels
            # (e.g. "NetIncome", "StockholdersEquity") - NOT the spaced,
            # title-cased form ("Net Income", "Stockholders Equity") used
            # in earlier yfinance releases and in this module's first cut.
            # Confirmed directly against a live pull (2026-10-01); see
            # docs/AS_BUILT.md §11 for the history of this mismatch.
            operating_cf = cf("OperatingCashFlow") or cf("CashFlowFromContinuingOperatingActivities")
            capex = cf("CapitalExpenditure")
            free_cf = cf("FreeCashFlow")
            if free_cf is None and operating_cf is not None and capex is not None:
                # Yahoo reports capex as a negative outflow already.
                free_cf = operating_cf + capex

            total_debt = bal("TotalDebt")
            if total_debt is None:
                long_term = bal("LongTermDebt") or Decimal("0")
                short_term = bal("CurrentDebt") or Decimal("0")
                total_debt = long_term + short_term if (long_term or short_term) else None

            snapshots.append(
                FundamentalsSnapshot(
                    fiscal_year=report_date.year,
                    period_type="FY",
                    report_date=report_date,
                    revenue=inc("TotalRevenue"),
                    ebit=inc("EBIT"),
                    net_profit_after_tax=inc("NetIncome"),
                    operating_cash_flow=operating_cf,
                    free_cash_flow=free_cf,
                    capital_expenditure=capex,
                    eps=inc("DilutedEPS") or inc("BasicEPS"),
                    total_assets=bal("TotalAssets"),
                    total_liabilities=bal("TotalLiabilitiesNetMinorityInterest"),
                    total_equity=bal("StockholdersEquity") or bal("CommonStockEquity"),
                    total_debt=total_debt,
                    cash_and_equivalents=bal("CashAndCashEquivalents"),
                    net_tangible_assets=bal("TangibleBookValue"),
                    dividends_per_share=None,  # sourced separately via get_dividend_payments
                )
            )
        return snapshots

    @staticmethod
    def get_fx_history(from_currency: str, to_currency: str, start: date, end: date) -> list[tuple[date, Decimal]]:
        """Daily closing exchange rates (to_currency per from_currency), e.g.
        USD->AUD from Yahoo's USDAUD=X. Empty on any failure; the caller
        decides what an unavailable rate means."""
        pair = f"{from_currency}{to_currency}=X"
        try:
            history = yf.Ticker(pair).history(start=start, end=end, interval="1d", auto_adjust=False)
        except Exception:
            logger.exception("Failed to fetch exchange rates for %s", pair)
            return []
        if history is None or history.empty or "Close" not in history.columns:
            return []
        out = []
        for ts, value in history["Close"].items():
            rate = _to_decimal(float(value))
            if rate is not None and rate > 0:
                out.append((ts.date() if hasattr(ts, "date") else ts, rate))
        return out

    def get_dividend_payments(self) -> list[Payment]:
        """Every per-share dividend Yahoo has recorded, oldest first. Raw:
        abnormal one-offs and financial-year matching are handled by
        src.ingestion.dividend_history."""
        try:
            dividends = self._ticker.dividends
        except Exception:
            logger.exception("Failed to fetch dividends for %s", self.symbol)
            return []
        if dividends is None or dividends.empty:
            return []
        payments = []
        for ts, amount in dividends.items():
            value = _to_decimal(float(amount))
            if value is not None:
                payments.append(Payment(ex_date=ts.date() if hasattr(ts, "date") else ts, amount=value))
        return sorted(payments, key=lambda p: p.ex_date)
