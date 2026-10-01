#!/usr/bin/env python3
"""ASX value screener - Graham/Buffett-style CLI.

Queries the `asx_value_screener` view (see `db/schema.sql`) - the latest
price joined to the latest valuation_metrics row per company - and lists
companies clearing all four classic value criteria:

    Margin of Safety      > 20%
    ROE                   > 12%
    Debt to Equity        < 0.80
    Grossed-Up Div. Yield > 4.5%

Run `python -m src.ingestion.run_ingestion` and
`python -m src.valuation.run_valuation` first to populate the database.

Usage:
    python screen_asx.py
    python screen_asx.py --min-roe 15 --min-yield 5 --sector Financials
    python screen_asx.py --limit 10 --any-of   # match any criterion instead of all
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import text
from tabulate import tabulate

from src.config import get_session

DEFAULT_MIN_MARGIN_OF_SAFETY = Decimal("20")
DEFAULT_MIN_ROE = Decimal("12")
DEFAULT_MAX_DEBT_TO_EQUITY = Decimal("0.80")
DEFAULT_MIN_GROSSED_UP_YIELD = Decimal("4.5")

COLUMNS = [
    "asx_code", "company_name", "sector", "current_price",
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "grossed_up_dividend_yield", "payout_ratio", "margin_of_safety_percent",
    "valuation_method",
]

# A payout ratio well over 100% means the latest dividend exceeded that
# year's earnings - usually a special/one-off distribution rather than a
# sustainable, repeatable payout. The yield is still shown (not hidden or
# nulled), but flagged here so it isn't mistaken for ordinary income.
PAYOUT_RATIO_WARNING_THRESHOLD = Decimal("150")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen ASX companies for classic value criteria.")
    parser.add_argument("--min-margin-of-safety", type=Decimal, default=DEFAULT_MIN_MARGIN_OF_SAFETY,
                         help=f"minimum margin of safety %% (default: {DEFAULT_MIN_MARGIN_OF_SAFETY})")
    parser.add_argument("--min-roe", type=Decimal, default=DEFAULT_MIN_ROE,
                         help=f"minimum return on equity %% (default: {DEFAULT_MIN_ROE})")
    parser.add_argument("--max-debt-equity", type=Decimal, default=DEFAULT_MAX_DEBT_TO_EQUITY,
                         help=f"maximum debt/equity ratio (default: {DEFAULT_MAX_DEBT_TO_EQUITY})")
    parser.add_argument("--min-yield", type=Decimal, default=DEFAULT_MIN_GROSSED_UP_YIELD,
                         help=f"minimum grossed-up dividend yield %% (default: {DEFAULT_MIN_GROSSED_UP_YIELD})")
    parser.add_argument("--sector", help="restrict to a single sector (exact match)")
    parser.add_argument("--any-of", action="store_true",
                         help="match companies passing ANY criterion instead of requiring ALL four")
    parser.add_argument("--limit", type=int, default=25, help="max rows to display (default: 25)")
    return parser.parse_args(argv)


def build_query(args: argparse.Namespace) -> tuple[str, dict]:
    criteria = [
        "margin_of_safety_percent > :min_mos",
        "roe > :min_roe",
        "debt_to_equity < :max_de",
        "grossed_up_dividend_yield > :min_yield",
    ]
    joiner = " OR " if args.any_of else " AND "

    # Each criterion column can be NULL (a company missing that input metric) -
    # NULL comparisons are false either way in SQL, so incomplete data simply
    # fails the screen rather than raising, which is what we want here.
    where_clauses = [f"({joiner.join(criteria)})"]
    params: dict = {
        "min_mos": args.min_margin_of_safety,
        "min_roe": args.min_roe,
        "max_de": args.max_debt_equity,
        "min_yield": args.min_yield,
    }

    if args.sector:
        where_clauses.append("sector = :sector")
        params["sector"] = args.sector

    query = f"""
        SELECT {', '.join(COLUMNS)}
        FROM asx_value_screener
        WHERE {' AND '.join(where_clauses)}
        ORDER BY margin_of_safety_percent DESC NULLS LAST
        LIMIT :limit
    """
    params["limit"] = args.limit
    return query, params


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query, params = build_query(args)

    with get_session() as session:
        rows = session.execute(text(query), params).mappings().all()

    if not rows:
        print("No companies matched the given criteria.")
        return 0

    print(tabulate(rows, headers="keys", floatfmt=".2f", tablefmt="simple"))
    print(f"\n{len(rows)} companies matched.")

    flagged = [r["asx_code"] for r in rows if r["payout_ratio"] is not None and r["payout_ratio"] > PAYOUT_RATIO_WARNING_THRESHOLD]
    if flagged:
        print(
            f"\n⚠ Payout ratio > {PAYOUT_RATIO_WARNING_THRESHOLD}% for: {', '.join(flagged)} — "
            "the dividend yield shown likely reflects a one-off/special dividend rather than "
            "sustainable income. Verify against the company's actual dividend history before relying on it."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
