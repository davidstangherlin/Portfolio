"""Ingest annual financial-report history from Yahoo Finance into
`financial_reports`.

Franking percentage and the corporate tax rate are not available from
Yahoo Finance - they default to fully franked (100%) at the standard
30% Australian corporate rate, which holds for the large majority of
established ASX-listed companies but should be corrected by hand for
anything known to pay partly-franked or unfranked dividends.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.ingestion.common import get_or_create_company
from src.ingestion.yahoo_client import YahooClient
from src.models import FinancialReport

logger = logging.getLogger(__name__)

DEFAULT_FRANKING_PERCENTAGE = Decimal("100.0")
DEFAULT_CORPORATE_TAX_RATE = Decimal("30.0")

# Columns that may legitimately be missing on any given Yahoo pull (a
# transient gap, a field Yahoo doesn't report for this company). On
# conflict, keep the existing stored value rather than blanking it out
# when the latest fetch didn't return one.
_COALESCE_ON_UPDATE = (
    "revenue", "ebit", "net_profit_after_tax", "operating_cash_flow",
    "free_cash_flow", "capital_expenditure", "eps",
    "total_assets", "total_liabilities", "total_equity", "total_debt",
    "cash_and_equivalents", "net_tangible_assets", "dividends_per_share",
)


def upsert_financial_report(session: Session, company_id, snapshot) -> None:
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
        franking_percentage=snapshot.franking_percentage or DEFAULT_FRANKING_PERCENTAGE,
        corporate_tax_rate=snapshot.corporate_tax_rate or DEFAULT_CORPORATE_TAX_RATE,
    )

    stmt = insert(FinancialReport).values(**values)
    set_ = {"report_date": stmt.excluded.report_date}
    for col in _COALESCE_ON_UPDATE:
        set_[col] = func.coalesce(getattr(stmt.excluded, col), getattr(FinancialReport, col))
    stmt = stmt.on_conflict_do_update(
        index_elements=[FinancialReport.company_id, FinancialReport.fiscal_year, FinancialReport.period_type],
        set_=set_,
    )
    session.execute(stmt)


def ingest_fundamentals(
    session: Session, asx_codes: list[str], max_years: int = 4, delay_seconds: float = 0.0
) -> dict[str, int]:
    """Ingest up to `max_years` of annual financial reports for each ASX
    code, including per-share dividends for each fiscal year. Returns
    {asx_code: number of fiscal-year reports upserted}.

    Each ticker is isolated in its own try/except (see
    `price_ingestion.ingest_daily_prices` for why this matters at scale).
    `delay_seconds` paces requests between tickers to reduce the chance of
    Yahoo rate-limiting a large batch."""
    results: dict[str, int] = {}
    total = len(asx_codes)
    for i, asx_code in enumerate(asx_codes, start=1):
        try:
            client = YahooClient(asx_code)
            company = get_or_create_company(session, asx_code, client=client)
            snapshots = client.get_annual_fundamentals(max_years=max_years)
            for snapshot in snapshots:
                if snapshot.dividends_per_share is None:
                    snapshot.dividends_per_share = client.get_dividends_per_share(snapshot.fiscal_year)
                upsert_financial_report(session, company.company_id, snapshot)
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
