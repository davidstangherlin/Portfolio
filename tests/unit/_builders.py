"""Shared in-memory object builders for engine.py unit tests. Plain ORM
objects, never persisted - compute_metrics() takes a ValuationInputs
dataclass and plain model instances, no database session, so these build
just enough of each object for the functions under test to run."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.models import Company, DailyPrice, FinancialReport
from src.valuation.engine import ValuationInputs


def make_company(sector: str = "Basic Materials", **kw) -> Company:
    defaults = dict(
        ticker="TEST.AX", company_name="Test Co", sector=sector,
        industry="Test Industry", asx_code="TEST", is_active=True,
    )
    defaults.update(kw)
    return Company(**defaults)


def make_price(
    price_date: date = date(2026, 10, 2),
    close_price: Decimal = Decimal("10.00"),
    market_cap: Decimal = Decimal("1000000000"),
    **kw,
) -> DailyPrice:
    defaults = dict(price_date=price_date, close_price=close_price, volume=100000, market_cap=market_cap)
    defaults.update(kw)
    return DailyPrice(**defaults)


def make_report(fiscal_year: int = 2026, **kw) -> FinancialReport:
    defaults = dict(
        fiscal_year=fiscal_year, period_type="FY", report_date=date(fiscal_year, 6, 30),
        revenue=Decimal("500000000"), ebit=Decimal("150000000"), net_profit_after_tax=Decimal("120000000"),
        operating_cash_flow=Decimal("140000000"), free_cash_flow=Decimal("110000000"),
        capital_expenditure=Decimal("30000000"), eps=Decimal("1.20"),
        total_assets=Decimal("900000000"), total_liabilities=Decimal("200000000"),
        total_equity=Decimal("700000000"), total_debt=Decimal("100000000"),
        cash_and_equivalents=Decimal("80000000"), net_tangible_assets=Decimal("650000000"),
        dividends_per_share=Decimal("0.60"), franking_percentage=Decimal("100.0"), corporate_tax_rate=Decimal("30.0"),
    )
    defaults.update(kw)
    return FinancialReport(**defaults)


def make_inputs(
    company: Company | None = None,
    price: DailyPrice | None = None,
    reports: list[FinancialReport] | None = None,
    shares_outstanding: Decimal | None = Decimal("100000000"),
    dcf_free_cash_flow: Decimal | None = None,
    ddm_dividend_per_share: Decimal | None = None,
    prior_margin_of_safety_percent: Decimal | None = None,
) -> ValuationInputs:
    company = company or make_company()
    reports = reports if reports is not None else [make_report()]
    price = price or make_price()
    return ValuationInputs(
        company=company,
        price=price,
        report=reports[0],
        reports=reports,
        shares_outstanding=shares_outstanding,
        dcf_free_cash_flow=dcf_free_cash_flow,
        ddm_dividend_per_share=ddm_dividend_per_share,
        prior_margin_of_safety_percent=prior_margin_of_safety_percent,
    )
