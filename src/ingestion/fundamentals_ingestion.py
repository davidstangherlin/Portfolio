"""Ingest annual financial-report history from Yahoo Finance into
`financial_reports`.

Franking percentage and the corporate tax rate are not available from
Yahoo Finance. Companies domiciled outside Australia (NZ, US, Irish and
other foreign listings) pay no Australian franking credits, so they are
set to 0%; everything else defaults to fully franked (100%) at the
standard 30% Australian corporate rate, which holds for the large
majority of established ASX-listed companies but should be corrected by
hand for anything known to pay partly-franked or unfranked dividends.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.ingestion.common import ensure_profile, get_or_create_company
from src.ingestion.currency import apply_conversion
from src.ingestion.dividend_history import dividends_for_fiscal_year, split_abnormal
from src.ingestion.yahoo_client import YahooClient
from src.models import DividendPayment, FinancialReport

logger = logging.getLogger(__name__)

DEFAULT_FRANKING_PERCENTAGE = Decimal("100.0")
DEFAULT_CORPORATE_TAX_RATE = Decimal("30.0")
FOREIGN_FRANKING_PERCENTAGE = Decimal("0.0")

# Columns that may legitimately be missing on any given Yahoo pull (a
# transient gap, a field Yahoo doesn't report for this company). On
# conflict, keep the existing stored value rather than blanking it out
# when the latest fetch didn't return one.
_COALESCE_ON_UPDATE = (
    "revenue", "ebit", "net_profit_after_tax", "operating_cash_flow",
    "free_cash_flow", "capital_expenditure", "eps",
    "total_assets", "total_liabilities", "total_equity", "total_debt",
    "cash_and_equivalents", "net_tangible_assets", "dividends_per_share",
    "abnormal_distributions_per_share", "reporting_currency", "fx_rate",
)


def is_foreign(country: str | None) -> bool:
    """True when Yahoo reports a domicile other than Australia. Unknown
    (None) is treated as Australian, matching the pre-existing default."""
    return country is not None and country.strip().lower() != "australia"


def franking_percentage_for(snapshot, country: str | None) -> Decimal:
    if is_foreign(country):
        return FOREIGN_FRANKING_PERCENTAGE
    return snapshot.franking_percentage or DEFAULT_FRANKING_PERCENTAGE


def upsert_financial_report(session: Session, company_id, snapshot, country: str | None = None) -> None:
    values = dict(
        company_id=company_id,
        fiscal_year=snapshot.fiscal_year,
        period_type=snapshot.period_type,
        report_date=snapshot.report_date,
        revenue=snapshot.revenue,
        ebit=snapshot.ebit,
        net_profit_after_tax=snapshot.net_profit_after_tax,
        operating_cash_flow=snapshot.operating_cash_flow,
        free_cash_flow=snapshot.free_cash_flow,
        capital_expenditure=snapshot.capital_expenditure,
        eps=snapshot.eps,
        total_assets=snapshot.total_assets,
        total_liabilities=snapshot.total_liabilities,
        total_equity=snapshot.total_equity,
        total_debt=snapshot.total_debt,
        cash_and_equivalents=snapshot.cash_and_equivalents,
        net_tangible_assets=snapshot.net_tangible_assets,
        dividends_per_share=snapshot.dividends_per_share,
        abnormal_distributions_per_share=snapshot.abnormal_distributions_per_share,
        reporting_currency=snapshot.reporting_currency,
        fx_rate=snapshot.fx_rate,
        franking_percentage=franking_percentage_for(snapshot, country),
        corporate_tax_rate=snapshot.corporate_tax_rate or DEFAULT_CORPORATE_TAX_RATE,
    )

    stmt = insert(FinancialReport).values(**values)
    set_ = {"report_date": stmt.excluded.report_date}
    for col in _COALESCE_ON_UPDATE:
        set_[col] = func.coalesce(getattr(stmt.excluded, col), getattr(FinancialReport, col))
    # A foreign domicile is a definite answer, so it corrects years already
    # stored at the old 100% default. Australian rows are left alone on
    # update so a hand-corrected partial franking figure survives re-runs.
    if is_foreign(country):
        set_["franking_percentage"] = stmt.excluded.franking_percentage
    stmt = stmt.on_conflict_do_update(
        index_elements=[FinancialReport.company_id, FinancialReport.fiscal_year, FinancialReport.period_type],
        set_=set_,
    )
    session.execute(stmt)


def upsert_dividend_payments(session: Session, company_id, payments) -> None:
    """Store each payment by ex-date, flagging abnormal one-offs with the
    same rule the per-year figures use. Re-ingestion refreshes amount and
    flag, so a reclassification is picked up."""
    if not payments:
        return
    _, abnormal = split_abnormal(payments)
    abnormal_dates = {p.ex_date for p in abnormal}
    for p in payments:
        stmt = insert(DividendPayment).values(company_id=company_id, ex_date=p.ex_date, amount=p.amount,
                                              abnormal=p.ex_date in abnormal_dates)
        stmt = stmt.on_conflict_do_update(index_elements=[DividendPayment.company_id, DividendPayment.ex_date],
                                          set_={"amount": stmt.excluded.amount, "abnormal": stmt.excluded.abnormal})
        session.execute(stmt)


def convert_to_trading_currency(client, company, snapshots) -> None:
    """Statements in another currency (US dollars for most big miners, NZ
    dollars for NZ listings) are converted at each balance date's exchange
    rate before storing, so every per-share figure is comparable with the
    share price. Raises CurrencyConversionError if no rate is available,
    which skips this company for the run rather than storing figures in
    the wrong currency. See src/ingestion/currency.py."""
    if not snapshots:
        return
    reporting = company.financial_currency or company.trading_currency or "AUD"
    trading = company.trading_currency or "AUD"
    closes = []
    if reporting != trading:
        dates = [s.report_date for s in snapshots]
        closes = client.get_fx_history(reporting, trading, min(dates) - timedelta(days=15), max(dates) + timedelta(days=2))
    apply_conversion(snapshots, reporting, trading, closes)


def ingest_fundamentals(
    session: Session, asx_codes: list[str], max_years: int = 4, delay_seconds: float = 0.0
) -> dict[str, int]:
    """Ingest up to `max_years` of annual financial reports for each ASX
    code, including per-share dividends for each fiscal year. Returns
    {asx_code: number of fiscal-year reports upserted}.

    Each ticker is isolated in its own try/except (see
    `price_ingestion.ingest_daily_prices` for why this matters at scale).
    `delay_seconds` paces requests between tickers to reduce the chance of
    Yahoo rate-limiting a large batch.

    Dividends per share are matched to each financial year, with abnormal
    one-off distributions (e.g. a capital return recorded as a dividend)
    held out - see src/ingestion/dividend_history.py."""
    results: dict[str, int] = {}
    total = len(asx_codes)
    for i, asx_code in enumerate(asx_codes, start=1):
        try:
            client = YahooClient(asx_code)
            company = get_or_create_company(session, asx_code, client=client)
            ensure_profile(company, client)
            snapshots = client.get_annual_fundamentals(max_years=max_years)
            convert_to_trading_currency(client, company, snapshots)
            payments = client.get_dividend_payments()
            upsert_dividend_payments(session, company.company_id, payments)
            for snapshot in snapshots:
                if snapshot.dividends_per_share is None:
                    fy = dividends_for_fiscal_year(payments, snapshot.report_date, date.today())
                    snapshot.dividends_per_share = fy.ordinary
                    snapshot.abnormal_distributions_per_share = fy.abnormal if fy.ordinary is not None else None
                upsert_financial_report(session, company.company_id, snapshot, company.country)
            session.commit()
            logger.info("[%d/%d] Ingested %d annual reports for %s", i, total, len(snapshots), asx_code)
            results[asx_code] = len(snapshots)
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Fundamentals ingestion failed for %s - skipping", i, total, asx_code)
            results[asx_code] = 0
        if delay_seconds and i < total:
            time.sleep(delay_seconds)
    return results
