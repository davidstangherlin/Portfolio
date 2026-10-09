"""Director trades and substantial holder notices as Sift shows them
(docs/kb/features/coattail.md): Coattail's two tabs, the company page's
card and the dashboard's card for the companies you hold or watch.

The notices are shared market data; whether a company is yours (held or
on a watchlist) is the current user's (src/accounts.py), so it's added
here, per request, never stored."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import bindparam, text

from src.coattail.notice_reader import KINDS
from src.coattail.views import slug

GROUPS = {"directors": ("DIRECTOR",), "substantial": ("SUBSTANTIAL_NEW", "SUBSTANTIAL_CHANGE", "SUBSTANTIAL_CEASE")}
DAYS = (7, 30, 90, 365)
MAX_ROWS = 1000

_NOTICES = text("""
    SELECT n.notice_id, n.asx_code, n.released_at, n.headline, n.kind, n.price_sensitive, n.pdf_url, n.read_status, n.read_note,
           coalesce(c.company_name, n.entity_name) AS company_name, c.company_id IS NOT NULL AS in_sift
    FROM asx_notices n LEFT JOIN companies c ON c.company_id = n.company_id
    WHERE n.kind IN :kinds AND n.released_at >= :since AND (CAST(:code AS TEXT) IS NULL OR n.asx_code = :code)
      AND (:codes_all OR n.asx_code IN :codes)
    ORDER BY n.released_at DESC, n.notice_id DESC LIMIT :limit
""").bindparams(bindparam("kinds", expanding=True), bindparam("codes", expanding=True))


def _details(session, ids: list[str]) -> tuple[dict, dict]:
    if not ids:
        return {}, {}
    trades: dict[str, list] = {}
    for r in session.execute(text("""
        SELECT notice_id, director, interest, change_date, security_class, acquired, disposed, consideration, price,
               held_after, nature, nature_kind, direction
        FROM director_trades WHERE notice_id IN :ids ORDER BY notice_id, line_no""").bindparams(bindparam("ids", expanding=True)),
            {"ids": ids}).mappings():
        trades.setdefault(r["notice_id"], []).append({k: v for k, v in r.items() if k != "notice_id"})
    known = {m for (m,) in session.execute(text("SELECT name FROM managers"))}
    holdings = {}
    for r in session.execute(text("""
        SELECT notice_id, holder, manager, event_date, previous_pct, present_pct, votes
        FROM substantial_holdings WHERE notice_id IN :ids""").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).mappings():
        d = {k: v for k, v in r.items() if k != "notice_id"}
        d["manager_id"] = slug(r["manager"]) if r["manager"] in known else None  # a Coattail holder card to link to
        d["change_pts"] = (r["present_pct"] - r["previous_pct"]) if r["present_pct"] is not None and r["previous_pct"] is not None else None
        holdings[r["notice_id"]] = d
    return trades, holdings


def notices(session, group: str | None = None, days: int = 30, code: str | None = None, codes=None,
            today: date | None = None, limit: int = MAX_ROWS) -> list[dict]:
    """Notices newest first: one group ("directors", "substantial") or both,
    from the last `days`, for one company or a set of codes."""
    kinds = list(GROUPS[group]) if group else [k for g in GROUPS.values() for k in g]
    since = (today or date.today()) - timedelta(days=days)
    codes = list(codes) if codes is not None else None
    rows = [dict(r) for r in session.execute(_NOTICES, {
        "kinds": kinds, "since": since, "code": code, "codes_all": codes is None, "codes": codes or [""], "limit": limit}).mappings()]
    trades, holdings = _details(session, [r["notice_id"] for r in rows])
    for r in rows:
        r["kind_label"] = KINDS[r["kind"]]
        r["trades"] = trades.get(r["notice_id"], [])
        r["holding"] = holdings.get(r["notice_id"])
    return rows


def _shares(v) -> str:
    return f"{v:,.0f}"


def _pct(v) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def in_words(n: dict) -> str:
    """One notice as a sentence, for AI answers: "Jane Citizen bought 50,000
    shares for $212,500 ($4.25 each), on market"."""
    if n["kind"] == "DIRECTOR":
        parts = []
        for t in n["trades"]:
            who = t["director"] or "A director"
            if t["direction"] == "NONE":
                parts.append(f"{who} reported no shares bought or sold")
                continue
            verb = {"BUY": "bought", "SELL": "sold", "MIXED": "bought and sold"}[t["direction"]]
            units = t["disposed"] if t["direction"] == "SELL" else t["acquired"]
            line = f"{who} {verb} {_shares(units)} shares" if units is not None else f"{who} {verb} shares"
            if t["consideration"] is not None:
                line += f" for ${t['consideration']:,.0f}"
            if t["price"] is not None:
                line += f" (${t['price']:,.2f} each)"
            parts.append(f"{line}, {t['nature_kind'].replace('_', ' ').lower()}")
        return "; ".join(parts) or "a director's notice whose details couldn't be read"
    x = n["holding"] or {}
    who = x.get("holder") or "a holder"
    if n["kind"] == "SUBSTANTIAL_NEW":
        return f"{who} became a substantial holder" + (f" with {_pct(x['present_pct'])}% of votes" if x.get("present_pct") is not None else "")
    if n["kind"] == "SUBSTANTIAL_CEASE":
        return f"{who} ceased to be a substantial holder (now below 5%)"
    if x.get("previous_pct") is not None and x.get("present_pct") is not None:
        return f"{who} changed their holding from {_pct(x['previous_pct'])}% to {_pct(x['present_pct'])}% of votes"
    return f"{who} changed their substantial holding"


def _mark_mine(rows: list[dict], held: set[str], watched: dict[str, list[str]]) -> list[dict]:
    for r in rows:
        r["held"] = r["asx_code"] in held
        r["watchlists"] = watched.get(r["asx_code"], [])
    return rows


def director_summary(rows: list[dict]) -> dict:
    """Companies where directors bought or sold on market, by net dollars:
    on-market trades are the ones made with the director's own money at
    the market price, so they say the most."""
    by: dict[str, dict] = {}
    for r in rows:
        for t in r["trades"]:
            if t["nature_kind"] != "ON_MARKET" or t["consideration"] is None or t["direction"] not in ("BUY", "SELL"):
                continue
            s = by.setdefault(r["asx_code"], {"asx_code": r["asx_code"], "company_name": r["company_name"], "in_sift": r["in_sift"],
                                              "bought": 0, "sold": 0, "buyers": set(), "sellers": set()})
            if t["direction"] == "BUY":
                s["bought"] += t["consideration"]
                s["buyers"].add(t["director"])
            else:
                s["sold"] += t["consideration"]
                s["sellers"].add(t["director"])
    out = []
    for s in by.values():
        s["net"] = s["bought"] - s["sold"]
        s["buyers"], s["sellers"] = len(s["buyers"]), len(s["sellers"])
        out.append(s)
    return {"buying": sorted((s for s in out if s["net"] > 0), key=lambda s: -s["net"])[:10],
            "selling": sorted((s for s in out if s["net"] < 0), key=lambda s: s["net"])[:10]}


def substantial_summary(rows: list[dict]) -> dict:
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in GROUPS["substantial"]}
    raised = sum(1 for r in rows if r["holding"] and (r["holding"]["change_pts"] or 0) > 0)
    cut = sum(1 for r in rows if r["holding"] and (r["holding"]["change_pts"] or 0) < 0)
    return {"became": counts["SUBSTANTIAL_NEW"], "changed": counts["SUBSTANTIAL_CHANGE"], "ceased": counts["SUBSTANTIAL_CEASE"],
            "raised": raised, "cut": cut}


def status(session) -> dict:
    row = session.execute(text("""
        SELECT max(released_at) AS latest, max(fetched_at) AS fetched, count(*) AS notices,
               count(*) FILTER (WHERE read_status IN ('partial', 'unreadable', 'failed')) AS unread
        FROM asx_notices""")).mappings().first()
    return dict(row)


def tab_payload(session, group: str, days: int, held: set[str], watched: dict[str, list[str]], today: date | None = None) -> dict:
    rows = _mark_mine(notices(session, group, days, today=today), held, watched)
    summary = director_summary(rows) if group == "directors" else substantial_summary(rows)
    return {"group": group, "days": days, "rows": rows, "summary": summary, "status": status(session),
            "capped": len(rows) >= MAX_ROWS}


def company_notices(session, asx_code: str, today: date | None = None) -> list[dict]:
    """A company's notices over the last year, for its page."""
    return notices(session, None, 365, code=asx_code, today=today, limit=50)


def my_notices(session, held: set[str], watched: dict[str, list[str]], days: int = 7, today: date | None = None) -> list[dict]:
    """The last week's notices on the companies you hold or watch, for the dashboard."""
    codes = held | set(watched)
    if not codes:
        return []
    return _mark_mine(notices(session, None, days, codes=codes, today=today, limit=30), held, watched)
