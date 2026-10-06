"""Show workings (docs/AS_BUILT.md §24): every figure on a company page,
step by step, with its inputs and formula, plus a sensitivity grid of
estimated value against discount and growth rates.

The steps reproduce src/valuation/engine.py's arithmetic one line at a
time; tests check the final figures equal compute_metrics() exactly, so
the workings can't drift from the numbers Sift actually uses. Each step
names the knowledge base entry (web/knowledge.json) that explains it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from screen_asx import annotate_row, args_from_settings
from src.admin.scenarios import MAX_AVERAGE_YEARS, _as_stored, with_average_years
from src.models import Company
from src.portfolio.holdings import position_summaries
from src.screening.actions import red_flags
from src.screening.enriched import valuation_status
from src.screening.scores import axis_scores, score_card
from src.settings import LIVE, ModelSettings
from src.valuation.engine import (
    DEFAULT_TREND_DAYS, _SECTOR_AWARE_SECTORS, _roe, compute_metrics, gather_inputs,
)

ONE = Decimal("1")
DISCOUNT_GRID = [Decimal(x) for x in ("0.07", "0.08", "0.09", "0.10", "0.11")]
GROWTH_STEPS = [Decimal(x) for x in ("-0.04", "-0.02", "0", "0.02", "0.04")]  # around the model's growth rate


def _v(label: str, value, unit: str = "") -> dict:
    return {"label": label, "value": value, "unit": unit}


def _step(title: str, formula: str, inputs: list[dict], result, unit: str = "", help_id: str | None = None,
          note: str | None = None) -> dict:
    return {"title": title, "formula": formula, "inputs": inputs, "result": result, "unit": unit,
            "help_id": help_id, "note": note}


def _cash_flow_model(base: Decimal, growth: Decimal, years: int, discount: Decimal, terminal: Decimal) -> dict:
    """The two-stage arithmetic of src/valuation/dcf.py and ddm.py, year by year."""
    rows, pv_total, flow = [], Decimal("0"), base
    for t in range(1, years + 1):
        flow = flow * (ONE + growth)
        factor = ONE / (ONE + discount) ** t
        pv = flow * factor
        pv_total += pv
        rows.append({"year": t, "flow": flow, "factor": factor, "present_value": pv})
    terminal_value = flow * (ONE + terminal) / (discount - terminal)
    pv_terminal = terminal_value / (ONE + discount) ** years
    return {"years": rows, "pv_stage1": pv_total, "terminal_value": terminal_value, "pv_terminal": pv_terminal,
            "final_flow": flow}


def valuation_steps(inputs, settings: ModelSettings) -> dict:
    company, price, report = inputs.company, inputs.price.close_price, inputs.report
    ddm = company.sector in _SECTOR_AWARE_SECTORS
    window = inputs.reports
    method = "DDM" if ddm else "DCF"
    growth = settings.ddm_growth_rate if ddm else settings.dcf_growth_rate
    field = "dividends_per_share" if ddm else "free_cash_flow"
    used = [{"year": r.fiscal_year, "value": getattr(r, field)} for r in window]
    values = [u["value"] for u in used if u["value"] is not None]
    base = sum(values) / Decimal(len(values)) if values else None
    out = {"method": method, "help_id": method.lower(),
           "why": (f"{company.sector}: valued on dividends, because a bank's, insurer's or REIT's free cash flow "
                   "is driven by its balance sheet rather than its business") if ddm
           else "Valued on free cash flow, the cash left after running and maintaining the business",
           "base": {"label": "dividend per share" if ddm else "free cash flow", "years": used, "average": base},
           "assumptions": [_v("Growth, years 1 to " + str(settings.stage1_years), growth * 100, "%"),
                           _v("Discount rate", settings.discount_rate * 100, "%"),
                           _v("Terminal growth", settings.terminal_growth_rate * 100, "%")],
           "steps": [], "estimated_value": None}
    if base is None or base <= 0:
        out["unavailable"] = f"No positive average {out['base']['label']} over the last {len(window)} years, so no {method} estimate."
        return out
    model = _cash_flow_model(base, growth, settings.stage1_years, settings.discount_rate, settings.terminal_growth_rate)
    out["years"] = model["years"]
    out["steps"].append(_step("Present value of years 1 to %d" % settings.stage1_years,
                              "sum of each year's cash flow / (1 + discount rate) ^ year",
                              [_v("Years", settings.stage1_years)], model["pv_stage1"], "$", "discount-rate"))
    out["steps"].append(_step("Terminal value", "final year's cash flow x (1 + terminal growth) / (discount rate - terminal growth)",
                              [_v("Final year's cash flow", model["final_flow"], "$"),
                               _v("Terminal growth", settings.terminal_growth_rate * 100, "%")],
                              model["terminal_value"], "$", "terminal-value"))
    out["steps"].append(_step("Present value of the terminal value", "terminal value / (1 + discount rate) ^ years",
                              [_v("Terminal value", model["terminal_value"], "$")], model["pv_terminal"], "$", "terminal-value"))
    if ddm:
        value = model["pv_stage1"] + model["pv_terminal"]
        out["steps"].append(_step("Estimated value per share", f"present value of years 1 to {settings.stage1_years} + present value of the terminal value",
                                  [_v(f"Years 1 to {settings.stage1_years}", model["pv_stage1"], "$"), _v("Terminal", model["pv_terminal"], "$")],
                                  value, "$", "estimated-value", note="Dividends are already per share."))
    else:
        shares = inputs.shares_outstanding
        cash, debt = report.cash_and_equivalents or Decimal("0"), report.total_debt or Decimal("0")
        equity = model["pv_stage1"] + model["pv_terminal"] + cash - debt
        out["steps"].append(_step("Equity value", "present values + cash - debt",
                                  [_v("Present values", model["pv_stage1"] + model["pv_terminal"], "$"),
                                   _v("Cash", cash, "$"), _v("Debt", debt, "$")], equity, "$", "dcf"))
        how = ("market capitalisation / share price" if inputs.price.market_cap and price
               else "net profit / earnings per share")
        out["steps"].append(_step("Shares on issue", how, [], shares, "", "shares-on-issue"))
        value = equity / shares if shares and shares > 0 else None
        out["steps"].append(_step("Estimated value per share", "equity value / shares on issue",
                                  [_v("Equity value", equity, "$"), _v("Shares", shares)], value, "$", "estimated-value"))
    out["estimated_value"] = value
    if value and value > 0:
        out["steps"].append(_step("Margin of safety", "(estimated value - price) / estimated value",
                                  [_v("Estimated value", value, "$"), _v("Price", price, "$")],
                                  (value - price) / value * 100, "%", "margin-of-safety"))
    return out


def ratio_steps(inputs, m: dict) -> list[dict]:
    r, price, shares = inputs.report, inputs.price.close_price, inputs.shares_outstanding
    bvps = r.total_equity / shares if r.total_equity and shares else None
    steps = [
        _step("P/E", "price / earnings per share", [_v("Price", price, "$"), _v("EPS", r.eps, "$")], m["pe_ratio"], "x", "pe"),
        _step("Book value per share", "shareholders' equity / shares on issue",
              [_v("Equity", r.total_equity, "$"), _v("Shares", shares)], bvps, "$", "book-value"),
        _step("P/B", "price / book value per share", [_v("Price", price, "$"), _v("Book value per share", bvps, "$")],
              m["pb_ratio"], "x", "pb"),
        _step("Graham Number", "square root of (22.5 x EPS x book value per share)",
              [_v("EPS", r.eps, "$"), _v("Book value per share", bvps, "$")], m["graham_number"], "$", "graham-number"),
        _step("ROE", "net profit / shareholders' equity", [_v("Net profit", r.net_profit_after_tax, "$"),
              _v("Equity", r.total_equity, "$")], m["roe"], "%", "roe"),
        _step("ROIC", "net profit / (debt + equity - cash)", [_v("Net profit", r.net_profit_after_tax, "$"),
              _v("Debt", r.total_debt, "$"), _v("Equity", r.total_equity, "$"), _v("Cash", r.cash_and_equivalents, "$")],
              m["roic"], "%", "roic"),
        _step("Debt to equity", "total debt / shareholders' equity", [_v("Debt", r.total_debt, "$"),
              _v("Equity", r.total_equity, "$")], m["debt_to_equity"], "x", "debt-to-equity"),
        _step("Price to free cash flow", "price / (free cash flow / shares)", [_v("Price", price, "$"),
              _v("Free cash flow", r.free_cash_flow, "$"), _v("Shares", shares)], m["price_to_fcf"], "x", "price-to-free-cash-flow"),
        _step("EV/EBIT", "(market capitalisation + debt - cash) / EBIT", [_v("Market capitalisation", inputs.price.market_cap, "$"),
              _v("Debt", r.total_debt, "$"), _v("Cash", r.cash_and_equivalents, "$"), _v("EBIT", r.ebit, "$")],
              m["ev_to_ebit"], "x", "ev-ebit"),
        _step("Cash dividend yield", "dividend per share / price", [_v("Dividend per share", r.dividends_per_share, "$"),
              _v("Price", price, "$")], m["uncapped_dividend_yield"], "%", "cash-dividend-yield"),
        _step("Grossed-up dividend yield", "dividend x (1 + franking % x tax rate / (1 - tax rate)) / price",
              [_v("Dividend per share", r.dividends_per_share, "$"), _v("Franking", r.franking_percentage, "%"),
               _v("Company tax rate", r.corporate_tax_rate, "%"), _v("Price", price, "$")],
              m["grossed_up_dividend_yield"], "%", "grossed-up-dividend-yield"),
        _step("Payout ratio", "dividend per share / earnings per share", [_v("Dividend per share", r.dividends_per_share, "$"),
              _v("EPS", r.eps, "$")], m["payout_ratio"], "%", "payout-ratio"),
    ]
    return steps


def test_steps(row: dict, s: ModelSettings) -> list[dict]:
    tests = (("Margin of safety", "margin_of_safety_percent", "mos_ok", "above", s.min_margin_of_safety, "%", "margin-of-safety"),
             ("Return on equity", "roe", "roe_ok", "above", s.min_roe, "%", "roe"),
             ("Debt to equity", "debt_to_equity", "de_ok", "below", s.max_debt_equity, "x", "debt-to-equity"),
             ("Grossed-up dividend yield", "grossed_up_dividend_yield", "yield_ok", "above", s.min_yield, "%",
              "grossed-up-dividend-yield"))
    return [{"name": n, "value": row[k], "unit": u, "rule": f"{w} {threshold.normalize():f}{u if u == '%' else ''}",
             "passed": row[ok] == "Y", "help_id": h} for n, k, ok, w, threshold, u, h in tests]


def marker_steps(inputs, m: dict, row: dict, s: ModelSettings) -> list[dict]:
    window = inputs.reports
    pairs = [(r.fiscal_year, r.operating_cash_flow, r.net_profit_after_tax) for r in window]
    history = inputs.history_reports or window
    dividends = [(r.fiscal_year, r.dividends_per_share) for r in reversed(history) if r.dividends_per_share is not None]
    latest, oldest = (window[0], window[-1]) if len(window) >= 2 else (None, None)
    roe_change = (_roe(latest) - _roe(oldest)) if latest and _roe(latest) is not None and _roe(oldest) is not None else None
    rev_change = ((latest.revenue - oldest.revenue) / oldest.revenue * 100
                  if latest and latest.revenue is not None and oldest.revenue else None)
    return [
        _step("Earnings quality", f"operating cash flow / net profit over {len(window)} years: STRONG from "
              f"{s.earnings_quality_strong.normalize():f}%, ADEQUATE from {s.earnings_quality_adequate.normalize():f}%, else WEAK",
              [v for y, ocf, npat in pairs for v in (_v(f"FY{y} operating cash flow", ocf, "$"), _v(f"FY{y} net profit", npat, "$"))],
              m["earnings_quality"], "", "earnings-quality",
              note=("Not assessed for banks, insurers and REITs, or for loss-makers" if m["cash_conversion"] is None
                    else f"Cash conversion {m['cash_conversion']:.0f}%")),
        _step("Price signal", f"below the 200-day average is DOWNTREND; also in the bottom {s.new_lows_range.normalize():f}% "
              "of the 52-week range is NEW LOWS", [_v("Against 200-day average", m["price_vs_200d"], "%"),
              _v("Position in 52-week range", m["range_position_52w"], "%")], row["price_signal"], "", "price-signal"),
        _step("Dividend trend", f"CUT if the latest is under {s.dividend_cut_ratio.normalize():f} x last year's or the earlier "
              f"median; GROWING if over {s.dividend_growth_ratio.normalize():f} x the oldest",
              [_v(f"FY{y}", d, "$") for y, d in dividends], m["dividend_trend"], "", "dividend-trend"),
        _step("Fundamentals trend", f"ROE change beyond {s.roe_trend_points.normalize():f} points or revenue change beyond "
              f"{(s.revenue_trend_ratio * 100).normalize():f}%, latest against oldest report",
              [_v("ROE change", roe_change, "points"), _v("Revenue change", rev_change, "%")], m["fundamentals_trend"], "",
              "fundamentals-trend"),
        _step("Momentum", f"margin of safety up more than {s.min_mos_trend.normalize():f} points over 30 days",
              [_v("Change over 30 days", row["margin_of_safety_trend"], "points")], "Yes" if row["momentum_ok"] == "Y" else "No",
              "", "margin-of-safety-trend"),
        _step("Value-trap risk", "passes the margin-of-safety test while fundamentals are DECLINING", [],
              "Yes" if row["trap_risk"] == "Y" else "No", "", "value-trap"),
        _step("Data confidence", "share of 11 key inputs present: HIGH from 90%, MEDIUM from 70%", [],
              m["data_confidence"], "", "data-confidence"),
    ]


def sensitivity(inputs, settings: ModelSettings) -> dict | None:
    """Estimated value and margin of safety across discount rates and
    growth rates around the company's model. Terminal growth stays put."""
    ddm = inputs.company.sector in _SECTOR_AWARE_SECTORS
    growth = settings.ddm_growth_rate if ddm else settings.dcf_growth_rate
    key = "ddm_growth_rate" if ddm else "dcf_growth_rate"
    growths = [growth + step for step in GROWTH_STEPS]
    discounts = sorted(set(DISCOUNT_GRID) | {settings.discount_rate})
    price = inputs.price.close_price
    rows = []
    for g in growths:
        cells = []
        for r in discounts:
            if r <= settings.terminal_growth_rate:
                cells.append(None)
                continue
            m = compute_metrics(inputs, settings=replace(settings, **{key: g, "discount_rate": r}))
            mos = m["margin_of_safety_percent"]
            cells.append({"value": m["dcf_intrinsic_value"], "mos": mos,
                          "status": valuation_status(mos, settings.min_margin_of_safety),
                          "current": g == growth and r == settings.discount_rate})
        rows.append({"growth": g * 100, "cells": cells})
    if all(c is None or c["value"] is None for row in rows for c in row["cells"]):
        return None
    return {"method": "DDM" if ddm else "DCF", "price": price, "discount_rates": [r * 100 for r in discounts], "rows": rows}


def company_workings(session, asx_code: str, today: date, settings: ModelSettings = LIVE) -> dict | None:
    company = session.execute(select(Company).where(Company.asx_code == asx_code)).scalar_one_or_none()
    if company is None:
        return None
    inputs = gather_inputs(session, company, fcf_average_years=MAX_AVERAGE_YEARS, trend_days=DEFAULT_TREND_DAYS)
    if inputs is None:
        return None
    inputs = with_average_years(inputs, settings.fcf_average_years)
    m = compute_metrics(inputs, settings=settings)
    stored = _as_stored(m)
    row = {"asx_code": company.asx_code, "company_name": company.company_name, "sector": company.sector,
           "current_price": inputs.price.close_price} | stored
    if settings != LIVE:  # momentum stays live: compare with the live figure, as the what-if lab does
        live = _as_stored(compute_metrics(with_average_years(inputs, LIVE.fcf_average_years)))
        row["margin_of_safety_trend"] = live["margin_of_safety_trend"]
    positions = position_summaries(session, today)
    row = annotate_row(row, args_from_settings(settings), positions.get(asx_code), today, settings)
    scores = axis_scores(score_card(row, inputs.report, settings))
    return {
        "asx_code": company.asx_code, "as_of_date": inputs.price.price_date, "price": inputs.price.close_price,
        "valuation": valuation_steps(inputs, settings),
        "ratios": ratio_steps(inputs, m),
        "tests": test_steps(row, settings),
        "markers": marker_steps(inputs, m, row, settings),
        "action": {"action": row["action"], "reason": row["action_reason"], "flags": red_flags(row, settings),
                   "held": row["held"] is not None, "help_id": "suggested-action"},
        "score": {"total": sum(scores.values()), "by_axis": scores, "help_id": "score-wheel"},
        "status": valuation_status(row["margin_of_safety_percent"], settings.min_margin_of_safety),
        "estimated_value": m["dcf_intrinsic_value"],
        "margin_of_safety": m["margin_of_safety_percent"],
        "sensitivity": sensitivity(inputs, settings),
    }
