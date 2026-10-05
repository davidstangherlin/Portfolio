#!/usr/bin/env python3
"""Interactive web GUI for the ASX value screener (docs/AS_BUILT.md §20).

    python gui.py              # this PC only: open http://localhost:8000
    python gui.py --lan        # also your phone on home Wi-Fi (needs GUI_PASSWORD in .env)

A small local web server over the same database and the same rules as
screen_asx.py - it calls the screener's own row loader, so the browser
and the command line can never disagree. Two screens: a filterable,
sortable screener table, and a company page with a score wheel (see
src/screening/scores.py), price against estimated value, price and
margin-of-safety history, and five years of financials.

Read-only: it never writes to the database.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import secrets
import socket
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from screen_asx import load_annotated_rows, parse_args as screener_defaults
from src.config import get_session
from src.models import Company, DailyPrice, DividendPayment, FinancialReport, ValuationMetric
from src.screening.actions import ACTION_ORDER, red_flags
from src.screening.scores import AXES, CHECKS_PER_AXIS, axis_scores, score_card
from src.valuation import dcf as dcf_module, ddm as ddm_module

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8000
PRICE_HISTORY_DAYS = 365
REPORT_HISTORY_YEARS = 5

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


def _latest_extras(session) -> tuple[dict[str, dict], dict[str, FinancialReport], date | None]:
    """Per company: the valuation_metrics columns the screener view doesn't
    carry (roic, graham_number), and the latest FY report for the health
    checks. Two DISTINCT ON queries rather than one per company."""
    metrics = session.execute(text("""
        SELECT DISTINCT ON (v.company_id) c.asx_code, v.roic, v.graham_number, v.as_of_date
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


def _with_extras(row: dict, extras: dict | None) -> dict:
    row = dict(row)
    row["roic"] = (extras or {}).get("roic")
    row["graham_number"] = (extras or {}).get("graham_number")
    return row


def _card_payload(card) -> dict:
    scores = axis_scores(card)
    return {
        axis: {"score": scores[axis], "checks": [{"label": c.label, "passed": c.passed} for c in card[axis]]}
        for axis in AXES
    }


def screener_payload(session, today: date) -> dict:
    args = screener_defaults([])
    rows, _ = load_annotated_rows(session, args, today)
    extras, reports, as_of = _latest_extras(session)
    out = []
    for r in rows:
        row = _with_extras(r, extras.get(r["asx_code"]))
        scores = axis_scores(score_card(row, reports.get(r["asx_code"])))
        item = {f: row.get(f) for f in _SCREENER_FIELDS}
        item["scores"] = [scores[a] for a in AXES]
        out.append(item)
    return {
        "as_of": as_of,
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

    row = _with_extras(row, {"roic": metric.roic, "graham_number": metric.graham_number})
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
