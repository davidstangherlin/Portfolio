"""Ingest daily price history from Yahoo Finance into `daily_prices`."""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from sqlalchemy import delete, select
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


BATCH = 1000


def upsert_daily_prices(session: Session, company_id, bars) -> None:
    """upsert_daily_price() for many bars, a thousand rows per statement
    (a full ETF history is thousands of rows)."""
    for start in range(0, len(bars), BATCH):
        stmt = insert(DailyPrice).values([
            {"company_id": company_id, "price_date": b.price_date, "close_price": b.close_price,
             "volume": b.volume, "market_cap": b.market_cap} for b in bars[start:start + BATCH]])
        session.execute(stmt.on_conflict_do_update(
            index_elements=[DailyPrice.company_id, DailyPrice.price_date],
            set_={"close_price": stmt.excluded.close_price, "volume": stmt.excluded.volume,
                  "market_cap": stmt.excluded.market_cap}))


FULL_HISTORY = "max"
SPLIT_TOLERANCE = Decimal("0.01")


def _history_matches(session, company, bars, splits) -> bool:
    """Whether the stored closes before the earliest split already agree
    with the newly fetched split-adjusted ones (true once a split has been
    refetched, so it's done once, not every night it stays in the window)."""
    first_split = min(d for d, _ in splits)
    before = [b for b in bars if b.price_date < first_split]
    if not before:
        return False
    bar = before[-1]
    stored = session.execute(select(DailyPrice.close_price).where(
        DailyPrice.company_id == company.company_id, DailyPrice.price_date == bar.price_date)).scalar_one_or_none()
    return stored is not None and abs(stored - bar.close_price) <= bar.close_price * SPLIT_TOLERANCE


def fetch_bars(session, client: YahooClient, company, period: str, include_market_cap: bool = True):
    """Fetch `period` of prices; returns (bars, whether they're the full
    history). A split in that period changes every earlier split-adjusted
    close, so the stored history is replaced with a full refetch rather
    than left half-adjusted."""
    bars = client.get_price_history(period=period, include_market_cap=include_market_cap)
    if client.last_splits and period != FULL_HISTORY and not _history_matches(session, company, bars, client.last_splits):
        logger.info("%s split %s: refetching its full price history", client.asx_code,
                    ", ".join(f"{d} ({r})" for d, r in client.last_splits))
        full = client.get_price_history(period=FULL_HISTORY, include_market_cap=include_market_cap)
        if full:
            session.execute(delete(DailyPrice).where(DailyPrice.company_id == company.company_id))
            return full, True
    return bars, period == FULL_HISTORY


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
            bars, _ = fetch_bars(session, client, company, period)
            upsert_daily_prices(session, company.company_id, bars)
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
