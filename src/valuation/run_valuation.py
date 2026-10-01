"""CLI: compute valuation metrics (ratios, grossed-up yield, Graham
Number, 2-stage DCF/DDM intrinsic value, margin of safety) from the latest
ingested prices and financial reports, and upsert them into
`valuation_metrics`. Financial Services and Real Estate companies are
priced with a Dividend Discount Model instead of the standard DCF - see
docs/AS_BUILT.md known-issue #8.

Run this after `src.ingestion.run_ingestion` and before `screen_asx.py`.

Usage:
    python -m src.valuation.run_valuation --all
    python -m src.valuation.run_valuation --tickers BHP CGF WES
    python -m src.valuation.run_valuation --all --growth-rate 0.06 --discount-rate 0.10
    python -m src.valuation.run_valuation --all --fcf-average-years 1  # old single-year DCF/DDM base
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal

from src.config import get_session
from src.valuation import dcf as dcf_module
from src.valuation import ddm as ddm_module
from src.valuation.engine import DEFAULT_FCF_AVERAGE_YEARS, DEFAULT_TREND_DAYS, run_valuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute and store ASX valuation metrics.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tickers", nargs="+", help="ASX codes to (re)value, e.g. BHP CGF WES")
    scope.add_argument("--all", action="store_true", help="(re)value every active company")

    parser.add_argument("--growth-rate", type=Decimal, default=None,
                         help="stage-1 growth rate (FCF for most sectors, dividends for Financial "
                              "Services/Real Estate - see docs/AS_BUILT.md known-issue #8). Left unset, "
                              f"each model uses its own default: {dcf_module.DEFAULT_GROWTH_RATE} (DCF) / "
                              f"{ddm_module.DEFAULT_GROWTH_RATE} (DDM); pass a value to apply the same "
                              "rate to both")
    parser.add_argument("--discount-rate", type=Decimal, default=dcf_module.DEFAULT_DISCOUNT_RATE,
                         help=f"discount rate, e.g. 0.09 (baseline 8-10%%; default: {dcf_module.DEFAULT_DISCOUNT_RATE})")
    parser.add_argument("--terminal-growth-rate", type=Decimal, default=dcf_module.DEFAULT_TERMINAL_GROWTH_RATE,
                         help=f"terminal growth rate (default: {dcf_module.DEFAULT_TERMINAL_GROWTH_RATE})")
    parser.add_argument("--stage1-years", type=int, default=dcf_module.DEFAULT_STAGE1_YEARS,
                         help=f"stage-1 forecast horizon in years (default: {dcf_module.DEFAULT_STAGE1_YEARS})")
    parser.add_argument("--fcf-average-years", type=int, default=DEFAULT_FCF_AVERAGE_YEARS,
                         help="years of free cash flow to average as the DCF base, smooths single-year "
                              f"volatility (default: {DEFAULT_FCF_AVERAGE_YEARS}; use 1 for old single-year behaviour)")
    parser.add_argument("--trend-days", type=int, default=DEFAULT_TREND_DAYS,
                         help="lookback window in days for margin_of_safety_trend ('momentum into value' - "
                              f"see docs/AS_BUILT.md §8.6) (default: {DEFAULT_TREND_DAYS}; needs that many "
                              "days of accumulated daily valuation history before it populates - run via "
                              "scripts/daily_refresh.ps1)")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers] if args.tickers else None

    with get_session() as session:
        results = run_valuation(
            session,
            asx_codes=tickers,
            fcf_average_years=args.fcf_average_years,
            trend_days=args.trend_days,
            growth_rate=args.growth_rate,
            discount_rate=args.discount_rate,
            terminal_growth_rate=args.terminal_growth_rate,
            stage1_years=args.stage1_years,
        )

    for asx_code, metrics in results.items():
        logger.info(
            "%s: MoS=%s%% (trend=%s) ROE=%s%% D/E=%s GrossYield=%s%% Fundamentals=%s",
            asx_code,
            metrics["margin_of_safety_percent"],
            metrics["margin_of_safety_trend"],
            metrics["roe"],
            metrics["debt_to_equity"],
            metrics["grossed_up_dividend_yield"],
            metrics["fundamentals_trend"],
        )
    logger.info("Valued %d companies", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
