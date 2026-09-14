"""Orchestrates computing a `valuation_metrics` row for a company from its
latest `daily_prices` and `financial_reports` data, and upserting it.

Shares outstanding are not stored directly in the schema. They are derived
from the latest daily price's `market_cap / close_price` (the most direct
figure we have), falling back to `net_profit_after_tax / eps` when a
market cap isn't available. `current_ratio` is intentionally left `None`:
the schema stores `total_assets`/`total_liabilities` but not the
current (short-term) split, so a true current ratio cannot be derived
without adding those columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Company, DailyPrice, FinancialReport, ValuationMetric
from src.valuation import dcf as dcf_module
from src.valuation.dividends import dividend_yields
from src.valuation.graham import book_value_per_share, graham_number

logger = logging.getLogger(__name__)


@dataclass
class ValuationInputs:
    company: Company
    price: DailyPrice
    report: FinancialReport
    shares_outstanding: Decimal | None


def _latest_price(session: Session, company_id) -> DailyPrice | None:
    stmt = (
        select(DailyPrice)
        .where(DailyPrice.company_id == company_id)
        .order_by(DailyPrice.price_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _latest_annual_report(session: Session, company_id) -> FinancialReport | None:
    stmt = (
        select(FinancialReport)
        .where(FinancialReport.company_id == company_id, FinancialReport.period_type == "FY")
        .order_by(FinancialReport.fiscal_year.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _estimate_shares_outstanding(price: DailyPrice, report: FinancialReport) -> Decimal | None:
    if price.market_cap and price.close_price:
        return price.market_cap / price.close_price
    if report.net_profit_after_tax and report.eps and report.eps != 0:
        return report.net_profit_after_tax / report.eps
    return None


def gather_inputs(session: Session, company: Company) -> ValuationInputs | None:
    price = _latest_price(session, company.company_id)
    report = _latest_annual_report(session, company.company_id)
    if price is None or report is None:
        logger.warning(
            "Skipping %s: missing %s", company.asx_code,
            "price and financial data" if price is None and report is None
            else "price data" if price is None else "financial report data",
        )
        return None

    shares_outstanding = _estimate_shares_outstanding(price, report)
    return ValuationInputs(company=company, price=price, report=report, shares_outstanding=shares_outstanding)


def compute_metrics(
    inputs: ValuationInputs,
    *,
    growth_rate: Decimal = dcf_module.DEFAULT_GROWTH_RATE,
    discount_rate: Decimal = dcf_module.DEFAULT_DISCOUNT_RATE,
    terminal_growth_rate: Decimal = dcf_module.DEFAULT_TERMINAL_GROWTH_RATE,
    stage1_years: int = dcf_module.DEFAULT_STAGE1_YEARS,
) -> dict:
    price = inputs.price
    report = inputs.report
    shares = inputs.shares_outstanding

    bvps = book_value_per_share(report.total_equity, shares)
    graham = graham_number(report.eps, bvps)

    pe_ratio = price.close_price / report.eps if report.eps and report.eps != 0 else None
    pb_ratio = price.close_price / bvps if bvps else None

    fcf_per_share = report.free_cash_flow / shares if report.free_cash_flow and shares else None
    price_to_fcf = price.close_price / fcf_per_share if fcf_per_share else None

    enterprise_value = None
    ev_to_ebit = None
    if price.market_cap is not None:
        enterprise_value = price.market_cap + (report.total_debt or Decimal("0")) - (report.cash_and_equivalents or Decimal("0"))
        if report.ebit:
            ev_to_ebit = enterprise_value / report.ebit

    roe = (report.net_profit_after_tax / report.total_equity * 100) if report.net_profit_after_tax and report.total_equity else None

    invested_capital = None
    roic = None
    if report.net_profit_after_tax is not None and report.total_debt is not None and report.total_equity is not None:
        invested_capital = report.total_debt + report.total_equity - (report.cash_and_equivalents or Decimal("0"))
        if invested_capital and invested_capital != 0:
            roic = report.net_profit_after_tax / invested_capital * 100

    debt_to_equity = (report.total_debt / report.total_equity) if report.total_debt is not None and report.total_equity else None

    yields = dividend_yields(
        report.dividends_per_share, price.close_price, report.franking_percentage, report.corporate_tax_rate
    )

    dcf_intrinsic_value = None
    if report.free_cash_flow and report.free_cash_flow > 0 and shares:
        dcf_result = dcf_module.two_stage_dcf(
            base_fcf=report.free_cash_flow,
            shares_outstanding=shares,
            cash_and_equivalents=report.cash_and_equivalents or Decimal("0"),
            total_debt=report.total_debt or Decimal("0"),
            growth_rate=growth_rate,
            stage1_years=stage1_years,
            terminal_growth_rate=terminal_growth_rate,
            discount_rate=discount_rate,
        )
        dcf_intrinsic_value = dcf_result.intrinsic_value_per_share

    margin_of_safety = dcf_module.margin_of_safety_percent(dcf_intrinsic_value, price.close_price)

    return {
        "as_of_date": price.price_date,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "price_to_fcf": price_to_fcf,
        "ev_to_ebit": ev_to_ebit,
        "roe": roe,
        "roic": roic,
        "debt_to_equity": debt_to_equity,
        "current_ratio": None,  # not derivable: schema has no current assets/liabilities split
        "uncapped_dividend_yield": yields.uncapped_dividend_yield,
        "grossed_up_dividend_yield": yields.grossed_up_dividend_yield,
        "dcf_intrinsic_value": dcf_intrinsic_value,
        "graham_number": graham,
        "margin_of_safety_percent": margin_of_safety,
    }


def upsert_valuation_metric(session: Session, company_id, metrics: dict) -> None:
    stmt = insert(ValuationMetric).values(company_id=company_id, **metrics)
    update_cols = {k: getattr(stmt.excluded, k) for k in metrics}
    stmt = stmt.on_conflict_do_update(
        index_elements=[ValuationMetric.company_id, ValuationMetric.as_of_date],
        set_=update_cols,
    )
    session.execute(stmt)


def run_valuation_for_company(
    session: Session,
    company: Company,
    **dcf_kwargs,
) -> dict | None:
    inputs = gather_inputs(session, company)
    if inputs is None:
        return None
    metrics = compute_metrics(inputs, **dcf_kwargs)
    upsert_valuation_metric(session, company.company_id, metrics)
    return metrics


def run_valuation(session: Session, asx_codes: list[str] | None = None, **dcf_kwargs) -> dict[str, dict]:
    """Compute and upsert valuation metrics for the given ASX codes, or all
    active companies if none are given. Returns {asx_code: metrics}."""
    stmt = select(Company).where(Company.is_active.is_(True))
    if asx_codes:
        stmt = select(Company).where(Company.asx_code.in_(asx_codes))

    results: dict[str, dict] = {}
    for company in session.execute(stmt).scalars():
        metrics = run_valuation_for_company(session, company, **dcf_kwargs)
        if metrics is not None:
            results[company.asx_code] = metrics

    session.commit()
    return results
