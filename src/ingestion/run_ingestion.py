"""CLI: pull daily prices and/or annual fundamentals from Yahoo Finance for
a list of ASX codes and load them into the database.

Usage:
    python -m src.ingestion.run_ingestion --tickers BHP CGF WES
    python -m src.ingestion.run_ingestion --tickers BHP --prices-only --period 1y
    python -m src.ingestion.run_ingestion --tickers BHP --fundamentals-only --max-years 6
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import get_session
from src.ingestion.fundamentals_ingestion import ingest_fundamentals
from src.ingestion.price_ingestion import ingest_daily_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest ASX price and fundamentals data from Yahoo Finance.")
    parser.add_argument("--tickers", nargs="+", required=True, help="ASX codes, e.g. BHP CGF WES (no .AX suffix)")
    parser.add_argument("--period", default="1mo", help="yfinance history period for prices (default: 1mo)")
    parser.add_argument("--max-years", type=int, default=4, help="years of annual fundamentals to pull (default: 4)")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prices-only", action="store_true", help="ingest daily prices only")
    mode.add_argument("--fundamentals-only", action="store_true", help="ingest annual fundamentals only")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers]

    with get_session() as session:
        if not args.fundamentals_only:
            price_results = ingest_daily_prices(session, tickers, period=args.period)
            logger.info("Price ingestion complete: %s", price_results)

        if not args.prices_only:
            fundamentals_results = ingest_fundamentals(session, tickers, max_years=args.max_years)
            logger.info("Fundamentals ingestion complete: %s", fundamentals_results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
