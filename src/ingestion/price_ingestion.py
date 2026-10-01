"""Ingest daily price history from Yahoo Finance into `daily_prices`."""

from __future__ import annotations

import logging
import time

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.ingestion.common import get_or_create_company
from src.ingestion.yahoo_client import YahooClient
from src.models import DailyPrice

logger = logging.getLogger(__name__)


def upsert_daily_price(session: Session, company_id, bar) -> None:
    stmt = insert(DailyPrice).values(
        company_id=company_id,
        price_date=bar.price_date,
        close_price=bar.close_price,
        volume=bar.volume,
        market_cap=bar.market_cap,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyPrice.company_id, DailyPrice.price_date],
        set_={
            "close_price": stmt.excluded.close_price,
            "volume": stmt.excluded.volume,
            "market_cap": stmt.excluded.market_cap,
        },
    )
    session.execute(stmt)


def ingest_daily_prices(
    session: Session, asx_codes: list[str], period: str = "1mo", delay_seconds: float = 0.0
) -> dict[str, int]:
    """Ingest `period` worth of daily prices for each ASX code.
    Returns {asx_code: number of bars upserted}.

    Each ticker is isolated in its own try/except: an unexpected failure
    (network blip, a malformed response, a DB error) logs and moves on to
    the next ticker rather than aborting the whole batch - important once
    `asx_codes` is large (e.g. a few hundred tickers), where hitting at
    least one edge case over the run is likely. `delay_seconds` paces
    requests between tickers to reduce the chance of Yahoo rate-limiting
    a large batch (yfinance has no official rate-limit guarantee)."""
    results: dict[str, int] = {}
    total = len(asx_codes)
    for i, asx_code in enumerate(asx_codes, start=1):
        try:
            client = YahooClient(asx_code)
            company = get_or_create_company(session, asx_code, client=client)
            bars = client.get_price_history(period=period)
            for bar in bars:
                upsert_daily_price(session, company.company_id, bar)
            session.commit()
            logger.info("[%d/%d] Ingested %d price bars for %s", i, total, len(bars), asx_code)
            results[asx_code] = len(bars)
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Price ingestion failed for %s - skipping", i, total, asx_code)
            results[asx_code] = 0
        if delay_seconds and i < total:
            time.sleep(delay_seconds)
    return results
