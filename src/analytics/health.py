"""Financial health (docs/kb/features/financial-health.md): the Piotroski
F-Score and the Altman Z-Score, worked out nightly into `financial_health`.

F-Score (Piotroski, 2000): nine pass-or-fail checks on the latest two years
of statements, one point each. Profitability: a profit (return on assets
above zero), cash in from operations, return on assets improving, and cash
flow above profit. Funding: debt falling against assets, the current ratio
improving, and no new shares issued. Efficiency: gross margin improving and
sales per dollar of assets improving. Return on assets and asset turnover
use the assets at the start of the year (the year before's), as Piotroski
did, falling back to the year's own assets when an earlier year is missing.
A check with missing data neither passes nor fails: Sift says how many of
the nine it could make. 7 to 9 is Strong, 4 to 6 Middling, 0 to 3 Weak,
and under 6 checks with data is Not enough data yet.

Z-Score (Altman, 1968), the original for public companies:
1.2 x working capital / assets + 1.4 x retained earnings / assets
+ 3.3 x EBIT / assets + 0.6 x market value of equity / liabilities
+ 1.0 x sales / assets. Above 2.99 Safe, 1.81 to 2.99 Grey, below 1.81
Distress. A Distress share gets a caution beside its action; the action
itself never changes, so the rules version doesn't either.

Neither was designed for banks, insurers or property trusts (their
balance sheets work differently), so those sectors get no score."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

logger = logging.getLogger(__name__)

EXCLUDED_SECTORS = {"Financial Services": "banks, insurers and other financial companies",
                    "Real Estate": "property trusts and other real estate companies"}
MIN_CHECKS = 6
Z_SAFE, Z_DISTRESS = 2.99, 1.81
SHARE_CHANGE_TOLERANCE = 0.005   # a 0.5% change in shares on issue is rounding, not an issue

CHECKS = (
    ("profit", "Made a profit", "Net profit / assets above zero"),
    ("cash", "Cash came in from operations", "Operating cash flow above zero"),
    ("roa_up", "Return on assets improved", "Net profit / assets higher than the year before"),
    ("accruals", "Profit backed by cash", "Operating cash flow / assets above net profit / assets"),
    ("debt_down", "Debt fell against assets", "Total debt / total assets lower than the year before (or no debt either year)"),
    ("liquidity_up", "Short-term position improved", "Current assets / current liabilities higher than the year before"),
    ("no_new_shares", "No new shares issued", "Shares on issue no higher than the year before"),
    ("margin_up", "Gross margin improved", "Gross profit / revenue higher than the year before"),
    ("turnover_up", "More sales per dollar of assets", "Revenue / assets higher than the year before"),
)


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _div(a, b) -> float | None:
    a, b = _f(a), _f(b)
    return a / b if a is not None and b not in (None, 0) else None


def _gt(a, b) -> bool | None:
    return None if a is None or b is None else a > b


def _shares(r: dict) -> float | None:
    """Shares on issue, or (failing that) profit / earnings per share."""
    if r.get("shares_outstanding") is not None:
        return _f(r["shares_outstanding"])
    npat, eps = _f(r.get("net_profit_after_tax")), _f(r.get("eps"))
    return npat / eps if npat and eps and npat > 0 and eps > 0 else None


def piotroski(reports: list[dict]) -> dict:
    """{score, checks_with_data, level, checks: [{key, label, rule, passed}], fiscal_year}.
    `reports`: annual reports, newest first (dicts of financial_reports columns)."""
    if len(reports) < 2:
        return {"score": None, "checks_with_data": 0, "level": "NOT_ENOUGH", "checks": [], "fiscal_year": None}
    now, before = reports[0], reports[1]
    earlier = reports[2] if len(reports) > 2 else {}
    start_now = before.get("total_assets") or now.get("total_assets")      # assets at the start of the year
    start_before = earlier.get("total_assets") or before.get("total_assets")
    roa_now, roa_before = _div(now.get("net_profit_after_tax"), start_now), _div(before.get("net_profit_after_tax"), start_before)
    cfo_now = _f(now.get("operating_cash_flow"))
    cfo_assets = _div(now.get("operating_cash_flow"), start_now)
    lev_now, lev_before = _div(now.get("total_debt"), now.get("total_assets")), _div(before.get("total_debt"), before.get("total_assets"))
    cur_now, cur_before = _div(now.get("current_assets"), now.get("current_liabilities")), _div(before.get("current_assets"), before.get("current_liabilities"))
    sh_now, sh_before = _shares(now), _shares(before)
    gm_now, gm_before = _div(now.get("gross_profit"), now.get("revenue")), _div(before.get("gross_profit"), before.get("revenue"))
    at_now, at_before = _div(now.get("revenue"), start_now), _div(before.get("revenue"), start_before)

    debt_down = None
    if lev_now is not None and lev_before is not None:
        debt_down = lev_now < lev_before or (lev_now == 0 and lev_before == 0)
    no_new = None
    if sh_now is not None and sh_before:
        no_new = sh_now <= sh_before * (1 + SHARE_CHANGE_TOLERANCE)
    passed = {
        "profit": None if roa_now is None else roa_now > 0,
        "cash": None if cfo_now is None else cfo_now > 0,
        "roa_up": _gt(roa_now, roa_before),
        "accruals": _gt(cfo_assets, roa_now),
        "debt_down": debt_down,
        "liquidity_up": _gt(cur_now, cur_before),
        "no_new_shares": no_new,
        "margin_up": _gt(gm_now, gm_before),
        "turnover_up": _gt(at_now, at_before),
    }
    checks = [{"key": k, "label": label, "rule": rule, "passed": passed[k]} for k, label, rule in CHECKS]
    with_data = sum(1 for c in checks if c["passed"] is not None)
    score = sum(1 for c in checks if c["passed"])
    if with_data < MIN_CHECKS:
        level = "NOT_ENOUGH"
    else:
        level = "STRONG" if score >= 7 else "MIDDLING" if score >= 4 else "WEAK"
    return {"score": score, "checks_with_data": with_data, "level": level, "checks": checks,
            "fiscal_year": now.get("fiscal_year")}


def altman(report: dict, market_value: float | None) -> dict:
    """{z, zone, parts} or zone None when an input is missing."""
    assets, liabilities = _f(report.get("total_assets")), _f(report.get("total_liabilities"))
    ca, cl = _f(report.get("current_assets")), _f(report.get("current_liabilities"))
    parts = {
        "working_capital": _div(ca - cl, assets) if ca is not None and cl is not None else None,
        "retained_earnings": _div(report.get("retained_earnings"), assets),
        "ebit": _div(report.get("ebit"), assets),
        "market_value": _div(market_value, liabilities),
        "sales": _div(report.get("revenue"), assets),
    }
    if any(v is None for v in parts.values()):
        return {"z": None, "zone": None, "parts": parts}
    z = (1.2 * parts["working_capital"] + 1.4 * parts["retained_earnings"] + 3.3 * parts["ebit"]
         + 0.6 * parts["market_value"] + 1.0 * parts["sales"])
    zone = "SAFE" if z > Z_SAFE else "DISTRESS" if z < Z_DISTRESS else "GREY"
    return {"z": z, "zone": zone, "parts": parts}


F_WORDS = {"STRONG": "Strong", "MIDDLING": "Middling", "WEAK": "Weak", "NOT_ENOUGH": "Not enough data yet"}
Z_WORDS = {"SAFE": ("Safe zone", "Low risk of financial distress on these figures."),
           "GREY": ("Grey zone", "Some risk of financial distress: worth watching."),
           "DISTRESS": ("Distress zone", "In Altman's study, companies scoring this low often failed within two years. Read the latest results with care.")}


def caution_text(z: float | None, zone: str | None) -> str | None:
    """The note added to an action's reason for a Distress-zone share."""
    if zone != "DISTRESS" or z is None:
        return None
    return f"possible financial distress (Altman Z-Score {z:.1f}, distress zone): check the balance sheet and latest results"


@dataclass
class _Row:
    company_id: object
    sector: str | None
    market_cap: float | None


def refresh(session, today: date) -> dict:
    """Recompute every active share's health. Returns counts for the log."""
    companies = session.execute(text("""
        SELECT c.company_id, c.sector,
               (SELECT p.market_cap FROM daily_prices p WHERE p.company_id = c.company_id AND p.market_cap IS NOT NULL
                ORDER BY p.price_date DESC LIMIT 1) AS market_cap,
               (SELECT p.close_price FROM daily_prices p WHERE p.company_id = c.company_id
                ORDER BY p.price_date DESC LIMIT 1) AS price
        FROM companies c WHERE c.is_active AND c.security_type = 'SHARE'""")).mappings().all()
    done = scored = distress = 0
    for c in companies:
        excluded = EXCLUDED_SECTORS.get(c["sector"] or "")
        reports = [dict(r) for r in session.execute(text("""
            SELECT * FROM financial_reports WHERE company_id = :c AND period_type = 'FY'
            ORDER BY fiscal_year DESC LIMIT 3"""), {"c": c["company_id"]}).mappings()]
        if not reports:
            continue
        f = piotroski(reports) if not excluded else None
        market = _f(c["market_cap"])
        if market is None and c["price"] is not None and reports[0].get("shares_outstanding") is not None:
            market = float(c["price"]) * float(reports[0]["shares_outstanding"])
        zr = altman(reports[0], market) if not excluded else {"z": None, "zone": None, "parts": {}}
        session.execute(text("""
            INSERT INTO financial_health (company_id, as_of_date, fiscal_year, f_score, f_checks, f_level, f_detail,
                z_score, z_zone, z_parts, excluded_reason, computed_at)
            VALUES (:c, :d, :fy, :fs, :fc, :fl, CAST(:fd AS JSONB), :z, :zz, CAST(:zp AS JSONB), :ex, now())
            ON CONFLICT (company_id) DO UPDATE SET as_of_date = EXCLUDED.as_of_date, fiscal_year = EXCLUDED.fiscal_year,
                f_score = EXCLUDED.f_score, f_checks = EXCLUDED.f_checks, f_level = EXCLUDED.f_level,
                f_detail = EXCLUDED.f_detail, z_score = EXCLUDED.z_score, z_zone = EXCLUDED.z_zone,
                z_parts = EXCLUDED.z_parts, excluded_reason = EXCLUDED.excluded_reason, computed_at = now()"""),
            {"c": c["company_id"], "d": today, "fy": reports[0]["fiscal_year"],
             "fs": f and f["score"], "fc": f and f["checks_with_data"], "fl": f and f["level"],
             "fd": json.dumps(f and f["checks"]), "z": zr["z"], "zz": zr["zone"], "zp": json.dumps(zr["parts"]),
             "ex": excluded})
        done += 1
        scored += bool(f and f["level"] != "NOT_ENOUGH")
        distress += zr["zone"] == "DISTRESS"
    return {"companies": done, "f_scored": scored, "distress": distress}


def company_health(session, company_id) -> dict | None:
    """The company page's Financial health card, in plain words."""
    r = session.execute(text("SELECT * FROM financial_health WHERE company_id = :c"), {"c": company_id}).mappings().first()
    if r is None:
        return None
    zone = r["z_zone"]
    return {"fiscal_year": r["fiscal_year"], "excluded_reason": r["excluded_reason"],
            "f_score": r["f_score"], "f_checks": r["f_checks"], "f_level": r["f_level"],
            "f_words": F_WORDS.get(r["f_level"]) if r["f_level"] else None, "f_detail": r["f_detail"] or [],
            "z_score": _f(r["z_score"]), "z_zone": zone,
            "z_words": Z_WORDS[zone][0] if zone else None, "z_meaning": Z_WORDS[zone][1] if zone else None,
            "z_parts": r["z_parts"] or {}}
