"""Screener rows with everything a reader of the whole universe needs:
the screen_asx.py row (indicators, markers, suggested action), plus the
valuation_metrics columns the screener view doesn't carry, the score
wheel, and the valuation status.

One loader shared by the web GUI (gui.py) and the nightly signal recorder
(src/tracking/signals.py), so what Sift shows and what the track record
measures are always the same rows under the same rules.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text

from screen_asx import load_annotated_rows, parse_args as screener_defaults
from src.models import Company, FinancialReport
from src.portfolio.holdings import PositionSummary
from src.screening.scores import AXES, axis_scores, score_card

UNDERVALUED = "Undervalued"
FAIR_VALUE = "Fair value"
OVERVALUED = "Overvalued"
NO_ESTIMATE = "No estimate"


def valuation_status(margin_of_safety: Decimal | float | None, threshold: Decimal | float) -> str:
    """Where the price sits against estimated value: Undervalued above the
    margin-of-safety test threshold, Fair value from 0% up to it,
    Overvalued below 0%, No estimate when no model could run. Mirrors
    valuationStatus() in web/app.js."""
    if margin_of_safety is None:
        return NO_ESTIMATE
    if margin_of_safety > threshold:
        return UNDERVALUED
    if margin_of_safety >= 0:
        return FAIR_VALUE
    return OVERVALUED


def latest_extras(session) -> tuple[dict[str, dict], dict[str, FinancialReport], date | None]:
    """Per company: the valuation_metrics columns the screener view doesn't
    carry (roic, graham_number, dcf_intrinsic_value, as_of_date), and the
    latest FY report for the health checks. Two DISTINCT ON queries rather
    than one per company."""
    metrics = session.execute(text("""
        SELECT DISTINCT ON (v.company_id) c.asx_code, c.company_id, v.roic, v.graham_number,
               v.dcf_intrinsic_value, v.as_of_date
        FROM valuation_metrics v JOIN companies c ON c.company_id = v.company_id
        ORDER BY v.company_id, v.as_of_date DESC
    """)).mappings().all()
    reports = session.execute(
        select(Company.asx_code, FinancialReport)
        .join(FinancialReport, FinancialReport.company_id == Company.company_id)
        .where(FinancialReport.period_type == "FY")
        .distinct(FinancialReport.company_id)
        .order_by(FinancialReport.company_id, FinancialReport.fiscal_year.desc())
    ).all()
    as_of = max((m["as_of_date"] for m in metrics), default=None)
    return {m["asx_code"]: dict(m) for m in metrics}, {code: report for code, report in reports}, as_of


def with_extras(row: dict, extras: dict | None) -> dict:
    row = dict(row)
    row["roic"] = (extras or {}).get("roic")
    row["graham_number"] = (extras or {}).get("graham_number")
    return row


@dataclass
class Universe:
    rows: list[dict]                       # one per screened company, see load_universe
    positions: dict[str, PositionSummary]  # every open holding, screened or not
    args: argparse.Namespace               # the default screener thresholds the rows were judged on
    as_of: date | None                     # newest valuation date across the universe


def load_universe(session, today: date) -> Universe:
    """Every screened company at the default thresholds. On top of the
    screen_asx.py row each carries: company_id, roic, graham_number,
    dcf_intrinsic_value (the estimated value), as_of_date (that company's
    valuation date), axis_scores (dict by spoke) and valuation_status."""
    args = screener_defaults([])
    rows, positions = load_annotated_rows(session, args, today)
    extras, reports, as_of = latest_extras(session)
    out = []
    for r in rows:
        extra = extras.get(r["asx_code"]) or {}
        row = with_extras(r, extra)
        row["company_id"] = extra.get("company_id")
        row["as_of_date"] = extra.get("as_of_date")
        row["dcf_intrinsic_value"] = extra.get("dcf_intrinsic_value")
        row["axis_scores"] = axis_scores(score_card(row, reports.get(r["asx_code"])))
        row["valuation_status"] = valuation_status(row["margin_of_safety_percent"], args.min_margin_of_safety)
        out.append(row)
    return Universe(rows=out, positions=positions, args=args, as_of=as_of)


def score_list(row: dict) -> list[int]:
    """Spoke scores in AXES order, as the GUI's score wheel takes them."""
    return [row["axis_scores"][a] for a in AXES]
