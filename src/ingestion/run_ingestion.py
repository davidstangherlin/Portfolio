"""CLI: pull daily prices and/or annual fundamentals from Yahoo Finance for
a list of ASX codes and load them into the database.

Usage:
    python -m src.ingestion.run_ingestion --tickers BHP CGF WES
    python -m src.ingestion.run_ingestion --tickers BHP --prices-only --period 1y
    python -m src.ingestion.run_ingestion --tickers BHP --fundamentals-only --max-years 6
    python -m src.ingestion.run_ingestion --tickers-file watchlist.txt --delay 0.75

A --tickers-file is a plain text file, one ASX code per line (or several
per line, whitespace/comma separated) - blank lines and lines starting
with # are ignored. This is the practical way to run a large watchlist
(e.g. a full index's constituents) rather than typing hundreds of codes
on the command line. --tickers and --tickers-file can be combined; codes
are deduplicated (case-insensitive) across both sources.

For a large batch, --delay (seconds between tickers) is worth setting to
avoid tripping Yahoo's informal rate limiting - there's no official
documented limit, so some trial and error may be needed. Each ticker's
ingestion is isolated: a failure on one ticker is logged and the run
continues with the rest rather than aborting (see
src/ingestion/price_ingestion.py and fundamentals_ingestion.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import get_session
from src.ingestion.fundamentals_ingestion import ingest_fundamentals
from src.ingestion.price_ingestion import ingest_daily_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _read_tickers_file(path: str) -> list[str]:
    tickers: list[str] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()  # strip trailing comments too
        if not line:
            continue
        tickers.extend(part.strip() for part in line.replace(",", " ").split() if part.strip())
    return tickers


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest ASX price and fundamentals data from Yahoo Finance.")
    parser.add_argument("--tickers", nargs="+", default=[], help="ASX codes, e.g. BHP CGF WES (no .AX suffix)")
    parser.add_argument("--tickers-file", help="path to a text file of ASX codes, one or more per line")
    parser.add_argument("--period", default="1mo", help="yfinance history period for prices (default: 1mo)")
    parser.add_argument("--max-years", type=int, default=4, help="years of annual fundamentals to pull (default: 4)")
    parser.add_argument("--delay", type=float, default=0.0,
                         help="seconds to pause between tickers, to ease Yahoo rate limiting on large batches "
                              "(default: 0, no delay)")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prices-only", action="store_true", help="ingest daily prices only")
    mode.add_argument("--fundamentals-only", action="store_true", help="ingest annual fundamentals only")

    args = parser.parse_args(argv)
    if not args.tickers and not args.tickers_file:
        parser.error("provide --tickers, --tickers-file, or both")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers]
    if args.tickers_file:
        tickers.extend(t.upper() for t in _read_tickers_file(args.tickers_file))
    # De-duplicate, preserving first-seen order.
    seen: set[str] = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    logger.info("Ingesting %d ticker(s)%s", len(tickers), f" (delay {args.delay}s between each)" if args.delay else "")

    with get_session() as session:
        if not args.fundamentals_only:
            price_results = ingest_daily_prices(session, tickers, period=args.period, delay_seconds=args.delay)
            failed = [t for t, n in price_results.items() if n == 0]
            logger.info(
                "Price ingestion complete: %d/%d tickers returned data%s",
                len(tickers) - len(failed), len(tickers),
                f" - 0 bars for: {', '.join(failed)}" if failed else "",
            )

        if not args.prices_only:
            fundamentals_results = ingest_fundamentals(
                session, tickers, max_years=args.max_years, delay_seconds=args.delay
            )
            failed = [t for t, n in fundamentals_results.items() if n == 0]
            logger.info(
                "Fundamentals ingestion complete: %d/%d tickers returned data%s",
                len(tickers) - len(failed), len(tickers),
                f" - 0 reports for: {', '.join(failed)}" if failed else "",
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
