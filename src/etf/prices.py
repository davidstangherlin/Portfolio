"""Nightly ETF prices and distributions from Yahoo Finance
(docs/AS_BUILT.md §25).

One request per ETF brings its closes, splits and distributions. An ETF
with no stored prices gets its full history (the one-off backfill behind
the 3, 5 and 10-year returns); after that, the last month. Distributions
go into dividend_payments, all counted: unlike company dividends there's
no "abnormal" one-off to hold out, since a fund's year-end distribution of
gains is part of its return.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert

from src.ingestion.price_ingestion import FULL_HISTORY, fetch_bars, upsert_daily_prices
from src.ingestion.yahoo_client import YahooClient
from src.models import Company, DailyPrice, DividendPayment

logger = logging.getLogger(__name__)


def active_etfs(session, codes: list[str] | None = None) -> list[tuple[Company, bool]]:
    """(ETF, whether it has any stored prices), for every active ETF or the
    codes given."""
    has_prices = exists().where(DailyPrice.company_id == Company.company_id)
    stmt = select(Company, has_prices).where(Company.security_type == "ETF")
    stmt = stmt.where(Company.asx_code.in_(codes)) if codes else stmt.where(Company.is_active.is_(True))
    return [(c, bool(h)) for c, h in session.execute(stmt.order_by(Company.asx_code)).all()]


def upsert_distributions(session, company_id, payments, replace: bool = False) -> None:
    if replace:
        session.execute(delete(DividendPayment).where(DividendPayment.company_id == company_id))
    for p in payments:
        stmt = insert(DividendPayment).values(company_id=company_id, ex_date=p.ex_date, amount=p.amount, abnormal=False)
        session.execute(stmt.on_conflict_do_update(index_elements=[DividendPayment.company_id, DividendPayment.ex_date],
                                                   set_={"amount": stmt.excluded.amount, "abnormal": False}))


def ingest_etf_prices(session, codes: list[str] | None = None, period: str = "1mo",
                      delay_seconds: float = 0.0, client_factory=YahooClient) -> dict[str, int]:
    """Prices and distributions for each ETF. Returns {code: bars stored}.
    Each ETF is committed on its own; a failure is logged and skipped."""
    etfs = active_etfs(session, codes)
    results: dict[str, int] = {}
    for i, (company, has_prices) in enumerate(etfs, start=1):
        code = company.asx_code
        try:
            client = client_factory(code)
            bars, full = fetch_bars(session, client, company, period if has_prices else FULL_HISTORY,
                                    include_market_cap=False)
            upsert_daily_prices(session, company.company_id, bars)
            # A full fetch carries every distribution, split-adjusted to match.
            upsert_distributions(session, company.company_id, client.last_dividends, replace=full and bool(bars))
            session.commit()
            logger.info("[%d/%d] %s: %d price bars, %d distributions%s", i, len(etfs), code, len(bars),
                        len(client.last_dividends), " (full history)" if full else "")
            results[code] = len(bars)
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] ETF price ingestion failed for %s - skipping", i, len(etfs), code)
            results[code] = 0
        if delay_seconds and i < len(etfs):
            time.sleep(delay_seconds)
    return results
