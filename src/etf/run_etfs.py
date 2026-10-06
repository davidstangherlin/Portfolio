"""CLI: the nightly ETF step, and loading or checking an ASX report by hand
(docs/AS_BUILT.md §25).

Usage:
    python -m src.etf.run_etfs                    # nightly: report if due, prices, performance
    python -m src.etf.run_etfs --report FILE.xlsx [--month 2026-09]
    python -m src.etf.run_etfs --inspect FILE.xlsx
    python -m src.etf.run_etfs --codes VAS IOZ --skip-report

The nightly run checks for last month's ASX Investment Products report
(once it's loaded, no request is made until next month), then fetches
prices and distributions for every active ETF (the full history for any
ETF seen for the first time), then recalculates performance.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from src.config import get_session
from src.etf import asx_report, performance
from src.etf.prices import ingest_etf_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASX ETFs: the ASX report, prices and distributions, performance.")
    parser.add_argument("--report", type=Path, help="load this ASX Investment Products spreadsheet")
    parser.add_argument("--month", help="the month --report covers, YYYY-MM, if its name doesn't say")
    parser.add_argument("--inspect", type=Path, help="show how a spreadsheet is read, without loading it")
    parser.add_argument("--codes", nargs="+", help="only these ETFs (prices and performance)")
    parser.add_argument("--skip-report", action="store_true", help="don't check for a new ASX report")
    parser.add_argument("--skip-prices", action="store_true", help="don't fetch prices and distributions")
    parser.add_argument("--period", default="1mo", help="price history to fetch for ETFs already stored (default 1mo)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between ETFs (default 0.5)")
    return parser.parse_args(argv)


def _month(text: str | None) -> date | None:
    if not text:
        return None
    year, month = text.split("-")
    return date(int(year), int(month), 1)


def _summary(result: asx_report.LoadResult) -> str:
    parts = [f"ASX report for {result.month:%B %Y}: {result.etfs} ETPs"]
    for label, codes in (("new", result.added), ("now ETFs", result.reclassified),
                         ("no longer listed", result.deactivated), ("listed again", result.reactivated)):
        if codes:
            parts.append(f"{label}: {len(codes)} ({', '.join(codes[:15])}{', ...' if len(codes) > 15 else ''})")
    return "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.inspect:
        try:
            print(asx_report.describe(asx_report.read_report(args.inspect, _month(args.month))))
        except asx_report.ReportError as exc:
            print(exc)
            return 1
        return 0

    today = date.today()
    with get_session() as session:
        if args.report:
            try:
                result = asx_report.load_report(session, args.report, _month(args.month))
            except asx_report.ReportError as exc:
                logger.error("%s", exc)
                return 1
            session.commit()
            logger.info(_summary(result))
        elif not args.skip_report:
            try:
                result = asx_report.ensure_latest(session, today)
                session.commit()
                if result:
                    logger.info(_summary(result))
            except Exception:
                session.rollback()
                logger.exception("Loading the ASX report failed - carrying on with prices")

        if not args.skip_prices:
            results = ingest_etf_prices(session, args.codes, period=args.period, delay_seconds=args.delay)
            empty = [c for c, n in results.items() if n == 0]
            logger.info("ETF prices: %d/%d returned data%s", len(results) - len(empty), len(results),
                        f" - none for: {', '.join(empty[:30])}" if empty else "")

        written = performance.update_performance(session)
        session.commit()
        logger.info("ETF performance updated for %d ETFs", written)
        differences = performance.report_differences(session)
        if differences:
            logger.info("1-year return differs from the ASX report by more than 2 points for %d ETFs: %s",
                        len(differences), ", ".join(f"{c} ({ours} vs {theirs})" for c, ours, theirs in differences[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
