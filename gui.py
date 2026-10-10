#!/usr/bin/env python3
"""Interactive web GUI for the ASX value screener (docs/AS_BUILT.md §20).

    python gui.py              # this PC only: open http://localhost:8000
    python gui.py --lan        # also your phone on home Wi-Fi (needs GUI_PASSWORD in .env)

A small local web server over the same database and the same rules as
screen_asx.py - it calls the screener's own row loader, so the browser
and the command line can never disagree. Screens: a dashboard (what needs
attention, what changed, top opportunities, how the track record is
coming along), a filterable, sortable screener table, a company page with
a score wheel (see src/screening/scores.py), price against estimated
value, price and margin-of-safety history and five years of financials,
and a holdings page.

It writes to the database only to record portfolios and trades (§19.1),
and only for requests that come from Sift's own pages (_same_site_write).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import logging
import os
import re
import secrets
import socket
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from screen_asx import load_annotated_rows, parse_args as screener_defaults
from src import accounts
from src import version as sift_version
from src.ai import tools as ai_tools
from src.devkb import articles as kb_articles, generated as kb_generated, markdown as kb_markdown, register as kb_register
from src.config import get_session
from src.etf import profiles as fund_profiles, views as etf_views
from src.ingestion.insights_ingestion import insights_payload
from src.models import Company, DailyPrice, DividendPayment, FinancialReport, ValuationMetric
from src.models import Holding, Portfolio
from src.portfolio import cgt, holdings as parcels_module, importer, trade_input, views as portfolio_views
from src.portfolio.holdings import HoldingsError
from src import preferences
from src.coattail import notice_views
from src.coattail import views as coattail
from src.search import indexer as search_indexer, learning as search_learning, query as search_query
from src.screening import movers
from src.screening import short_caution
from src.screening.actions import ACTION_ORDER, red_flags
from src.screening.enriched import load_universe, score_list, with_extras
from src.screening.scores import AXES, CHECKS_PER_AXIS, axis_scores, score_card
from src.tracking import report as track_report
from src.tracking import rules_versions
from src import registries
from src.drp import drp_payload
from src.ingestion import short_positions
from src.tracking.signals import signal_changes, tracking_status
from src.watchlist import lists as watchlists
from src import settings as model_settings
from src.admin import scenarios as scenario_lab, workings as workings_module
from src.admin.scenarios import ScenarioError
from src.settings import SettingsError
from src.watchlist.lists import WatchlistError
from src.valuation import dcf as dcf_module, ddm as ddm_module

REPO_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("sift")
WEB_DIR = REPO_DIR / "web"
LOG_DIR = REPO_DIR / "logs"
DEFAULT_PORT = 8000
PRICE_HISTORY_DAYS = 365
REPORT_HISTORY_YEARS = 5
CGT_SOON_DAYS = 90  # dashboard: parcels reaching the CGT discount within this many days
TOP_OPPORTUNITIES = 6
ATTENTION_ACTIONS = ("SELL", "REVIEW")

# Screener table payload - everything the table, filters and mini score
# wheel need, and nothing else, to keep ~500 rows light on a phone.
_SCREENER_FIELDS = (
    "asx_code", "company_name", "sector", "current_price", "margin_of_safety_percent",
    "pe_ratio", "roe", "debt_to_equity", "grossed_up_dividend_yield", "payout_ratio",
    "valuation_method", "fundamentals_trend", "earnings_quality", "price_signal",
    "dividend_trend", "data_confidence", "mos_ok", "roe_ok", "de_ok", "yield_ok",
    "overall", "momentum_ok", "trap_risk", "held", "action", "action_reason", "short_percent",
    "days_to_cover",
)


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


def _authorised(header: str | None, password: str) -> bool:
    """HTTP Basic auth: any username, the password from GUI_PASSWORD."""
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    _, _, supplied = decoded.partition(":")
    return secrets.compare_digest(supplied.encode("utf-8"), password.encode("utf-8"))


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
WRITE_HEADER = "x-sift"  # set by web/app.js on every change; another site's page can't add it without permission


def _same_site_write(request: Request) -> bool:
    """A change must come from Sift's own pages. The browser sends saved
    Basic-auth credentials with any site's request, so a password alone
    doesn't stop another website's page posting to Sift. Three checks: the
    custom header (cross-site requests can't set it without a CORS
    permission Sift never grants), the browser's Sec-Fetch-Site, and the
    Origin's host matching the Host."""
    if request.headers.get(WRITE_HEADER) != "1":
        return False
    site = request.headers.get("sec-fetch-site")
    if site and site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower():
        return False
    return True


SCHEMA_HINT = ("The database is missing a table or column this version of Sift needs. "
               "Run: python -m src.apply_schema, then reload. (Restarting python gui.py also does it.)")


def error_message(exc: Exception) -> str:
    """What the page shows for an unexpected server error: the fix when it's
    a database that hasn't caught up with the code, otherwise the error
    itself, so it can be reported without hunting through the console."""
    if isinstance(exc, ProgrammingError) and type(getattr(exc, "orig", None)).__name__ in ("UndefinedTable", "UndefinedColumn"):
        return SCHEMA_HINT
    if isinstance(exc, OperationalError):
        return "Can't reach the database. Check PostgreSQL is running and the settings in .env."
    first = (str(getattr(exc, "orig", None) or exc).strip().splitlines() or [""])[0][:300]
    return f"Server error ({type(exc).__name__}): {first}. The full details are in the window running gui.py."


def prepare_search() -> str:
    """Bring the search index up to date at start-up (§32): help, pages and
    the developer knowledge base always (they change only with a git pull), and everything when the
    index is empty (a new install). Never stops the server starting."""
    try:
        with get_session() as session:
            empty = not session.execute(text("SELECT 1 FROM search_index WHERE area = 'market' LIMIT 1")).first()
            counts = search_indexer.reindex(session, search_indexer.AREAS if empty else ("help", "pages", "devkb"), "startup")
            session.commit()
        return "Search index: " + ", ".join(f"{a} {n}" for a, n in counts.items()) + "."
    except Exception as exc:  # noqa: BLE001 - search can be rebuilt later; the pages still work
        logger.exception("Search index not prepared")
        return f"Search index not updated ({type(exc).__name__}); rebuild it from Admin."


def prepare_database() -> str | None:
    """Bring the database up to the code's schema before serving, the same
    idempotent step the nightly job runs first (src/apply_schema.py), so a
    git pull can't leave the pages failing until 6pm. Returns a problem to
    report, or None."""
    from src.apply_schema import apply_schema
    from src.config import get_engine

    try:
        apply_schema(get_engine())
    except Exception as exc:  # noqa: BLE001 - reported, and the server still starts
        return f"{type(exc).__name__}: {str(exc).strip().splitlines()[0] if str(exc).strip() else ''}"
    return None


def _card_payload(card) -> dict:
    scores = axis_scores(card)
    return {
        axis: {"score": scores[axis], "checks": [{"label": c.label, "passed": c.passed} for c in card[axis]]}
        for axis in AXES
    }


def screener_payload(session, today: date) -> dict:
    universe = load_universe(session, today)
    args = universe.args
    watched = watchlists.watched_codes(session)
    out = []
    for row in universe.rows:
        item = {f: row.get(f) for f in _SCREENER_FIELDS}
        item["scores"] = score_list(row)
        found = short_caution.caution(row)
        item["short_caution"] = found and found["level"]  # HIGH / ELEVATED / None
        item["watchlists"] = watched.get(row["asx_code"], [])
        out.append(item)
    return {
        "watchlists": [{"watchlist_id": str(w.watchlist_id), "name": w.name} for w in watchlists.list_watchlists(session)],
        "as_of": universe.as_of,
        "axes": list(AXES),
        "checks_per_axis": CHECKS_PER_AXIS,
        "actions": [a for a in ACTION_ORDER],
        "sectors": sorted({r["sector"] for r in out if r["sector"]}),
        "thresholds": {
            "margin_of_safety": args.min_margin_of_safety, "roe": args.min_roe,
            "debt_to_equity": args.max_debt_equity, "yield": args.min_yield,
        },
        "rows": out,
    }


def _model_assumptions(method: str | None) -> dict | None:
    """The default assumptions the nightly valuation runs with, for the
    company page's model note (run_valuation's CLI overrides aren't used
    by the scheduled job)."""
    if method == "DDM":
        m = ddm_module
    elif method == "DCF":
        m = dcf_module
    else:
        return None
    return {"method": method, "growth_rate": m.DEFAULT_GROWTH_RATE, "stage1_years": m.DEFAULT_STAGE1_YEARS,
            "terminal_growth_rate": m.DEFAULT_TERMINAL_GROWTH_RATE, "discount_rate": m.DEFAULT_DISCOUNT_RATE}

SUMMARY_SENTENCES = 2  # the company page shows this many, with "more" for the rest
# A full stop after one of these (or after a single capital, as in "U.S.")
# doesn't end a sentence.
_NOT_A_SENTENCE_END = {"ltd", "pty", "inc", "co", "corp", "no", "st", "mt", "dr", "mr", "mrs", "ms", "approx",
                       "est", "e.g", "i.e", "vs", "etc", "jr", "sr", "nz", "u.s", "u.k", "p.l.c", "n.v", "s.a"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def short_summary(text: str | None, sentences: int = SUMMARY_SENTENCES) -> str | None:
    """The first `sentences` sentences of Yahoo's business summary, or the
    whole thing when it's no longer than that."""
    if not text:
        return None
    kept, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        last_word = text[start:m.start()].rsplit(None, 1)[-1].rstrip(".!?").lower()
        if last_word in _NOT_A_SENTENCE_END or len(last_word) == 1:
            continue
        kept.append(text[start:m.start()])
        start = m.end()
        if len(kept) == sentences:
            return " ".join(kept)
    return text


def company_payload(session, asx_code: str, today: date) -> dict | None:
    args = screener_defaults([])
    rows, positions = load_annotated_rows(session, args, today)
    row = next((r for r in rows if r["asx_code"] == asx_code), None)
    if row is None:
        return None
    company = session.execute(select(Company).where(Company.asx_code == asx_code)).scalar_one()
    metric = session.execute(
        select(ValuationMetric).where(ValuationMetric.company_id == company.company_id)
        .order_by(ValuationMetric.as_of_date.desc()).limit(1)
    ).scalar_one()
    reports = list(session.execute(
        select(FinancialReport)
        .where(FinancialReport.company_id == company.company_id, FinancialReport.period_type == "FY")
        .order_by(FinancialReport.fiscal_year.desc()).limit(REPORT_HISTORY_YEARS)
    ).scalars())
    since = today - timedelta(days=PRICE_HISTORY_DAYS)
    prices = session.execute(
        select(DailyPrice.price_date, DailyPrice.close_price, DailyPrice.volume)
        .where(DailyPrice.company_id == company.company_id, DailyPrice.price_date >= since)
        .order_by(DailyPrice.price_date)
    ).all()
    dividends = session.execute(
        select(DividendPayment.ex_date, DividendPayment.amount, DividendPayment.abnormal)
        .where(DividendPayment.company_id == company.company_id, DividendPayment.ex_date >= since)
        .order_by(DividendPayment.ex_date)
    ).all()
    mos_history = session.execute(
        select(ValuationMetric.as_of_date, ValuationMetric.margin_of_safety_percent)
        .where(ValuationMetric.company_id == company.company_id, ValuationMetric.as_of_date >= since)
        .order_by(ValuationMetric.as_of_date)
    ).all()

    row = with_extras(row, {"roic": metric.roic, "graham_number": metric.graham_number})
    for field in ("dcf_intrinsic_value", "uncapped_dividend_yield", "price_to_fcf", "ev_to_ebit",
                  "cash_conversion", "price_vs_200d", "range_position_52w", "margin_of_safety_trend", "pb_ratio"):
        row[field] = getattr(metric, field)
    row["industry"] = company.industry
    row["country"] = company.country
    row["statements_issue"] = company.statements_issue
    row["business_summary"] = company.business_summary or None
    row["business_summary_short"] = short_summary(company.business_summary)
    row["insights"] = insights_payload(session, company.company_id, row.get("current_price"))
    row["notices"] = notice_views.company_notices(session, asx_code, today)
    row["trading_currency"] = company.trading_currency
    row["financial_currency"] = company.financial_currency
    row["as_of_date"] = metric.as_of_date

    position = positions.get(asx_code)
    t = args
    return {
        "company": row,
        "axes": list(AXES),
        "checks_per_axis": CHECKS_PER_AXIS,
        "scores": _card_payload(score_card(row, reports[0] if reports else None)),
        "tests": [
            {"name": "Margin of safety", "value": row["margin_of_safety_percent"], "unit": "%",
             "rule": f"above {t.min_margin_of_safety}%", "passed": row["mos_ok"] == "Y"},
            {"name": "Return on equity (ROE)", "value": row["roe"], "unit": "%",
             "rule": f"above {t.min_roe}%", "passed": row["roe_ok"] == "Y"},
            {"name": "Debt to equity", "value": row["debt_to_equity"], "unit": "",
             "rule": f"below {t.max_debt_equity}", "passed": row["de_ok"] == "Y"},
            {"name": "Grossed-up dividend yield", "value": row["grossed_up_dividend_yield"], "unit": "%",
             "rule": f"above {t.min_yield}%", "passed": row["yield_ok"] == "Y"},
        ],
        "flags": red_flags(row),
        "short_caution": short_caution.caution(row),
        "model": _model_assumptions(row.get("valuation_method")),
        "watchlists": company_watchlists(session, company.company_id, row),
        "position": None if position is None else {
            "units": position.units, "cost_base": position.cost_base,
            "next_discount_date": position.next_discount_date,
            "units_pending_discount": position.units_pending_discount,
        },
        "prices": [[d, c] for d, c, _ in prices],
        "volumes": [[d, v] for d, _, v in prices if v is not None],  # shares traded each day
        "dividends": [{"ex_date": d, "amount": a, "abnormal": ab} for d, a, ab in dividends],
        "drp": drp_payload(session, company.company_id, row.get("current_price"), today,
                           position.units if position is not None else None),
        "registry": registries.company_registry(session, company.company_id),
        "short_interest": short_positions.company_short(session, asx_code, today),
        "mos_history": [[d, m] for d, m in mos_history if m is not None],
        "reports": [
            {"fiscal_year": r.fiscal_year, "revenue": r.revenue, "net_profit_after_tax": r.net_profit_after_tax,
             "free_cash_flow": r.free_cash_flow, "operating_cash_flow": r.operating_cash_flow,
             "dividends_per_share": r.dividends_per_share, "eps": r.eps,
             "abnormal_distributions_per_share": r.abnormal_distributions_per_share,
             "reporting_currency": r.reporting_currency, "fx_rate": r.fx_rate, "report_date": r.report_date,
             "total_debt": r.total_debt, "cash_and_equivalents": r.cash_and_equivalents,
             "total_equity": r.total_equity}
            for r in reversed(reports)
        ],
    }


# ---------- dashboard ----------

_LOG_STARTED = re.compile(r"Daily Refresh Started: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_LOG_FINISHED = re.compile(r"Daily Refresh Finished: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_LOG_ERROR = " ERROR "  # logging's level field; each company that fails logs one of these
_TRACEBACK = "Traceback (most recent call last)"
RUN_STILL_GOING_HOURS = 4  # an unfinished log younger than this is a run in progress (the task stops runs at 4 hours)


def _previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def last_refresh(log_dir: Path, now: datetime) -> dict | None:
    """The newest nightly log (scripts/daily_refresh.ps1): when it ran,
    whether it finished, how many errors it logged, and whether a whole
    step crashed.

    A company that fails is logged as one ERROR line followed by its
    traceback, and the run carries on: a few of these most nights are
    normal (Yahoo has gaps). A traceback with no ERROR line before it is a
    step that crashed outright, which is what turns the status to
    "crashed"."""
    logs = sorted(log_dir.glob("refresh_*.log"))
    if not logs:
        return None
    raw = logs[-1].read_bytes()
    body = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")
    started, finished = _LOG_STARTED.search(body), _LOG_FINISHED.search(body)
    started_at = datetime.strptime(started.group(1), "%Y-%m-%d %H:%M:%S") if started else None
    finished_at = datetime.strptime(finished.group(1), "%Y-%m-%d %H:%M:%S") if finished else None
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    errors = [line for line in lines if _LOG_ERROR in line]
    crashes = sum(1 for i, line in enumerate(lines) if _TRACEBACK in line and (i == 0 or _LOG_ERROR not in lines[i - 1]))
    if not finished_at:
        recent = started_at and now - started_at < timedelta(hours=RUN_STILL_GOING_HOURS)
        status = "running" if recent else "incomplete"
    else:
        status = "crashed" if crashes else "errors" if errors else "ok"
    return {"file": logs[-1].name, "started": started_at, "finished": finished_at, "status": status,
            "errors": len(errors), "crashes": crashes, "first_error": errors[0][:300] if errors else None}


def status_payload(session, today: date, now: datetime, log_dir: Path = LOG_DIR) -> dict:
    """The data-date chip in the menu bar: how fresh the prices and
    valuations are, and how the last nightly run went."""
    as_of = session.execute(select(func.max(ValuationMetric.as_of_date))).scalar_one()
    prices = session.execute(select(func.max(DailyPrice.price_date)).join(Company)
                             .where(Company.security_type == "SHARE")).scalar_one()
    expected = _previous_weekday(today)
    return {
        "as_of": as_of,
        "latest_price_date": prices,
        "expected": expected,
        # Amber when the newest valuation is older than the last weekday's
        # close (a public holiday also shows amber, harmlessly).
        "stale": as_of is None or as_of < expected,
        "last_run": last_refresh(log_dir, now),
    }


def etf_by_code(session, today: date, watched: dict[str, list[str]] | None = None, kind: str = "ETF") -> dict[str, dict]:
    return {r["asx_code"]: r for r in etf_views.etf_rows(session, today, watched, kind)}


def funds_by_code(session, today: date, watched: dict[str, list[str]] | None = None) -> dict[str, dict]:
    """ETF and LIC rows together, by code."""
    return etf_by_code(session, today, watched, "ETF") | etf_by_code(session, today, watched, "LIC")


def portfolio_payload(session, universe, today: date, etfs: dict[str, dict] | None = None) -> dict:
    """Every open holding across all portfolios valued at the latest close,
    with the day's move and the suggested action, plus a summary line for
    each active portfolio."""
    rows = {r["asx_code"]: r for r in universe.rows}
    out = portfolio_views.combined(session, rows, today, etfs)
    out["portfolios"] = [p for p in portfolio_views.portfolio_summaries(session, rows, today) if not p["archived"]]
    return out


def _brief(row: dict) -> dict:
    return {"asx_code": row["asx_code"], "company_name": row["company_name"], "sector": row["sector"],
            "action": row["action"], "action_reason": row["action_reason"], "price": row["current_price"],
            "margin_of_safety_percent": row["margin_of_safety_percent"],
            "valuation_status": row["valuation_status"], "scores": score_list(row)}


def dashboard_payload(session, today: date, now: datetime, log_dir: Path = LOG_DIR) -> dict:
    universe = load_universe(session, today)
    rows = universe.rows
    rows_by = {r["asx_code"]: r for r in rows}
    watched = watchlists.watched_codes(session)
    etfs = etf_by_code(session, today, watched)
    lics = etf_by_code(session, today, watched, "LIC")
    portfolio = portfolio_payload(session, universe, today, etfs | lics)
    # What changed: companies on a watchlist first, keeping the better-first order within each group.
    changes = signal_changes(session)
    for c in changes["changes"]:
        c["watchlists"] = watched.get(c["asx_code"], [])
    changes["changes"].sort(key=lambda c: not c["watchlists"])

    attention = [_brief(r) for r in rows if r["held"] is not None and r["action"] in ATTENTION_ACTIONS]
    attention.sort(key=lambda b: (ATTENTION_ACTIONS.index(b["action"]), b["asx_code"]))
    screened = {r["asx_code"] for r in rows}
    cgt_soon = [
        {"asx_code": h["asx_code"], "date": h["next_discount_date"], "units": h["units_pending_discount"],
         "days": (h["next_discount_date"] - today).days, "security_type": h["security_type"]}
        for h in portfolio["holdings"]
        if h["next_discount_date"] and 0 <= (h["next_discount_date"] - today).days <= CGT_SOON_DAYS
    ]
    cgt_soon.sort(key=lambda c: c["date"])

    def rank(r):
        return (-sum(r["axis_scores"].values()), -(r["margin_of_safety_percent"] or 0), r["asx_code"])
    buys = sorted((r for r in rows if r["action"] == "BUY"), key=rank)
    investigate = sorted((r for r in rows if r["action"] == "INVESTIGATE"), key=rank)
    top = [_brief(r) for r in (buys + investigate)[:TOP_OPPORTUNITIES]]

    return {
        "status": status_payload(session, today, now, log_dir),
        "axes": list(AXES),
        "checks_per_axis": CHECKS_PER_AXIS,
        "companies": len(rows),
        "action_counts": {a: sum(1 for r in rows if r["action"] == a) for a in ACTION_ORDER},
        "attention": attention,
        "triggered": triggered_entries(session, rows_by),
        "not_screened": sorted(set(universe.positions) - screened - set(etfs) - set(lics)),
        "cgt_soon": [c for c in cgt_soon if c["security_type"] == "SHARE"],
        "etfs": etf_panel(session, etfs, portfolio, [c for c in cgt_soon if c["security_type"] == "ETF"]),
        "lics": etf_panel(session, lics, portfolio, [c for c in cgt_soon if c["security_type"] == "LIC"], "LIC"),
        "cgt_soon_days": CGT_SOON_DAYS,
        "portfolio": portfolio,
        "changes": changes,
        "tracking": tracking_status(session) | {"headline": track_report.headline(session)},
        "top": top,
        "layout": preferences.get_preference(session, preferences.DASHBOARD_LAYOUT),
        "notices": notice_views.my_notices(session, set(universe.positions), watched, today=today),
        "movers": {"shares": movers.share_movers(session, rows, watched, today),
                   "etfs": movers.fund_movers(etfs), "lics": movers.fund_movers(lics)},
        "thresholds": {"margin_of_safety": universe.args.min_margin_of_safety, "roe": universe.args.min_roe,
                       "debt_to_equity": universe.args.max_debt_equity, "yield": universe.args.min_yield},
    }


ETF_PANEL_LIMIT = 8


def etf_panel(session, etfs: dict[str, dict], portfolio: dict, cgt_soon: list[dict], kind: str = "ETF") -> dict:
    """The dashboard's ETFs (or LICs) card: watchlist triggers met on them,
    parcels reaching the CGT discount, and the ones you hold or watch with
    today's move, held first, then biggest move first."""
    def brief(r):
        return {k: r[k] for k in ("asx_code", "company_name", "category", "current_price", "day_change_percent",
                                  "return_1y", "distribution_yield_12m", "premium_now", "watchlists")} | \
            {"held": r["held"] is not None}
    followed = [r for r in etfs.values() if r["held"] is not None or r["watchlists"]]
    followed.sort(key=lambda r: (r["held"] is None, -abs(r["day_change_percent"] or 0), r["asx_code"]))
    return {
        "count": len(etfs),
        "triggered": triggered_entries(session, etfs),
        "cgt_soon": cgt_soon,
        "followed": [brief(r) for r in followed[:ETF_PANEL_LIMIT]],
        "more": max(0, len(followed) - ETF_PANEL_LIMIT),
        "value": portfolio["sections"][kind],
        "kind": kind,
    }


def companies_index(session) -> list[dict]:
    """Code and name of every screened company, ETF and LIC, for the menu
    bar search; each is marked with its type so search opens the right page."""
    rows = session.execute(text("SELECT asx_code, company_name FROM asx_value_screener ORDER BY asx_code")).all()
    funds = session.execute(select(Company.asx_code, Company.company_name, Company.security_type).where(
        Company.security_type.in_(("ETF", "LIC")), Company.is_active.is_(True)).order_by(Company.asx_code)).all()
    return [{"code": code, "name": name, "type": "SHARE"} for code, name in rows] + \
        [{"code": code, "name": name, "type": kind} for code, name, kind in funds]


# ---------- watchlists (§22) ----------

def _entry(item, code: str, row: dict | None) -> dict:
    found = watchlists.triggers(item, row)
    if row and row.get("security_type") in ("ETF", "LIC"):
        return {
            "asx_code": code, "company_name": row["company_name"], "security_type": row["security_type"],
            "note": item.note, "price_below": item.price_below, "yield_above": item.yield_above,
            "nta_discount_above": item.nta_discount_above,
            "added_at": item.added_at, "triggers": found, "triggered": any(t["met"] for t in found),
            "price": row["current_price"], "held": row["held"] is not None,
            **{k: row[k] for k in ("category", "day_change_percent", "return_1y", "return_5y",
                                   "distribution_yield_12m", "mer_percent", "premium_now", "nta_pre_tax")},
        }
    return {
        "asx_code": code, "company_name": row["company_name"] if row else None, "security_type": "SHARE",
        "note": item.note, "mos_above": item.mos_above, "price_below": item.price_below, "added_at": item.added_at,
        "short_above": item.short_above, "short_percent": row.get("short_percent") if row else None,
        "triggers": found, "triggered": any(t["met"] for t in found),
        "price": row["current_price"] if row else None,
        "margin_of_safety_percent": row["margin_of_safety_percent"] if row else None,
        "valuation_status": row["valuation_status"] if row else None,
        "action": row["action"] if row else None, "action_reason": row["action_reason"] if row else None,
        "held": row["held"] is not None if row else False,
        "scores": score_list(row) if row else None,
    }


def company_watchlists(session, company_id, row: dict) -> list[dict]:
    """Every watchlist, and this company's entry on each one it's on."""
    mine = {i.watchlist_id: i for i in session.execute(
        select(watchlists.WatchlistItem).where(watchlists.WatchlistItem.company_id == company_id)).scalars()}
    out = []
    for w in watchlists.list_watchlists(session):
        item = mine.get(w.watchlist_id)
        entry = {"watchlist_id": str(w.watchlist_id), "name": w.name, "member": item is not None}
        if item is not None:
            found = watchlists.triggers(item, row)
            entry |= {"note": item.note, "mos_above": item.mos_above, "price_below": item.price_below,
                      "yield_above": item.yield_above, "nta_discount_above": item.nta_discount_above,
                      "short_above": item.short_above, "triggers": found, "triggered": any(t["met"] for t in found)}
        out.append(entry)
    return out


def watchlist_summaries(session, rows: dict[str, dict]) -> list[dict]:
    """Each list with its share and ETF counts (an ETF is anything in
    `rows` marked as one) and how many entries have a trigger met."""
    counts: dict = {}
    bucket = {"ETF": "etfs", "LIC": "lics"}
    for item, code, _ in watchlists.entries(session):
        c = counts.setdefault(item.watchlist_id, {"companies": 0, "etfs": 0, "lics": 0, "triggered": 0})
        row = rows.get(code)
        c[bucket.get(row.get("security_type") if row else None, "companies")] += 1
        c["triggered"] += any(t["met"] for t in watchlists.triggers(item, row))
    empty = {"companies": 0, "etfs": 0, "lics": 0, "triggered": 0}
    return [{"watchlist_id": str(w.watchlist_id), "name": w.name} | counts.get(w.watchlist_id, empty)
            for w in watchlists.list_watchlists(session)]


def watchlist_detail(session, watchlist, rows: dict[str, dict]) -> dict:
    items = [_entry(item, code, rows.get(code)) for item, code, _ in watchlists.entries(session, watchlist.watchlist_id)]
    items.sort(key=lambda e: (not e["triggered"], e["asx_code"]))
    return {"watchlist_id": str(watchlist.watchlist_id), "name": watchlist.name,
            "items": [e for e in items if e["security_type"] == "SHARE"],
            "etfs": [e for e in items if e["security_type"] == "ETF"],
            "lics": [e for e in items if e["security_type"] == "LIC"],
            "axes": list(AXES), "checks_per_axis": CHECKS_PER_AXIS}


def triggered_entries(session, rows: dict[str, dict]) -> list[dict]:
    """Every watchlist entry whose trigger is met now, for the dashboard."""
    out = []
    for item, code, name in watchlists.entries(session):
        met = [t for t in watchlists.triggers(item, rows.get(code)) if t["met"]]
        if met:
            out.append({"asx_code": code, "watchlist": name, "watchlist_id": str(item.watchlist_id),
                        "triggers": met, "note": item.note})
    return out


def track_record_payload(session, today: date, version: str | None = None) -> dict:
    """Everything the Track record page shows (§21). `version` limits the
    verdict and lists to one rules version; None means all."""
    universe = load_universe(session, today)
    threshold = universe.args.min_margin_of_safety
    current = {r["asx_code"]: r for r in universe.rows}
    watched = watchlists.watched_codes(session)
    verdict = track_report.verdict(session, version)
    proven, is_proven, proven_at = track_report.proven_actions(verdict)
    missed, saved = track_report.missed_and_saved(session, version, current, threshold, watched)
    return {
        "status": tracking_status(session),
        "version": version,
        "version_label": rules_versions.label(session, version),  # versions are an admin detail (Admin, Model and rules)
        "horizons": list(verdict),
        "verdict": verdict,
        "monthly": track_report.monthly(session, version),
        "missed": missed,
        "saved": saved,
        "proven": {"actions": proven, "proven": is_proven, "horizon": proven_at},
        "actionable": track_report.actionable(session, universe.rows, proven, threshold, watched),
        "rules": {"too_early_below": track_report.TOO_EARLY_BELOW, "solid_above": track_report.SOLID_ABOVE,
                  "missed_excess": track_report.MISSED_EXCESS, "purchase_window_days": track_report.PURCHASE_WINDOW_DAYS,
                  "margin_of_safety": threshold},
    }


# ---------- admin console (§24) ----------

def settings_payload() -> dict:
    """Every adjustable setting with its live value, as the admin console shows it."""
    def shown(key, value):
        return model_settings.to_display(key, value)
    return {
        "groups": [{"id": g, "name": n} for g, n in model_settings.GROUPS],
        "settings": [{"key": m.key, "group": m.group, "label": m.label, "unit": m.unit,
                      "live": shown(m.key, getattr(model_settings.LIVE, m.key)),
                      "minimum": shown(m.key, m.minimum), "maximum": shown(m.key, m.maximum),
                      "formula": m.formula, "used_in": m.used_in, "help_id": m.help_id}
                     for m in model_settings.SETTINGS],
    }


def scenario_info(scenario) -> dict:
    return {"scenario_id": str(scenario.scenario_id), "name": scenario.name, "notes": scenario.notes,
            "overrides": scenario.overrides or {}, "changes": len(scenario.overrides or {}),
            "updated_at": scenario.updated_at}


def web_version() -> str:
    """Changes whenever a page file changes (a git pull): sent with every
    response so an open Sift tab knows to reload itself."""
    stamps = [f"{p.name}:{p.stat().st_mtime_ns}" for p in sorted(WEB_DIR.glob("*")) if p.is_file()]
    return hashlib.sha1("|".join(stamps).encode()).hexdigest()[:12]


def owner_user(request: Request, session) -> accounts.User | None:
    """Who a request is from, until logins arrive (multi-user Phase 3, §33):
    the owner, behind GUI_PASSWORD when that is set."""
    return accounts.owner(session)


def test_header_user(request: Request, session) -> accounts.User | None:
    """Tests only: the account named by the X-Test-User header (an email),
    else the owner. Never used by `python gui.py`."""
    email = request.headers.get("x-test-user")
    return accounts.find_user(session, email) if email else accounts.owner(session)


def create_app(password: str | None = None, resolve_user=owner_user) -> FastAPI:
    """`resolve_user(request, session)` says who each /api/ request is from
    (None: nobody signed in). Personal data is read and written as that
    user (src/accounts.py); /api/admin/ needs an admin."""
    app = FastAPI(title="ASX Value Screener", docs_url=None, redoc_url=None, openapi_url=None)

    def request_user(request: Request) -> tuple[accounts.User | None, accounts.User | None]:
        """(who is signed in, whom Sift acts for): the same person unless
        they're an admin impersonating someone (§35)."""
        with get_session() as session:
            user = resolve_user(request, session)
            acting = user
            if user is not None and user.is_active:
                accounts.touch(session, user.user_id, accounts.client_label(request.headers.get("user-agent")))
                acting = accounts.impersonating(session, user) or user
            session.commit()
            return user, acting

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        # Covers every route, including the static files.
        if password and not _authorised(request.headers.get("authorization"), password):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ASX Value Screener"'})
        if request.method in WRITE_METHODS and not _same_site_write(request):
            return JSONResponse({"detail": "Changes are only accepted from Sift's own pages."}, status_code=403)
        acting = None
        try:
            if request.url.path.startswith("/api/"):
                user, acting = await run_in_threadpool(request_user, request)
                if user is None:
                    return JSONResponse({"detail": "Sign in to use Sift."}, status_code=401, headers={"Cache-Control": "no-store"})
                if not user.is_active:
                    return JSONResponse({"detail": "This account is disabled."}, status_code=403, headers={"Cache-Control": "no-store"})
                # While impersonating, the admin console is closed, as it is to the person being impersonated.
                if request.url.path.startswith("/api/admin/") and not acting.is_admin:
                    return JSONResponse({"detail": "Only an admin can do that."}, status_code=403, headers={"Cache-Control": "no-store"})
                request.state.user, request.state.acting = user, acting
            with accounts.acting_as(acting.user_id if acting else None):
                response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - an unexpected error becomes a readable message on the page
            logger.exception("Error serving %s", request.url.path)
            return JSONResponse({"detail": error_message(exc)}, status_code=500, headers={"Cache-Control": "no-store"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Sift-Version"] = web_version()
        return response

    @app.get("/api/status")
    def api_status(request: Request):
        with get_session() as session:
            payload = status_payload(session, date.today(), datetime.now())
            payload["user"] = accounts.current_user(session).info()
            payload["impersonating"] = request.state.user.user_id != request.state.acting.user_id
            payload["version"] = sift_version.VERSION
            return JSONResponse(_json_ready(payload))

    def me_payload(request: Request, session) -> dict:
        user, acting = request.state.user, request.state.acting
        return acting.info() | {
            "impersonated_by": user.info() if user.user_id != acting.user_id else None,
            "settings": preferences.user_settings(session),
            "settings_chosen": sorted(preferences.saved_settings(session)),  # the rest are defaults
            "previous_session": None if user.user_id != acting.user_id else accounts.previous_session(session, user.user_id),
        }

    @app.get("/api/me")
    def api_me(request: Request):
        """Who Sift is acting for (§33), who is impersonating them if anyone (§35), and their settings."""
        with get_session() as session:
            return JSONResponse(_json_ready(me_payload(request, session)))

    @app.patch("/api/me")
    def api_update_me(request: Request, body: dict = Body(...)):
        """Profile: the display name (the email changes with sign-in, Phase 3)."""
        def action(session):
            accounts.update_user(session, request.state.acting, request.state.acting,
                                 display_name=body.get("display_name"))
            return me_payload(request, session) | {"display_name": accounts.current_user(session).display_name}
        return change(action)

    @app.put("/api/me/settings")
    def api_my_settings(body: dict = Body(...)):
        """Preferences: change any of the settings; the rest stay as they are."""
        return change(lambda session: {"settings": preferences.save_settings(session, body)})

    @app.delete("/api/me/settings")
    def api_reset_my_settings():
        return change(lambda session: {"settings": preferences.save_settings(session, preferences.SETTINGS_DEFAULTS)})

    # ---------- developer knowledge base (§36) ----------
    def kb_index(today: date) -> dict:
        found = kb_articles.load()
        listed = [a.info(today) for a in found]
        listed += [{"id": key, "title": title, "category": cat, "summary": summary, "status": "published",
                    "generated": True} for key, (title, cat, summary) in kb_generated.GENERATED.items()]
        return {"articles": listed, "found": found}

    @app.get("/api/admin/kb")
    def api_kb():
        """The developer knowledge base's home: every article by category, reviews due, the register and releases."""
        today = date.today()
        idx = kb_index(today)
        releases = sorted((a for a in idx["found"] if a.category == "releases" and a.release),
                          key=lambda a: a.published, reverse=True)
        return JSONResponse(_json_ready({
            "version": sift_version.VERSION, "released": sift_version.RELEASED,
            "categories": [{"id": k, "name": v} for k, v in kb_articles.CATEGORIES.items()],
            "articles": idx["articles"], "reviews": kb_articles.review_summary(idx["found"], today),
            "register": kb_register.summary(kb_register.load()),
            "latest_release": releases[0].info(today) if releases else None,
        }))

    @app.get("/api/admin/kb/register")
    def api_kb_register():
        """The improvement register: known issues, technical debt, ideas and risks."""
        titles = {a.id: a.title for a in kb_articles.load()}
        items = [i | {"article_titles": [{"id": x, "title": titles.get(x, x)} for x in i["articles"]]} for i in kb_register.load()]
        return JSONResponse(_json_ready({"items": items, "types": kb_register.TYPES, "priorities": kb_register.PRIORITIES,
                                         "statuses": kb_register.STATUSES}))

    @app.get("/api/admin/kb/{article_id}")
    def api_kb_article(article_id: str):
        """One article (or generated reference page), rendered, with its contents and links."""
        today = date.today()
        found = kb_articles.by_id()
        if article_id in kb_generated.GENERATED:
            title, cat, summary = kb_generated.GENERATED[article_id]
            with get_session() as session:
                body = kb_generated.build(article_id, session, app)
            html_, toc = kb_markdown.render(body)
            return JSONResponse(_json_ready({"id": article_id, "title": title, "category": cat, "summary": summary,
                                             "generated": True, "html": html_, "toc": toc, "related": [], "backlinks": []}))
        article = found.get(article_id)
        if article is None:
            raise HTTPException(status_code=404, detail="No such article")
        html_, toc = kb_articles.rendered(article)
        related = [{"id": r, "title": found[r].title if r in found else kb_generated.GENERATED.get(r, (r,))[0]}
                   for r in article.related]
        backlinks = [{"id": a.id, "title": a.title} for a in found.values()
                     if a.id != article.id and (article.id in a.related or f"kb:{article.id}" in a.body)]
        return JSONResponse(_json_ready(article.info(today) | {
            "html": html_, "toc": toc, "related": related, "backlinks": backlinks,
            "category_name": kb_articles.CATEGORIES[article.category]}))

    # ---------- AI tools (docs/kb/features/ai-and-graph.md) ----------
    @app.get("/api/ai/tools")
    def api_ai_tools():
        """Every read-only AI tool with its JSON Schema, for an assistant to call."""
        return JSONResponse({"tools": ai_tools.catalogue(), "note": ai_tools.NOT_ADVICE})

    @app.post("/api/ai/tools/{name}")
    def api_ai_tool(name: str, body: dict = Body(default={})):
        """Run one AI tool for the current person. Read-only: its session is rolled back."""
        with get_session() as session:
            try:
                return JSONResponse(ai_tools.call(session, name, body))
            except ai_tools.ToolError as exc:
                raise HTTPException(status_code=404 if name not in ai_tools.BY_NAME else 400, detail=str(exc)) from None
            finally:
                session.rollback()

    # ---------- users and impersonation (§35) ----------
    def user_or_404(session, user_id: str) -> accounts.User:
        found = accounts.get_user(session, user_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such account")
        return found

    @app.put("/api/admin/company/{asx_code}/registry")
    def api_set_registry(asx_code: str, body: dict = Body(...)):
        """Set or correct a company's share registry (a known one, another by name, or none: back to ASX's)."""
        code = asx_code.strip().upper()
        def action(session):
            company = session.execute(select(Company).where(Company.asx_code == code)).scalar_one_or_none()
            if company is None:
                raise HTTPException(status_code=404, detail=f"{code} isn't in Sift")
            registries.set_by_admin(session, code, body.get("registry_id") or None, body.get("name"))
            return registries.company_registry(session, company.company_id)
        return change(action)

    @app.get("/api/admin/rules-versions")
    def api_rules_versions():
        """Each rules version: its number, when it took effect, what changed and its share of the track record."""
        with get_session() as session:
            return JSONResponse(_json_ready({"versions": rules_versions.listing(session)}))

    @app.get("/api/admin/users")
    def api_users(request: Request):
        with get_session() as session:
            return JSONResponse(_json_ready({"users": accounts.user_list(session), "me": str(request.state.user.user_id),
                                             "log": accounts.impersonation_log(session),
                                             "sessions": accounts.session_log(session),
                                             "activity_days": accounts.ACTIVITY_DAYS,
                                             "idle_minutes": accounts.SESSION_IDLE_MINUTES,
                                             "expires_hours": accounts.IMPERSONATION_HOURS}))

    @app.post("/api/admin/users")
    def api_create_user(body: dict = Body(...)):
        return change(lambda session: accounts.create_user(
            session, body.get("email"), body.get("display_name"), body.get("role") or "member").info())

    @app.patch("/api/admin/users/{user_id}")
    def api_update_user(user_id: str, request: Request, body: dict = Body(...)):
        return change(lambda session: accounts.update_user(
            session, user_or_404(session, user_id), request.state.user, display_name=body.get("display_name"),
            role=body.get("role"), status=body.get("status")).info())

    @app.post("/api/admin/impersonate")
    def api_impersonate(request: Request, body: dict = Body(...)):
        """Act as someone else until ended (or after IMPERSONATION_HOURS); logged."""
        return change(lambda session: {"impersonating": accounts.start_impersonation(
            session, request.state.user, accounts.get_user(session, body.get("user_id"))).info()})

    @app.delete("/api/impersonation")
    def api_end_impersonation(request: Request):
        """End impersonating: open to the impersonating admin whomever they're acting as."""
        return change(lambda session: {"ended": accounts.end_impersonation(session, request.state.user.user_id)})

    @app.get("/api/dashboard")
    def api_dashboard():
        with get_session() as session:
            return JSONResponse(_json_ready(dashboard_payload(session, date.today(), datetime.now())))

    @app.put("/api/dashboard/layout")
    def api_dashboard_layout(body: dict = Body(...)):
        """Save the dashboard's widget order, hidden widgets and widths."""
        def action(session):
            layout = preferences.clean_layout(body)
            preferences.set_preference(session, preferences.DASHBOARD_LAYOUT, layout)
            return {"layout": layout}
        return change(action)

    @app.delete("/api/dashboard/layout")
    def api_dashboard_layout_reset():
        """Back to the default layout."""
        return change(lambda session: {"reset": preferences.clear_preference(session, preferences.DASHBOARD_LAYOUT)})

    @app.get("/api/coattail")
    def api_coattail():
        """The Coattail page (§31): who holds the screener's companies, by manager."""
        with get_session() as session:
            rows = load_universe(session, date.today()).rows
            payload = coattail.holdings(session, rows, watchlists.watched_codes(session))
            return JSONResponse(_json_ready(payload | {"axes": list(AXES), "checks_per_axis": CHECKS_PER_AXIS}))

    @app.get("/api/coattail/notices")
    def api_coattail_notices(group: str = "directors", days: int = 30):
        """Coattail's Director trades and Substantial holders tabs: ASX notices
        for every company, with yours (held or watched) marked."""
        if group not in notice_views.GROUPS:
            raise HTTPException(status_code=400, detail=f"group must be one of {', '.join(notice_views.GROUPS)}")
        if days not in notice_views.DAYS:
            raise HTTPException(status_code=400, detail=f"days must be one of {', '.join(map(str, notice_views.DAYS))}")
        with get_session() as session:
            held = {p.asx_code for p in parcels_module.open_parcels(session)}
            return JSONResponse(_json_ready(notice_views.tab_payload(session, group, days, held, watchlists.watched_codes(session))))

    @app.get("/api/coattail/shorts")
    def api_coattail_shorts():
        """Coattail's Most shorted tab: ASIC's latest short positions, most shorted and rising fastest."""
        with get_session() as session:
            held = {p.asx_code for p in parcels_module.open_parcels(session)}
            return JSONResponse(_json_ready(short_positions.most_shorted(session, held, watchlists.watched_codes(session))))

    @app.get("/api/track-record")
    def api_track_record(version: str | None = None):
        with get_session() as session:
            return JSONResponse(_json_ready(track_record_payload(session, date.today(), version or None)))

    @app.get("/api/companies")
    def api_companies():
        with get_session() as session:
            return JSONResponse(companies_index(session))

    @app.get("/api/screener")
    def api_screener():
        with get_session() as session:
            return JSONResponse(_json_ready(screener_payload(session, date.today())))

    @app.get("/api/company/{asx_code}")
    def api_company(asx_code: str):
        with get_session() as session:
            payload = company_payload(session, asx_code.strip().upper(), date.today())
        if payload is None:
            raise HTTPException(status_code=404, detail=f"{asx_code.upper()} is not in the screener")
        return JSONResponse(_json_ready(payload))

    # ---------- portfolios and trades (§19.1) ----------
    def rows_by_code(session):
        return {r["asx_code"]: r for r in load_universe(session, date.today()).rows}

    def watch_rows(session):
        """Screener rows for shares and ETF rows for ETFs, by code: what watchlist triggers are judged on."""
        return rows_by_code(session) | funds_by_code(session, date.today())

    def portfolio_or_404(session, portfolio_id: str) -> Portfolio:
        found = parcels_module.get_portfolio(session, portfolio_id)  # only the current user's (§33)
        if found is None:
            raise HTTPException(status_code=404, detail="No such portfolio")
        return found

    def parcel_or_404(session, holding_id: str) -> Holding:
        try:
            found = session.get(Holding, uuid.UUID(holding_id))
        except ValueError:
            found = None
        if found is not None and parcels_module.get_portfolio(session, found.portfolio_id) is None:
            found = None  # someone else's (§33)
        if found is None:
            raise HTTPException(status_code=404, detail="No such parcel")
        return found

    def reindex_personal(session):
        """Saved changes are searchable at once (§32). Search must never block a save."""
        try:
            with session.begin_nested():
                search_indexer.reindex(session, ("personal",), "saved", everyone=False)
        except Exception:  # noqa: BLE001
            logger.exception("Search index: personal data not reindexed")

    def change(action):
        """Run one change in its own transaction; a HoldingsError is the
        person's mistake (400 with the message), never a half-saved change."""
        with get_session() as session:
            try:
                result = action(session)
                reindex_personal(session)
                session.commit()
            except (HoldingsError, WatchlistError, ScenarioError, SettingsError, preferences.PreferenceError,
                    accounts.AccountError, registries.RegistryError) as exc:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(exc)[:1].upper() + str(exc)[1:]) from None
        return JSONResponse(_json_ready(result))

    @app.get("/api/portfolios")
    def api_portfolios(brief: bool = False):
        """Every portfolio with its totals; ?brief=1 gives names only, for the menu."""
        with get_session() as session:
            if brief:
                portfolios = [portfolio_views.portfolio_info(p) for p in parcels_module.list_portfolios(session)]
            else:
                portfolios = portfolio_views.portfolio_summaries(session, rows_by_code(session), date.today())
            return JSONResponse(_json_ready({"tax_types": portfolio_views.tax_types(), "portfolios": portfolios}))

    @app.post("/api/portfolios")
    def api_create_portfolio(body: dict = Body(...)):
        def action(session):
            fields = trade_input.parse_portfolio(body)
            return portfolio_views.portfolio_info(parcels_module.create_portfolio(session, **fields))
        return change(action)

    # ---------- importing a broker's export (docs/kb/features/broker-import.md) ----------
    @app.post("/api/portfolios/import/preview")
    def api_import_preview(body: dict = Body(...)):
        """What a broker's file holds and what would be imported. Saves nothing."""
        with get_session() as session:
            try:
                return JSONResponse(_json_ready(importer.preview(session, body, date.today())))
            except HoldingsError as exc:
                raise HTTPException(status_code=400, detail=str(exc)[:1].upper() + str(exc)[1:]) from None

    @app.post("/api/portfolios/import")
    def api_import(body: dict = Body(...)):
        """Import the ticked lines into the chosen portfolio, or a new one."""
        return change(lambda session: importer.apply(session, body, date.today()))

    @app.get("/api/portfolios/{portfolio_id}")
    def api_portfolio(portfolio_id: str):
        with get_session() as session:
            portfolio = portfolio_or_404(session, portfolio_id)
            return JSONResponse(_json_ready(
                portfolio_views.portfolio_detail(session, portfolio, rows_by_code(session), date.today(),
                                                 funds_by_code(session, date.today()))))

    @app.patch("/api/portfolios/{portfolio_id}")
    def api_update_portfolio(portfolio_id: str, body: dict = Body(...)):
        def action(session):
            portfolio = portfolio_or_404(session, portfolio_id)
            fields = trade_input.parse_portfolio(body, partial=True)
            archived = fields.pop("archived", None)
            parcels_module.update_portfolio(session, portfolio, **fields)
            if archived is True and not portfolio.is_archived:
                parcels_module.archive_portfolio(session, portfolio)
            elif archived is False and portfolio.is_archived:
                parcels_module.unarchive_portfolio(session, portfolio)
            return portfolio_views.portfolio_info(portfolio)
        return change(action)

    @app.delete("/api/portfolios/{portfolio_id}")
    def api_delete_portfolio(portfolio_id: str):
        def action(session):
            portfolio = portfolio_or_404(session, portfolio_id)
            name = portfolio.name
            return {"deleted": name, "parcels_deleted": parcels_module.delete_portfolio(session, portfolio)}
        return change(action)

    @app.post("/api/portfolios/{portfolio_id}/buys")
    def api_buy(portfolio_id: str, body: dict = Body(...)):
        def action(session):
            portfolio = portfolio_or_404(session, portfolio_id)
            parcel = parcels_module.add_parcel(session, portfolio=portfolio, **trade_input.parse_buy(body, date.today()))
            return {"holding_id": str(parcel.holding_id), "asx_code": parcel.asx_code, "units": parcel.units,
                    "cost_base": cgt.cost_base(parcel.units, parcel.buy_price, parcel.buy_brokerage),
                    "discount_from": cgt.discount_eligible_from(parcel.buy_date)}
        return change(action)

    @app.post("/api/portfolios/{portfolio_id}/sales")
    def api_sell(portfolio_id: str, body: dict = Body(...)):
        def action(session):
            portfolio = portfolio_or_404(session, portfolio_id)
            sold = parcels_module.sell(session, portfolio=portfolio, **trade_input.parse_sell(body, date.today()))
            gains = [parcels_module.realised_gain(p) for p in sold]
            gets_discount = parcels_module.discount_rate(portfolio) > 0
            return {"parcels": len(sold), "units": sum((g.units for g in gains), Decimal("0")),
                    "proceeds": sum((g.proceeds for g in gains), Decimal("0")),
                    "gain": sum((g.gain for g in gains), Decimal("0")),
                    "discounted_units": sum((g.units for g in gains if g.discount_eligible and gets_discount), Decimal("0"))}
        return change(action)

    @app.delete("/api/parcels/{holding_id}")
    def api_delete_parcel(holding_id: str):
        def action(session):
            parcel = parcel_or_404(session, holding_id)
            if not parcel.is_open:
                raise HoldingsError("that parcel has been sold: undo the sale instead")
            parcels_module.delete_parcel(session, holding_id)
            return {"deleted": holding_id}
        return change(action)

    @app.post("/api/parcels/{holding_id}/undo-sale")
    def api_undo_sale(holding_id: str):
        def action(session):
            parcel_or_404(session, holding_id)
            parcel = parcels_module.undo_sale(session, holding_id)
            return {"holding_id": str(parcel.holding_id), "units": parcel.units}
        return change(action)

    # ---------- watchlists (§22) ----------
    def watchlist_or_404(session, watchlist_id: str):
        found = watchlists.get_watchlist(session, watchlist_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such watchlist")
        return found

    @app.get("/api/watchlists")
    def api_watchlists(brief: bool = False):
        """Every watchlist with its counts; ?brief=1 gives names only, for the menu."""
        with get_session() as session:
            if brief:
                lists = [{"watchlist_id": str(w.watchlist_id), "name": w.name} for w in watchlists.list_watchlists(session)]
            else:
                lists = watchlist_summaries(session, watch_rows(session))
            return JSONResponse(_json_ready({"watchlists": lists}))

    @app.post("/api/watchlists")
    def api_create_watchlist(body: dict = Body(...)):
        def action(session):
            w = watchlists.create_watchlist(session, body.get("name"))
            if body.get("asx_code"):  # created from a company page: add that company straight away
                watchlists.save_entry(session, w, body["asx_code"], watchlists.entry_fields({}))
            return {"watchlist_id": str(w.watchlist_id), "name": w.name}
        return change(action)

    @app.get("/api/watchlists/{watchlist_id}")
    def api_watchlist(watchlist_id: str):
        with get_session() as session:
            w = watchlist_or_404(session, watchlist_id)
            return JSONResponse(_json_ready(watchlist_detail(session, w, watch_rows(session))))

    @app.patch("/api/watchlists/{watchlist_id}")
    def api_rename_watchlist(watchlist_id: str, body: dict = Body(...)):
        def action(session):
            w = watchlists.rename_watchlist(session, watchlist_or_404(session, watchlist_id), body.get("name"))
            return {"watchlist_id": str(w.watchlist_id), "name": w.name}
        return change(action)

    @app.delete("/api/watchlists/{watchlist_id}")
    def api_delete_watchlist(watchlist_id: str):
        def action(session):
            w = watchlist_or_404(session, watchlist_id)
            name = w.name
            return {"deleted": name, "companies": watchlists.delete_watchlist(session, w)}
        return change(action)

    @app.put("/api/watchlists/{watchlist_id}/items/{asx_code}")
    def api_save_entry(watchlist_id: str, asx_code: str, body: dict = Body(default={})):
        def action(session):
            w = watchlist_or_404(session, watchlist_id)
            item = watchlists.save_entry(session, w, asx_code, watchlists.entry_fields(body))
            return {"watchlist": w.name, "asx_code": asx_code.strip().upper(), "note": item.note,
                    "mos_above": item.mos_above, "price_below": item.price_below, "yield_above": item.yield_above,
                    "nta_discount_above": item.nta_discount_above, "short_above": item.short_above}
        return change(action)

    @app.delete("/api/watchlists/{watchlist_id}/items/{asx_code}")
    def api_remove_entry(watchlist_id: str, asx_code: str):
        def action(session):
            w = watchlist_or_404(session, watchlist_id)
            return {"removed": watchlists.remove_entry(session, w, asx_code)}
        return change(action)

    # ---------- ETFs (§26) and LICs (§27) ----------
    def fund_list(kind):
        with get_session() as session:
            lists = [{"watchlist_id": str(w.watchlist_id), "name": w.name} for w in watchlists.list_watchlists(session)]
            return JSONResponse(_json_ready(etf_views.screener_payload(
                session, date.today(), watchlists.watched_codes(session), lists, kind)))

    def fund_page(asx_code, compare, kind):
        code = asx_code.strip().upper()
        with get_session() as session:
            detail = etf_views.etf_detail(session, code, date.today(), compare, watchlists.watched_codes(session), kind)
            if detail is None:
                raise HTTPException(status_code=404, detail=f"{code} isn't an {kind} Sift follows")
            detail["watchlists"] = company_watchlists(session, detail["etf"]["company_id"], detail["etf"])
            detail["kind"] = kind
            profile = fund_profiles.profile_payload(session, detail["etf"]["company_id"])
            if profile:
                profile["description_short"] = short_summary(profile["description"])
            detail["profile"] = profile
            return JSONResponse(_json_ready(detail))

    @app.get("/api/etfs")
    def api_etfs():
        return fund_list("ETF")

    @app.get("/api/etf/{asx_code}")
    def api_etf(asx_code: str, compare: str | None = None):
        return fund_page(asx_code, compare, "ETF")

    @app.get("/api/lics")
    def api_lics():
        return fund_list("LIC")

    @app.get("/api/lic/{asx_code}")
    def api_lic(asx_code: str, compare: str | None = None):
        return fund_page(asx_code, compare, "LIC")

    # ---------- admin console (§24) ----------
    def scenario_or_404(session, scenario_id: str):
        found = scenario_lab.get_scenario(session, scenario_id)  # only the current user's (§33)
        if found is None:
            raise HTTPException(status_code=404, detail="No such scenario")
        return found

    # ---------- search (§32) ----------
    @app.get("/api/search")
    def api_search(request: Request, q: str = "", type: list[str] = Query(default=[]), sector: list[str] = Query(default=[]),  # noqa: A002
                   recommendation: list[str] = Query(default=[]), mine: list[str] = Query(default=[]),
                   topic: list[str] = Query(default=[]), log: bool = False, query_id: int | None = None, scope: str = "all"):
        """`log=1` records the search (the page sends it once per new search, not per tick box).
        `scope=devkb` searches only the developer knowledge base (admins only, §36)."""
        if scope not in search_query.SCOPES:
            raise HTTPException(status_code=400, detail=f"scope must be one of {', '.join(search_query.SCOPES)}")
        selected = {"type": type, "sector": sector, "recommendation": recommendation, "mine": mine, "topic": topic}
        with get_session() as session:
            user, acting = request.state.user, request.state.acting
            result = search_query.search(session, q, selected, log=log, query_id=query_id, scope=scope,
                                         impersonated_by=user.user_id if user.user_id != acting.user_id else None)
            session.commit()
            return JSONResponse(_json_ready(result))

    @app.post("/api/search/click")
    def api_search_click(body: dict = Body(...)):
        """A result was opened: it rises for these words next time."""
        try:
            query_id, doc_id = int(body["query_id"]), str(body["doc_id"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="query_id and doc_id are needed") from None
        with get_session() as session:
            search_learning.record_click(session, query_id, doc_id, body.get("position"), accounts.current_user_id(session))
            session.commit()
        return JSONResponse({"ok": True})

    @app.post("/api/search/feedback")
    def api_search_feedback(body: dict = Body(...)):
        """Thumbs up (1), down (-1) or withdrawn (0) on a result for these words."""
        try:
            norm, doc_id, vote = str(body["norm"]), str(body["doc_id"]), int(body["vote"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="norm, doc_id and vote are needed") from None
        if vote not in (-1, 0, 1) or not norm.strip():
            raise HTTPException(status_code=400, detail="vote is 1, -1 or 0")
        with get_session() as session:
            search_learning.record_vote(session, norm, doc_id, vote, accounts.current_user_id(session))
            session.commit()
        return JSONResponse({"ok": True, "vote": vote})

    @app.get("/api/admin/search/insights")
    def api_search_insights(days: int = 30):
        with get_session() as session:
            return JSONResponse(_json_ready(search_learning.insights(session, max(1, min(days, 365)))))

    @app.get("/api/admin/search/synonyms")
    def api_synonyms():
        with get_session() as session:
            return JSONResponse({"synonyms": search_learning.list_synonyms(session)})

    @app.post("/api/admin/search/synonyms")
    def api_add_synonyms(body: dict = Body(...)):
        """A group of terms that mean the same: {"terms": ["cba", "commonwealth bank"]} or "cba, commonwealth bank"."""
        terms = body.get("terms")
        if isinstance(terms, str):
            terms = terms.split(",")
        with get_session() as session:
            try:
                group = search_learning.add_synonyms(session, terms)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)[:1].upper() + str(exc)[1:]) from None
            session.commit()
            return JSONResponse({"added": group, "synonyms": search_learning.list_synonyms(session)})

    @app.delete("/api/admin/search/synonyms/{synonym_id}")
    def api_delete_synonyms(synonym_id: int):
        with get_session() as session:
            search_learning.delete_synonyms(session, synonym_id)
            session.commit()
            return JSONResponse({"synonyms": search_learning.list_synonyms(session)})

    @app.get("/api/admin/search")
    def api_search_status():
        with get_session() as session:
            return JSONResponse(_json_ready(search_indexer.status(session)))

    @app.post("/api/admin/search/reindex")
    def api_search_reindex(body: dict = Body(default={})):
        """Rebuild the search index now: every area, or those listed in `areas`."""
        areas = [a for a in (body or {}).get("areas") or search_indexer.AREAS if a in search_indexer.AREAS]
        with get_session() as session:
            counts = search_indexer.reindex(session, areas, "manual")
            session.commit()
            return JSONResponse(_json_ready({"rebuilt": counts} | search_indexer.status(session)))

    @app.get("/api/admin/settings")
    def api_admin_settings():
        return JSONResponse(_json_ready(settings_payload()))

    @app.get("/api/admin/scenarios")
    def api_scenarios():
        with get_session() as session:
            rows = scenario_lab.list_scenarios(session, ("updated", "name"))
            return JSONResponse(_json_ready({"scenarios": [scenario_info(x) for x in rows]}))

    @app.post("/api/admin/scenarios")
    def api_create_scenario(body: dict = Body(...)):
        return change(lambda session: scenario_info(scenario_lab.save_scenario(
            session, body.get("name"), body.get("notes"), body.get("overrides"))))

    @app.get("/api/admin/scenarios/{scenario_id}")
    def api_scenario(scenario_id: str):
        with get_session() as session:
            return JSONResponse(_json_ready(scenario_info(scenario_or_404(session, scenario_id))))

    @app.put("/api/admin/scenarios/{scenario_id}")
    def api_update_scenario(scenario_id: str, body: dict = Body(...)):
        return change(lambda session: scenario_info(scenario_lab.save_scenario(
            session, body.get("name"), body.get("notes"), body.get("overrides"), scenario_or_404(session, scenario_id))))

    @app.delete("/api/admin/scenarios/{scenario_id}")
    def api_delete_scenario(scenario_id: str):
        def action(session):
            found = scenario_or_404(session, scenario_id)
            name = found.name
            session.delete(found)
            return {"deleted": name}
        return change(action)

    @app.post("/api/admin/run")
    def api_run_scenario(body: dict = Body(...)):
        """A what-if against live on today's data, from the editor's
        current values (saved or not). Reads only; POST because it carries
        the settings."""
        try:
            settings = model_settings.with_overrides(body.get("overrides") or {})
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        with get_session() as session:
            result = scenario_lab.run(session, settings, date.today(), watchlists.watched_codes(session))
        return JSONResponse(_json_ready(result))

    @app.get("/api/company/{asx_code}/workings")
    def api_workings(asx_code: str, scenario: str | None = None):
        with get_session() as session:
            settings, name = model_settings.LIVE, None
            if scenario:
                found = scenario_or_404(session, scenario)
                settings, name = scenario_lab.scenario_settings(found), found.name
            result = workings_module.company_workings(session, asx_code.strip().upper(), date.today(), settings)
            if result is None:
                raise HTTPException(status_code=404, detail=f"No workings for {asx_code.upper()}: no price or reports")
            result["scenario"] = name
            result["scenarios"] = [{"scenario_id": str(x.scenario_id), "name": x.name}
                                   for x in scenario_lab.list_scenarios(session)]
            return JSONResponse(_json_ready(result))

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _lan_address() -> str | None:
    """This PC's address on the home network (no traffic is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive web GUI for the ASX value screener.")
    parser.add_argument("--lan", action="store_true",
                        help="also listen on your home network so a phone can connect (requires GUI_PASSWORD in .env)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default: {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    password = os.getenv("GUI_PASSWORD") or None  # .env is loaded by src.config
    if args.lan and not password:
        print("--lan needs a password so others on your network can't see your holdings.\n"
              "Add a line like GUI_PASSWORD=choose-something-long to your .env file, then run again.")
        return 1

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"ASX Value Screener GUI - open http://localhost:{args.port} on this PC")
    if args.lan:
        address = _lan_address()
        if address:
            print(f"On your phone (same Wi-Fi): http://{address}:{args.port}")
        print("Log in with any username and the GUI_PASSWORD from .env.")
    problem = prepare_database()
    print("Database: up to date." if problem is None else
          f"Database update failed ({problem}). Pages may show errors; see docs/AS_BUILT.md §13.")
    if problem is None:
        print(prepare_search())
    print("Press Ctrl+C to stop.")

    import uvicorn  # imported here so tests can import this module without starting a server

    uvicorn.run(create_app(password), host=host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
