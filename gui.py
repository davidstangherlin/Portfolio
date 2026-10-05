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

Read-only: it never writes to the database.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import secrets
import socket
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from screen_asx import load_annotated_rows, parse_args as screener_defaults
from src.config import get_session
from src.models import Company, DailyPrice, DividendPayment, FinancialReport, ValuationMetric
from src.screening.actions import ACTION_ORDER, red_flags
from src.screening.enriched import load_universe, score_list, with_extras
from src.screening.scores import AXES, CHECKS_PER_AXIS, axis_scores, score_card
from src.tracking.signals import signal_changes, tracking_status
from src.valuation import dcf as dcf_module, ddm as ddm_module

REPO_DIR = Path(__file__).resolve().parent
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
    "overall", "momentum_ok", "trap_risk", "held", "action", "action_reason",
)


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
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


def _card_payload(card) -> dict:
    scores = axis_scores(card)
    return {
        axis: {"score": scores[axis], "checks": [{"label": c.label, "passed": c.passed} for c in card[axis]]}
        for axis in AXES
    }


def screener_payload(session, today: date) -> dict:
    universe = load_universe(session, today)
    args = universe.args
    out = []
    for row in universe.rows:
        item = {f: row.get(f) for f in _SCREENER_FIELDS}
        item["scores"] = score_list(row)
        out.append(item)
    return {
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
        select(DailyPrice.price_date, DailyPrice.close_price)
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
        "model": _model_assumptions(row.get("valuation_method")),
        "position": None if position is None else {
            "units": position.units, "cost_base": position.cost_base,
            "next_discount_date": position.next_discount_date,
            "units_pending_discount": position.units_pending_discount,
        },
        "prices": [[d, c] for d, c in prices],
        "dividends": [{"ex_date": d, "amount": a, "abnormal": ab} for d, a, ab in dividends],
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
RUN_STILL_GOING_HOURS = 3  # an unfinished log younger than this is a run in progress, not a crash


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
    prices = session.execute(select(func.max(DailyPrice.price_date))).scalar_one()
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


def _two_latest_closes(session, codes: set[str]) -> dict[str, list]:
    if not codes:
        return {}
    rows = session.execute(text("""
        SELECT asx_code, close_price, price_date FROM (
            SELECT c.asx_code, p.close_price, p.price_date,
                   ROW_NUMBER() OVER (PARTITION BY p.company_id ORDER BY p.price_date DESC) AS n
            FROM daily_prices p JOIN companies c ON c.company_id = p.company_id
            WHERE c.asx_code = ANY(:codes)
        ) ranked WHERE n <= 2 ORDER BY asx_code, price_date DESC
    """), {"codes": sorted(codes)}).all()
    out: dict[str, list] = {}
    for code, close, _ in rows:
        out.setdefault(code, []).append(close)
    return out


def portfolio_payload(session, universe, today: date) -> dict:
    """Every open holding valued at the latest close, with the day's move
    and the screener's suggested action."""
    rows = {r["asx_code"]: r for r in universe.rows}
    closes = _two_latest_closes(session, set(universe.positions))
    names = dict(session.execute(
        select(Company.asx_code, Company.company_name).where(Company.asx_code.in_(universe.positions))
    ).all()) if universe.positions else {}
    holdings = []
    for code, pos in sorted(universe.positions.items()):
        row = rows.get(code)
        last = closes.get(code, [])
        price = last[0] if last else None
        value = pos.units * price if price is not None else None
        holdings.append({
            "asx_code": code, "company_name": names.get(code), "units": pos.units, "cost_base": pos.cost_base,
            "price": price, "value": value,
            "gain": value - pos.cost_base if value is not None else None,
            "day_change": pos.units * (last[0] - last[1]) if len(last) == 2 else None,
            "action": row["action"] if row else None, "action_reason": row["action_reason"] if row else None,
            "valuation_status": row["valuation_status"] if row else None,
            "next_discount_date": pos.next_discount_date, "units_pending_discount": pos.units_pending_discount,
        })
    priced = [h for h in holdings if h["value"] is not None]
    value = sum((h["value"] for h in priced), Decimal("0"))
    cost = sum((h["cost_base"] for h in priced), Decimal("0"))
    day = [h["day_change"] for h in priced if h["day_change"] is not None]
    return {
        "holdings": holdings,
        "value": value if priced else None,
        "cost_base": cost if priced else None,
        "gain": value - cost if priced else None,
        "day_change": sum(day, Decimal("0")) if day else None,
        "unpriced": [h["asx_code"] for h in holdings if h["value"] is None],
    }


def _brief(row: dict) -> dict:
    return {"asx_code": row["asx_code"], "company_name": row["company_name"], "sector": row["sector"],
            "action": row["action"], "action_reason": row["action_reason"], "price": row["current_price"],
            "margin_of_safety_percent": row["margin_of_safety_percent"],
            "valuation_status": row["valuation_status"], "scores": score_list(row)}


def dashboard_payload(session, today: date, now: datetime, log_dir: Path = LOG_DIR) -> dict:
    universe = load_universe(session, today)
    rows = universe.rows
    portfolio = portfolio_payload(session, universe, today)

    attention = [_brief(r) for r in rows if r["held"] is not None and r["action"] in ATTENTION_ACTIONS]
    attention.sort(key=lambda b: (ATTENTION_ACTIONS.index(b["action"]), b["asx_code"]))
    screened = {r["asx_code"] for r in rows}
    cgt_soon = [
        {"asx_code": h["asx_code"], "date": h["next_discount_date"], "units": h["units_pending_discount"],
         "days": (h["next_discount_date"] - today).days}
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
        "not_screened": sorted(set(universe.positions) - screened),
        "cgt_soon": cgt_soon,
        "cgt_soon_days": CGT_SOON_DAYS,
        "portfolio": portfolio,
        "changes": signal_changes(session),
        "tracking": tracking_status(session),
        "top": top,
        "thresholds": {"margin_of_safety": universe.args.min_margin_of_safety, "roe": universe.args.min_roe,
                       "debt_to_equity": universe.args.max_debt_equity, "yield": universe.args.min_yield},
    }


def companies_index(session) -> list[dict]:
    """Code and name of every screened company, for the menu bar search."""
    rows = session.execute(text("SELECT asx_code, company_name FROM asx_value_screener ORDER BY asx_code")).all()
    return [{"code": code, "name": name} for code, name in rows]


def create_app(password: str | None = None) -> FastAPI:
    app = FastAPI(title="ASX Value Screener", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        # Covers every route, including the static files.
        if password and not _authorised(request.headers.get("authorization"), password):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ASX Value Screener"'})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/status")
    def api_status():
        with get_session() as session:
            return JSONResponse(_json_ready(status_payload(session, date.today(), datetime.now())))

    @app.get("/api/dashboard")
    def api_dashboard():
        with get_session() as session:
            return JSONResponse(_json_ready(dashboard_payload(session, date.today(), datetime.now())))

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
    print("Press Ctrl+C to stop.")

    import uvicorn  # imported here so tests can import this module without starting a server

    uvicorn.run(create_app(password), host=host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
