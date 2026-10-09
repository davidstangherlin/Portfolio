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

Decision markers (earnings_quality, price_signal, dividend_trend,
data_confidence - see src/valuation/markers.py) and a suggested `action`
for every company (src/screening/actions.py) sit alongside. Shares you hold
(portfolio.py) get SELL / REVIEW / ACCUMULATE / HOLD; everything else BUY / INVESTIGATE /
WATCH / AVOID / IGNORE. --actions prints a grouped report with the reason
behind each action instead of the full table.

Run `python -m src.ingestion.run_ingestion` and
`python -m src.valuation.run_valuation` first to populate the database.

Usage:
    python screen_asx.py
    python screen_asx.py --min-roe 15 --min-yield 5 --sector Financials
    python screen_asx.py --passing-only              # old behaviour: only rows passing all four
    python screen_asx.py --passing-only --any-of      # ...passing any one of the four
    python screen_asx.py --rank-by momentum           # "catch it before others" ranking
    python screen_asx.py --limit 10                   # cap rows shown (default: no limit)
    python screen_asx.py --actions                    # grouped action report with reasons
    python screen_asx.py --actions --held             # just the shares you hold
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from tabulate import tabulate

from src.config import get_session
from src.portfolio.holdings import PositionSummary, position_summaries
from src.screening.actions import ACTION_ORDER, HELD_ACTIONS, suggest_action
from src.settings import LIVE, ModelSettings
from src.valuation import markers
from src.valuation.engine import DEFAULT_TREND_DAYS

# Live thresholds come from the settings registry (src/settings.py).
DEFAULT_MIN_MARGIN_OF_SAFETY = LIVE.min_margin_of_safety
DEFAULT_MIN_ROE = LIVE.min_roe
DEFAULT_MAX_DEBT_TO_EQUITY = LIVE.max_debt_equity
DEFAULT_MIN_GROSSED_UP_YIELD = LIVE.min_yield
DEFAULT_MIN_MOS_TREND = LIVE.min_mos_trend  # percentage points improvement over ~trend_days to count as "momentum"

COLUMNS = [
    "asx_code", "company_name", "sector", "current_price",
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "grossed_up_dividend_yield", "payout_ratio", "margin_of_safety_percent",
    "valuation_method", "margin_of_safety_trend", "fundamentals_trend",
    "cash_conversion", "earnings_quality", "price_vs_200d", "range_position_52w",
    "dividend_trend", "data_confidence",
]

# The full table: raw marker inputs (cash_conversion, price_vs_200d,
# range_position_52w) are summarised by their labels here and stay in the
# database for anyone who wants the numbers.
DISPLAY_COLUMNS = [
    "asx_code", "company_name", "sector", "current_price",
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "grossed_up_dividend_yield", "payout_ratio", "margin_of_safety_percent",
    "valuation_method", "margin_of_safety_trend", "fundamentals_trend",
    "earnings_quality", "price_signal", "dividend_trend", "data_confidence",
    "mos_ok", "roe_ok", "de_ok", "yield_ok", "overall", "momentum_ok", "trap_risk",
    "held", "action",
]
COMPANY_NAME_WIDTH = 32

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
PAYOUT_RATIO_WARNING_THRESHOLD = LIVE.payout_warning


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
    parser.add_argument("--actions", action="store_true",
                         help="print a report grouped by suggested action, with the reason for each, instead of the full table")
    parser.add_argument("--held", action="store_true", help="only companies you hold (see portfolio.py)")
    return parser.parse_args(argv)


def args_from_settings(settings: ModelSettings) -> argparse.Namespace:
    """The screener's default arguments with the value tests and momentum
    threshold taken from `settings` (the admin console's what-if lab)."""
    args = parse_args([])
    args.min_margin_of_safety, args.min_roe = settings.min_margin_of_safety, settings.min_roe
    args.max_debt_equity, args.min_yield = settings.max_debt_equity, settings.min_yield
    args.min_mos_trend = settings.min_mos_trend
    return args


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


def annotate_row(
    row: dict, args: argparse.Namespace, position: PositionSummary | None = None, today: date | None = None,
    settings: ModelSettings = LIVE,
) -> dict:
    """Adds one Y/N indicator column per criterion plus an 'overall' column
    (AND of all four, or OR if --any-of), without removing or hiding the
    row itself - see module docstring for why this replaced filtering.
    Also adds momentum_ok (margin_of_safety_trend-based) and trap_risk
    (mos_ok cheap but fundamentals_trend declining) - both informational,
    deliberately excluded from 'overall' since they answer a different
    question than the core four-criterion value screen - then the
    price_signal label, units held, and the suggested action and reason."""
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
    annotated["price_signal"] = markers.price_signal(row["price_vs_200d"], row["range_position_52w"], settings.new_lows_range)
    annotated["held"] = position.units if position else None
    annotated["action"], annotated["action_reason"] = suggest_action(annotated, position, today, settings)
    return annotated


def _short_name(name: str | None) -> str | None:
    if name and len(name) > COMPANY_NAME_WIDTH:
        return name[:COMPANY_NAME_WIDTH - 3] + "..."
    return name


def print_action_report(rows: list[dict], positions: dict[str, PositionSummary], show_unscreened_holdings: bool) -> None:
    for action in ACTION_ORDER:
        group = [r for r in rows if r["action"] == action]
        if not group or action == "IGNORE":
            continue
        held_group = action in HELD_ACTIONS
        table = []
        for r in group:
            line = {"asx_code": r["asx_code"], "company": _short_name(r["company_name"]),
                    "price": r["current_price"], "mos_%": r["margin_of_safety_percent"]}
            if held_group:
                line["held"] = r["held"]
            line["reason"] = r["action_reason"]
            table.append(line)
        print(f"\n{action} ({len(group)})")
        print(tabulate(table, headers="keys", floatfmt=".2f", tablefmt="simple",
                       maxcolwidths=[None] * (len(table[0]) - 1) + [70]))

    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ACTION_ORDER}
    print("\n" + ", ".join(f"{a} {n}" for a, n in counts.items() if n) + " (IGNORE = no value signal, not listed)")

    if show_unscreened_holdings:
        unscreened = sorted(set(positions) - {r["asx_code"] for r in rows})
        if unscreened:
            print(f"\nHeld but not screened (add to your watchlist file so they get valued): {', '.join(unscreened)}")
    print("\nSuggested actions are rule-based research prompts, not financial advice.")


def load_annotated_rows(session, args: argparse.Namespace, today: date,
                        positions: dict[str, PositionSummary] | None = None) -> tuple[list[dict], dict[str, PositionSummary]]:
    """Every screened company with its Y/N indicators, markers and suggested
    action - the single source both this CLI and the web GUI (gui.py) read,
    so the two can never disagree. Actions are for the current user's
    holdings unless `positions` is given ({} for someone holding nothing)."""
    query, params = build_query(args)
    rows = session.execute(text(query), params).mappings().all()
    if positions is None:
        positions = position_summaries(session, today)
    return [annotate_row(row, args, positions.get(row["asx_code"]), today) for row in rows], positions


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = date.today()

    with get_session() as session:
        annotated_rows, positions = load_annotated_rows(session, args, today)

    if args.passing_only:
        annotated_rows = [r for r in annotated_rows if r["overall"] == "Y"]
    if args.held:
        annotated_rows = [r for r in annotated_rows if r["held"] is not None]

    if not annotated_rows:
        print("No companies found - check --sector/--passing-only/--held, or that run_valuation has been run.")
        return 0

    if args.actions:
        print_action_report(annotated_rows, positions, show_unscreened_holdings=not (args.sector or args.limit))
        return 0

    table = [{col: r[col] for col in DISPLAY_COLUMNS} | {"company_name": _short_name(r["company_name"])}
             for r in annotated_rows]
    print(tabulate(table, headers="keys", floatfmt=".2f", tablefmt="simple"))
    passing = sum(1 for r in annotated_rows if r["overall"] == "Y")
    print(f"\n{len(annotated_rows)} companies shown, {passing} passing ({'any' if args.any_of else 'all'} of the four criteria).")

    flagged = [r["asx_code"] for r in annotated_rows if r["payout_ratio"] is not None and r["payout_ratio"] > PAYOUT_RATIO_WARNING_THRESHOLD]
    if flagged:
        print(
            f"\n⚠ Payout ratio > {PAYOUT_RATIO_WARNING_THRESHOLD}% for: {', '.join(flagged)} - "
            "the dividend yield shown likely reflects a one-off/special dividend rather than "
            "sustainable income. Verify against the company's actual dividend history before relying on it."
        )

    trapped = [r["asx_code"] for r in annotated_rows if r["trap_risk"] == "Y"]
    if trapped:
        print(
            f"\n⚠ Potential value trap for: {', '.join(trapped)} - margin of safety looks attractive, "
            "but ROE/revenue have been trending down across the recent financial-report history. "
            "Worth checking why it's cheap before assuming the market has simply mispriced it."
        )

    print("\nRun with --actions for the suggested action and reason for each company.")

    if not any(r["margin_of_safety_trend"] is not None for r in annotated_rows):
        print(
            f"\nNote: margin_of_safety_trend/momentum_ok are blank for every company - this needs roughly "
            f"{DEFAULT_TREND_DAYS} days of accumulated daily valuation history (see scripts/daily_refresh.ps1) "
            "before it can populate. Expected early on, not a bug."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
