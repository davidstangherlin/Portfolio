#!/usr/bin/env python3
"""ASX value screener - Graham/Buffett-style CLI.

Queries the `asx_value_screener` view (see `db/schema.sql`) - the latest
price joined to the latest valuation_metrics row per company - and lists
every company (not just the ones that pass), with a Y/N indicator column
for each of the four classic value criteria:

    Margin of Safety      > 20%
    ROE                   > 12%
    Debt to Equity        < 0.80
    Grossed-Up Div. Yield > 4.5%

Showing every company rather than filtering them out keeps a company with
missing data (NULL on one metric) visible and clearly marked 'N' on that
criterion, instead of silently disappearing - and lets you see *how close*
a company is to passing, not just whether it did. Pass --passing-only to
restore the old filtered-to-matches-only behaviour.

Two additional, informational indicators (not part of 'overall' - these
support a different question, "what's moving", not the core Graham/Buffett
pass/fail):
    momentum_ok  - margin_of_safety_trend has improved by more than
                   --min-mos-trend over the last ~trend_days (set on
                   run_valuation.py) - "getting cheaper", a candidate to
                   catch before the market re-rates it. Blank/NULL until
                   enough daily valuation history has accumulated.
    trap_risk    - mos_ok is Y but fundamentals_trend is DECLINING: looks
                   cheap, but ROE/revenue are heading the wrong way - a
                   candidate value trap, worth checking before assuming
                   it's genuinely mispriced rather than deteriorating.
Pass --rank-by momentum to sort by margin_of_safety_trend instead of the
default (absolute margin of safety).

Run `python -m src.ingestion.run_ingestion` and
`python -m src.valuation.run_valuation` first to populate the database.

Usage:
    python screen_asx.py
    python screen_asx.py --min-roe 15 --min-yield 5 --sector Financials
    python screen_asx.py --passing-only              # old behaviour: only rows passing all four
    python screen_asx.py --passing-only --any-of      # ...passing any one of the four
    python screen_asx.py --rank-by momentum           # "catch it before others" ranking
    python screen_asx.py --limit 10                   # cap rows shown (default: no limit)
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import text
from tabulate import tabulate

from src.config import get_session
from src.valuation.engine import DEFAULT_TREND_DAYS

DEFAULT_MIN_MARGIN_OF_SAFETY = Decimal("20")
DEFAULT_MIN_ROE = Decimal("12")
DEFAULT_MAX_DEBT_TO_EQUITY = Decimal("0.80")
DEFAULT_MIN_GROSSED_UP_YIELD = Decimal("4.5")
DEFAULT_MIN_MOS_TREND = Decimal("5")  # percentage points improvement over ~trend_days to count as "momentum"

COLUMNS = [
    "asx_code", "company_name", "sector", "current_price",
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "grossed_up_dividend_yield", "payout_ratio", "margin_of_safety_percent",
    "valuation_method", "margin_of_safety_trend", "fundamentals_trend",
]

# Each entry: (indicator column name, source column, comparison). Computed
# in Python against every row (not a SQL WHERE filter - see module
# docstring), so a NULL source value and a value that simply fails the
# threshold are both 'N': the point of this table is "does this company
# clear the bar", and a missing metric never clears it either way. These
# four feed 'overall' (the core value screen); momentum_ok/trap_risk below
# are informational and deliberately excluded from 'overall'.
_CRITERIA = [
    ("mos_ok", "margin_of_safety_percent", lambda v, t: v > t),
    ("roe_ok", "roe", lambda v, t: v > t),
    ("de_ok", "debt_to_equity", lambda v, t: v < t),
    ("yield_ok", "grossed_up_dividend_yield", lambda v, t: v > t),
]

# A payout ratio well over 100% means the latest dividend exceeded that
# year's earnings - usually a special/one-off distribution rather than a
# sustainable, repeatable payout. The yield is still shown (not hidden or
# nulled), but flagged here so it isn't mistaken for ordinary income.
PAYOUT_RATIO_WARNING_THRESHOLD = Decimal("150")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen ASX companies for classic value criteria.")
    parser.add_argument("--min-margin-of-safety", type=Decimal, default=DEFAULT_MIN_MARGIN_OF_SAFETY,
                         help=f"margin of safety %% threshold for the mos_ok indicator (default: {DEFAULT_MIN_MARGIN_OF_SAFETY})")
    parser.add_argument("--min-roe", type=Decimal, default=DEFAULT_MIN_ROE,
                         help=f"return on equity %% threshold for the roe_ok indicator (default: {DEFAULT_MIN_ROE})")
    parser.add_argument("--max-debt-equity", type=Decimal, default=DEFAULT_MAX_DEBT_TO_EQUITY,
                         help=f"debt/equity threshold for the de_ok indicator (default: {DEFAULT_MAX_DEBT_TO_EQUITY})")
    parser.add_argument("--min-yield", type=Decimal, default=DEFAULT_MIN_GROSSED_UP_YIELD,
                         help=f"grossed-up dividend yield %% threshold for the yield_ok indicator (default: {DEFAULT_MIN_GROSSED_UP_YIELD})")
    parser.add_argument("--sector", help="restrict to a single sector (exact match) - this is a real filter, unlike the criteria above")
    parser.add_argument("--any-of", action="store_true",
                         help="'overall' column (and --passing-only) requires ANY one criterion instead of ALL four")
    parser.add_argument("--passing-only", action="store_true",
                         help="filter to only companies where 'overall' is Y (the pre-2026-10 behaviour)")
    parser.add_argument("--min-mos-trend", type=Decimal, default=DEFAULT_MIN_MOS_TREND,
                         help="margin_of_safety_trend threshold (percentage points) for the momentum_ok "
                              f"indicator (default: {DEFAULT_MIN_MOS_TREND})")
    parser.add_argument("--rank-by", choices=["margin_of_safety", "momentum"], default="margin_of_safety",
                         help="row order and what --limit caps (default: margin_of_safety - static "
                              "cheapness). 'momentum' ranks by margin_of_safety_trend instead - companies "
                              "getting cheaper fastest, a 'catch it before others' view")
    parser.add_argument("--limit", type=int, default=None, help="max rows to display (default: no limit - show every company)")
    return parser.parse_args(argv)


def build_query(args: argparse.Namespace) -> tuple[str, dict]:
    where_clauses = []
    params: dict = {}

    if args.sector:
        where_clauses.append("sector = :sector")
        params["sector"] = args.sector

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = "LIMIT :limit" if args.limit is not None else ""
    if args.limit is not None:
        params["limit"] = args.limit
    order_col = "margin_of_safety_trend" if args.rank_by == "momentum" else "margin_of_safety_percent"

    query = f"""
        SELECT {', '.join(COLUMNS)}
        FROM asx_value_screener
        {where_sql}
        ORDER BY {order_col} DESC NULLS LAST
        {limit_sql}
    """
    return query, params


def annotate_row(row: dict, args: argparse.Namespace) -> dict:
    """Adds one Y/N indicator column per criterion plus an 'overall' column
    (AND of all four, or OR if --any-of), without removing or hiding the
    row itself - see module docstring for why this replaced filtering.
    Also adds momentum_ok (margin_of_safety_trend-based) and trap_risk
    (mos_ok cheap but fundamentals_trend declining) - both informational,
    deliberately excluded from 'overall' since they answer a different
    question than the core four-criterion value screen."""
    thresholds = {
        "mos_ok": args.min_margin_of_safety,
        "roe_ok": args.min_roe,
        "de_ok": args.max_debt_equity,
        "yield_ok": args.min_yield,
    }
    checks = {}
    for indicator, source_col, compare in _CRITERIA:
        value = row[source_col]
        checks[indicator] = value is not None and compare(value, thresholds[indicator])

    overall = any(checks.values()) if args.any_of else all(checks.values())

    mos_trend = row["margin_of_safety_trend"]
    momentum_ok = mos_trend is not None and mos_trend > args.min_mos_trend
    trap_risk = checks["mos_ok"] and row["fundamentals_trend"] == "DECLINING"

    annotated = dict(row)
    annotated.update({k: ("Y" if v else "N") for k, v in checks.items()})
    annotated["overall"] = "Y" if overall else "N"
    annotated["momentum_ok"] = "Y" if momentum_ok else "N"
    annotated["trap_risk"] = "Y" if trap_risk else "N"
    return annotated


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query, params = build_query(args)

    with get_session() as session:
        rows = session.execute(text(query), params).mappings().all()

    annotated_rows = [annotate_row(row, args) for row in rows]
    if args.passing_only:
        annotated_rows = [r for r in annotated_rows if r["overall"] == "Y"]

    if not annotated_rows:
        print("No companies found - check --sector/--passing-only, or that run_valuation has been run.")
        return 0

    print(tabulate(annotated_rows, headers="keys", floatfmt=".2f", tablefmt="simple"))
    passing = sum(1 for r in annotated_rows if r["overall"] == "Y")
    print(f"\n{len(annotated_rows)} companies shown, {passing} passing ({'any' if args.any_of else 'all'} of the four criteria).")

    flagged = [r["asx_code"] for r in annotated_rows if r["payout_ratio"] is not None and r["payout_ratio"] > PAYOUT_RATIO_WARNING_THRESHOLD]
    if flagged:
        print(
            f"\n⚠ Payout ratio > {PAYOUT_RATIO_WARNING_THRESHOLD}% for: {', '.join(flagged)} — "
            "the dividend yield shown likely reflects a one-off/special dividend rather than "
            "sustainable income. Verify against the company's actual dividend history before relying on it."
        )

    trapped = [r["asx_code"] for r in annotated_rows if r["trap_risk"] == "Y"]
    if trapped:
        print(
            f"\n⚠ Potential value trap for: {', '.join(trapped)} — margin of safety looks attractive, "
            "but ROE/revenue have been trending down across the recent financial-report history. "
            "Worth checking why it's cheap before assuming the market has simply mispriced it."
        )

    if not any(r["margin_of_safety_trend"] is not None for r in annotated_rows):
        print(
            f"\nNote: margin_of_safety_trend/momentum_ok are blank for every company - this needs roughly "
            f"{DEFAULT_TREND_DAYS} days of accumulated daily valuation history (see scripts/daily_refresh.ps1) "
            "before it can populate. Expected early on, not a bug."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
