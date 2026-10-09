"""Read-only tools an AI assistant can call (docs/kb/features/ai-and-graph.md).

Each tool answers one kind of question from Sift's own data, as the pages
would, for the current person (src/accounts.py): their holdings decide the
held calls, and their portfolios and watchlists are the only personal data
it sees. Nothing here writes. Answers are plain JSON with short field
names, units in the names, and the reasons Sift gives in words, because
that is what a language model uses best.

The same TOOLS list feeds the local MCP server (src/ai/mcp_server.py) and
the API (`GET /api/ai/tools`, `POST /api/ai/tools/{name}`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import text

NOT_ADVICE = "Sift's suggested actions are rule-based research prompts, not financial advice."
KNOWLEDGE = Path(__file__).resolve().parents[2] / "web" / "knowledge.json"


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]                      # fn(session, **params)
    params: dict[str, dict] = field(default_factory=dict)   # name -> {"type", "description", "required", "default"}


def jsonable(value):
    """Decimals, dates and ids as plain JSON values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


class ToolError(ValueError):
    """A question the tool can't answer (unknown code, bad argument); the message is for the AI to relay."""


def _code(code: str) -> str:
    code = (code or "").strip().upper().removesuffix(".AX")
    if not re.fullmatch(r"[A-Z0-9]{2,6}", code):
        raise ToolError("give an ASX code such as BHP")
    return code


def _kind(session, code: str) -> str | None:
    return session.execute(text("SELECT security_type FROM companies WHERE asx_code = :c"), {"c": code}).scalar()


def _funds(session, today):
    import gui
    from src.watchlist import lists
    return gui.funds_by_code(session, today, lists.watched_codes(session))


# ---------- the tools ----------

def search_sift(session, query: str, limit: int = 10) -> dict:
    from src.search.query import search
    res = search(session, query)
    return {"query": query, "results": [{"title": r["title"], "type": r["type"], "code": r.get("code"),
                                         "summary": r.get("subtitle"), "page": r["url"]} for r in res["results"][:max(1, min(limit, 25))]]}


def company(session, code: str) -> dict:
    """Facts and Sift's view of one share, ETF or LIC."""
    import gui
    code = _code(code)
    kind = _kind(session, code)
    if kind is None:
        raise ToolError(f"Sift doesn't follow {code}")
    today = date.today()
    if kind in ("ETF", "LIC"):
        f = _funds(session, today).get(code)
        if f is None:
            raise ToolError(f"no current figures for {code}")
        keep = ("asx_code", "company_name", "category", "issuer", "current_price", "price_date", "day_change_percent",
                "mer_percent", "fum_aud", "distribution_yield_12m", "return_1y", "return_3y", "return_5y",
                "premium_now", "nta_pre_tax", "held", "watchlists", "benchmark")
        return {"type": kind, **{k: f.get(k) for k in keep if k in f}, "note": NOT_ADVICE}
    p = gui.company_payload(session, code, today)
    if p is None:
        raise ToolError(f"{code} has no valuation yet")
    c = p["company"]
    from src.screening.enriched import load_universe
    row = next((r for r in load_universe(session, today).rows if r["asx_code"] == code), {})  # status and score wheel
    return {
        "type": "SHARE", "code": code, "name": c["company_name"], "sector": c["sector"], "industry": c.get("industry"),
        "summary": c.get("business_summary_short"), "price": c["current_price"], "as_of": c["as_of_date"],
        "estimated_value": c.get("dcf_intrinsic_value"), "valuation_method": c.get("valuation_method"),
        "margin_of_safety_percent": c["margin_of_safety_percent"], "valuation_status": row.get("valuation_status"),
        "ratios": {k: c.get(k) for k in ("pe_ratio", "pb_ratio", "roe", "roic", "debt_to_equity", "grossed_up_dividend_yield",
                                         "payout_ratio", "price_to_fcf", "ev_to_ebit", "graham_number")},
        "action": c["action"], "action_reason": c["action_reason"], "tests": p["tests"], "red_flags": p["flags"],
        "score_total": sum((row.get("axis_scores") or {}).values()) or None, "scores_by_spoke": row.get("axis_scores"),
        "position": p["position"],
        "watchlists": [w["name"] for w in p["watchlists"] if w["member"]], "note": NOT_ADVICE,
    }


def explain_call(session, code: str) -> dict:
    """Why Sift suggests what it does for a share: the tests, flags, markers,
    the call's recent history for this person, and how such calls have done."""
    from src.tracking import report
    from src.tracking.signals import person_nights
    c = company(session, code)
    if c["type"] != "SHARE":
        raise ToolError(f"{c.get('asx_code', code)} is an {c['type']}: Sift doesn't make calls on funds; ask for its facts instead")
    import gui
    p = gui.company_payload(session, c["code"], date.today())["company"]
    markers = {k: p.get(k) for k in ("earnings_quality", "price_signal", "dividend_trend", "fundamentals_trend",
                                    "margin_of_safety_trend", "data_confidence", "trap_risk", "momentum_ok")}
    history, last = [], None
    for n in person_nights(session, date.today() - timedelta(days=365)):
        if n["asx_code"] == c["code"] and n["action"] != last:
            history.append({"date": n["snapshot_date"], "action": n["action"], "held": n["held"]})
            last = n["action"]
    record = {}
    v = report.verdict(session, None)
    for months in (3, 1, 6, 12):
        hit = next((a for a in v[months]["actions"] if a["action"] == c["action"]), None)
        if hit:
            record = {"horizon_months": months, "signals": hit["signals"], "beat_average_percent": hit["beat_rate"],
                      "average_excess_return_points": hit["avg_excess"], "confidence": hit["confidence"]}
            break
    return {
        "code": c["code"], "name": c["name"], "action": c["action"], "reason": c["action_reason"],
        "held": c["position"] is not None,
        "how_actions_work": ("Shares not held get BUY, INVESTIGATE, WATCH, AVOID or IGNORE from the four value tests and red flags; "
                             "held shares get HOLD, ACCUMULATE, REVIEW or SELL."),
        "valuation": {"estimated_value": c["estimated_value"], "method": c["valuation_method"], "price": c["price"],
                      "margin_of_safety_percent": c["margin_of_safety_percent"], "status": c["valuation_status"]},
        "tests": c["tests"], "red_flags": c["red_flags"], "markers": markers,
        "history_last_year": history[-12:],
        "track_record_for_this_action": record or "not enough results yet",
        "note": NOT_ADVICE,
    }


def my_portfolio(session) -> dict:
    """The current person's holdings with value, gain and Sift's call on each."""
    import gui
    from src.screening.enriched import load_universe
    today = date.today()
    d = gui.portfolio_payload(session, load_universe(session, today), today, _funds(session, today))
    keep = ("asx_code", "company_name", "security_type", "units", "value", "cost_base", "gain", "gain_percent",
            "day_change_percent", "action", "action_reason", "weight_percent")
    return {
        "totals": {k: d.get(k) for k in ("value", "cost_base", "gain", "gain_percent", "day_change", "day_change_percent") if k in d},
        "holdings": [{k: h.get(k) for k in keep if k in h} for h in d["holdings"]],
        "portfolios": [{k: p.get(k) for k in ("name", "tax_type_label", "value", "gain", "holdings", "sales") if k in p} for p in d["portfolios"]],
        "note": NOT_ADVICE,
    }


def my_watchlists(session) -> dict:
    """The current person's watchlists, each entry with its note and which triggers are met."""
    from src.screening.enriched import load_universe
    from src.watchlist import lists
    today = date.today()
    rows = {r["asx_code"]: r for r in load_universe(session, today).rows} | _funds(session, today)
    out = {}
    for item, code, name in lists.entries(session):
        met = [t["label"] for t in lists.triggers(item, rows.get(code)) if t["met"]]
        out.setdefault(name, []).append({"code": code, "note": item.note, "triggers_met": met,
                                         "price": (rows.get(code) or {}).get("current_price")})
    return {"watchlists": [{"name": k, "entries": v} for k, v in out.items()]}


def who_holds(session, code: str) -> dict:
    """The fund managers and funds that hold a company, and the ETFs and LICs in Sift that hold it."""
    code = _code(code)
    holders = [dict(r) for r in session.execute(text("""
        SELECT h.name AS holder, h.holder_kind AS kind, m.name AS manager, h.index_fund, t.shares, t.percent_held,
               t.percent_change, t.date_reported AS reported
        FROM top_holders t JOIN companies c USING (company_id)
        JOIN holders h ON h.holder_id = t.holder_id LEFT JOIN managers m ON m.manager_id = h.manager_id
        WHERE c.asx_code = :c ORDER BY t.percent_held DESC NULLS LAST"""), {"c": code}).mappings()]
    funds = [dict(r) for r in session.execute(text("""
        SELECT f.asx_code AS fund, f.company_name AS fund_name, f.security_type AS type, fh.weight_percent
        FROM fund_holdings fh JOIN companies f ON f.company_id = fh.company_id
        JOIN companies c ON c.company_id = fh.held_company_id
        WHERE c.asx_code = :c ORDER BY fh.weight_percent DESC NULLS LAST"""), {"c": code}).mappings()]
    return {"code": code, "holders": holders, "funds_in_sift_holding_it": funds,
            "limits": "Yahoo lists each company's top 10 holders and each fund's top holdings only."}


def manager(session, name: str) -> dict:
    """What one fund manager (Vanguard, BlackRock...) holds among Sift's companies, and what it's adding or cutting."""
    from src.coattail.views import slug
    rows = [dict(r) for r in session.execute(text("""
        SELECT c.asx_code AS code, c.company_name AS name, h.name AS through, h.index_fund, t.shares, t.percent_held,
               t.percent_change, t.date_reported AS reported
        FROM managers m JOIN holders h USING (manager_id) JOIN top_holders t ON t.holder_id = h.holder_id
        JOIN companies c USING (company_id)
        WHERE m.manager_id = :m OR lower(m.name) = lower(:n) ORDER BY t.percent_held DESC NULLS LAST"""),
        {"m": slug(name or ""), "n": (name or "").strip()}).mappings()]
    if not rows:
        known = [n for (n,) in session.execute(text("SELECT name FROM managers ORDER BY name"))]
        raise ToolError(f"no manager called {name!r}; known: {', '.join(known) or 'none yet'}")
    return {"manager": name, "holdings": rows,
            "adding": [r["code"] for r in rows if (r["percent_change"] or 0) > 0],
            "cutting": [r["code"] for r in rows if (r["percent_change"] or 0) < 0]}


def fund_overlap(session, codes: list[str] | None = None) -> dict:
    """How much ETFs and LICs overlap (shared holdings, by weight), and which of the
    person's own shares they also hold. With no codes, the funds the person holds."""
    from src.portfolio.holdings import position_summaries
    held = position_summaries(session, date.today())
    if not codes:
        codes = [c for c in held if _kind(session, c) in ("ETF", "LIC")]
    codes = sorted({_code(c) for c in codes})
    weights: dict[str, dict[str, float]] = {}
    for fund, company_code, w in session.execute(text("""
            SELECT f.asx_code, c.asx_code, fh.weight_percent FROM fund_holdings fh
            JOIN companies f ON f.company_id = fh.company_id JOIN companies c ON c.company_id = fh.held_company_id
            WHERE f.asx_code IN :codes""").bindparams(_expanding("codes")), {"codes": codes or [""]}):
        weights.setdefault(fund, {})[company_code] = float(w or 0)
    pairs = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            common = set(weights.get(a, {})) & set(weights.get(b, {}))
            pairs.append({"funds": [a, b], "overlap_percent": round(sum(min(weights[a][x], weights[b][x]) for x in common), 2),
                          "shared_holdings": sorted(common)})
    mine = {c for c in held if _kind(session, c) == "SHARE"}
    also = {f: sorted(set(w) & mine) for f, w in weights.items() if set(w) & mine}
    return {"funds": codes, "pairs": sorted(pairs, key=lambda p: -p["overlap_percent"]),
            "my_shares_also_inside_these_funds": also,
            "funds_without_holdings_data": [c for c in codes if c not in weights],
            "method": "Overlap = sum over shared holdings of the smaller weight; uses each fund's published top holdings only."}


def screener(session, action: str | None = None, sector: str | None = None, limit: int = 20) -> dict:
    """Shares from Sift's screener, best score first, optionally only one action (BUY...) or sector."""
    from src.screening.enriched import load_universe
    rows = load_universe(session, date.today()).rows
    if action:
        rows = [r for r in rows if (r["action"] or "").upper() == action.strip().upper()]
    if sector:
        rows = [r for r in rows if (r["sector"] or "").lower() == sector.strip().lower()]
    rows.sort(key=lambda r: (-sum((r.get("axis_scores") or {}).values()), r["asx_code"]))
    return {"count": len(rows), "shares": [{
        "code": r["asx_code"], "name": r["company_name"], "sector": r["sector"], "action": r["action"],
        "margin_of_safety_percent": r["margin_of_safety_percent"], "score_total": sum((r.get("axis_scores") or {}).values()),
        "price": r["current_price"]} for r in rows[:max(1, min(limit, 100))]], "note": NOT_ADVICE}


def track_record(session) -> dict:
    """How Sift's calls have done against the average screened share, by action and horizon."""
    from src.tracking import report
    from src.tracking.signals import tracking_status
    v = report.verdict(session, None)
    return {"status": tracking_status(session),
            "by_horizon_months": {m: [{k: a[k] for k in ("action", "signals", "beat_rate", "avg_excess", "avg_return", "confidence")}
                                      for a in v[m]["actions"]] for m in v},
            "how_to_read": "avg_excess is percentage points above (or below) the average screened share's total return over the horizon."}


def help_topic(session, term: str) -> dict:
    """Sift's own explanation of a term or screen (the Help articles)."""
    kb = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    t = (term or "").strip().lower()
    hits = [e for e in kb["entries"] if t and (t == e["id"] or t == e["title"].lower() or t in [a.lower() for a in e.get("aliases", [])])]
    hits = hits or [e for e in kb["entries"] if t and t in (e["title"] + " " + e.get("definition", "")).lower()]
    if not hits:
        raise ToolError(f"no help article about {term!r}")
    return {"articles": [{"title": e["title"], "definition": e.get("definition"), "detail": e.get("body", [])} for e in hits[:3]]}


def notices(session, code: str | None = None, kind: str | None = None, days: int = 30, mine: bool = False) -> dict:
    """ASX director trades and substantial holder notices (docs/kb/features/coattail.md)."""
    from src.coattail import notice_views
    from src.portfolio.holdings import open_parcels
    from src.watchlist.lists import watched_codes
    if kind not in (None, "directors", "substantial"):
        raise ToolError("kind is directors or substantial")
    days = max(1, min(int(days or 30), 365))
    codes = None
    if mine:
        codes = {p.asx_code for p in open_parcels(session)} | set(watched_codes(session))
    rows = notice_views.notices(session, kind, days, code=_code(code) if code else None, codes=codes, limit=200)
    return {"days": days, "notices": [{
        "code": n["asx_code"], "company": n["company_name"], "released": n["released_at"], "type": n["kind_label"],
        "what": notice_views.in_words(n), "details_read": n["read_status"] == "read", "notice": n["pdf_url"]} for n in rows],
        "about": "What directors (Appendix 3Y) and holders of 5% or more (forms 603, 604, 605) reported to ASX, read from each notice's PDF. "
                 "On-market buys with a director's own money say the most; options, share plans and dividend reinvestment say little.",
        "note": "Leads for research, not advice."}


def _expanding(name):
    from sqlalchemy import bindparam
    return bindparam(name, expanding=True)


CODE = {"type": "string", "description": "ASX code, e.g. BHP", "required": True}
TOOLS = [
    Tool("search_sift", "Search everything in Sift (shares, ETFs, LICs, fund managers, the person's lists, help) by words.", search_sift,
         {"query": {"type": "string", "description": "words to search for", "required": True},
          "limit": {"type": "integer", "description": "how many results, up to 25", "default": 10}}),
    Tool("company", "Facts and Sift's view of one share, ETF or LIC: price, estimated value, margin of safety, ratios, the four value tests, red flags, action and the person's position.", company, {"code": CODE}),
    Tool("explain_call", "Explain why Sift suggests BUY, HOLD, SELL etc. for a share: the tests and thresholds, red flags, markers, the call's history this year, and how that action has done in the track record.", explain_call, {"code": CODE}),
    Tool("my_portfolio", "The person's holdings across their portfolios: units, value, gain, today's move and Sift's call on each.", my_portfolio),
    Tool("my_watchlists", "The person's watchlists: each company or fund, its note and which triggers are met now.", my_watchlists),
    Tool("who_holds", "Which fund managers and funds hold a company, how much, and whether they're adding or cutting; plus the ETFs and LICs in Sift that hold it.", who_holds, {"code": CODE}),
    Tool("manager", "What one fund manager (for example Vanguard or BlackRock) holds among Sift's companies, and what it's adding or cutting.", manager,
         {"name": {"type": "string", "description": "manager name, e.g. Vanguard", "required": True}}),
    Tool("fund_overlap", "How much ETFs and LICs overlap by their holdings, and which of the person's own shares sit inside them. With no codes, the funds the person holds.", fund_overlap,
         {"codes": {"type": "array", "items": {"type": "string"}, "description": "ETF or LIC codes; leave out for the person's own funds"}}),
    Tool("screener", "Shares from Sift's screener, best score first, optionally filtered by suggested action (BUY, INVESTIGATE, WATCH, AVOID...) or sector.", screener,
         {"action": {"type": "string", "description": "e.g. BUY"}, "sector": {"type": "string", "description": "e.g. Financial Services"},
          "limit": {"type": "integer", "description": "up to 100", "default": 20}}),
    Tool("notices", "ASX director trades (directors buying or selling their own company's shares) and substantial holder notices (holders crossing, raising or cutting 5% or more), for one company, the person's own companies, or the whole market, over the last so many days.", notices,
         {"code": {"type": "string", "description": "ASX code, e.g. BHP; leave out for every company"},
          "kind": {"type": "string", "description": "directors or substantial; leave out for both"},
          "days": {"type": "integer", "description": "how far back, up to 365", "default": 30},
          "mine": {"type": "boolean", "description": "only companies the person holds or watches", "default": False}}),
    Tool("track_record", "How Sift's suggested actions have performed against the average screened share at 1, 3, 6 and 12 months.", track_record),
    Tool("help_topic", "Sift's own explanation of a term or screen, such as margin of safety, franking or Coattail.", help_topic,
         {"term": {"type": "string", "description": "the term, e.g. margin of safety", "required": True}}),
]
BY_NAME = {t.name: t for t in TOOLS}


def catalogue() -> list[dict]:
    """Each tool's name, description and JSON Schema for its arguments."""
    out = []
    for t in TOOLS:
        props = {k: {kk: vv for kk, vv in v.items() if kk not in ("required",)} for k, v in t.params.items()}
        out.append({"name": t.name, "description": t.description, "input_schema": {
            "type": "object", "properties": props, "required": [k for k, v in t.params.items() if v.get("required")]}})
    return out


def call(session, name: str, args: dict | None = None) -> dict:
    """Run one tool and return its JSON answer. Read-only: the caller rolls back."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"no tool called {name!r}")
    args = {k: v for k, v in (args or {}).items() if v is not None}
    unknown = set(args) - set(tool.params)
    if unknown:
        raise ToolError(f"{name} doesn't take {', '.join(sorted(unknown))}")
    missing = [k for k, v in tool.params.items() if v.get("required") and k not in args]
    if missing:
        raise ToolError(f"{name} needs {', '.join(missing)}")
    return jsonable(tool.fn(session, **args))
