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
    franking_percentage: Decimal | None = None  # Yahoo does not expose this - left None
    corporate_tax_rate: Decimal | None = None  # Yahoo does not expose this - left None


class YahooClient:
    def __init__(self, asx_code: str):
        self.asx_code = asx_code.strip().upper()
        self.symbol = to_yahoo_symbol(self.asx_code)
        self._ticker = yf.Ticker(self.symbol)

    def get_profile(self) -> dict:
        """Company name / sector / industry, for populating `companies`."""
        try:
            info = self._ticker.get_info()
        except Exception:  # yfinance raises a variety of network/parsing errors
            logger.exception("Failed to fetch profile for %s", self.symbol)
            return {}
        return {
            "company_name": info.get("longName") or info.get("shortName") or self.asx_code,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_price_history(self, period: str = "1mo") -> list[PriceBar]:
        """Daily close/volume/market-cap bars for the given yfinance period
        (e.g. '1mo', '6mo', '1y', 'max')."""
        try:
            history = self._ticker.history(period=period, interval="1d")
        except Exception:
            logger.exception("Failed to fetch price history for %s", self.symbol)
            return []

        if history is None or history.empty:
            return []

        shares_outstanding = None
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

            operating_cf = cf("Operating Cash Flow") or cf("Total Cash From Operating Activities")
            capex = cf("Capital Expenditure")
            free_cf = cf("Free Cash Flow")
            if free_cf is None and operating_cf is not None and capex is not None:
                # Yahoo reports capex as a negative outflow already.
                free_cf = operating_cf + capex

            total_debt = bal("Total Debt")
            if total_debt is None:
                long_term = bal("Long Term Debt") or Decimal("0")
                short_term = bal("Current Debt") or Decimal("0")
                total_debt = long_term + short_term if (long_term or short_term) else None

            snapshots.append(
                FundamentalsSnapshot(
                    fiscal_year=report_date.year,
                    period_type="FY",
                    report_date=report_date,
                    revenue=inc("Total Revenue"),
                    ebit=inc("EBIT"),
                    net_profit_after_tax=inc("Net Income"),
                    operating_cash_flow=operating_cf,
                    free_cash_flow=free_cf,
                    capital_expenditure=capex,
                    eps=inc("Diluted EPS") or inc("Basic EPS"),
                    total_assets=bal("Total Assets"),
                    total_liabilities=bal("Total Liabilities Net Minority Interest"),
                    total_equity=bal("Stockholders Equity") or bal("Common Stock Equity"),
                    total_debt=total_debt,
                    cash_and_equivalents=bal("Cash And Cash Equivalents"),
                    net_tangible_assets=bal("Tangible Book Value"),
                    dividends_per_share=None,  # sourced separately via get_dividends_per_share
                )
            )
        return snapshots

    def get_dividends_per_share(self, fiscal_year: int) -> Decimal | None:
        """Sum of per-share dividends paid in the given calendar/fiscal year."""
        try:
            dividends = self._ticker.dividends
        except Exception:
            logger.exception("Failed to fetch dividends for %s", self.symbol)
            return None
        if dividends is None or dividends.empty:
            return None
        year_dividends = dividends[dividends.index.year == fiscal_year]
        if year_dividends.empty:
            return None
        return _to_decimal(float(year_dividends.sum()))
