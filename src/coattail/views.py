"""The Coattail page (docs/AS_BUILT.md §31): following the "smart money".

Stage 1 is the big funds and institutions holding the screener's
companies, from the holder lists Sift already collects weekly from Yahoo
Finance (`top_holders`, §29), grouped by the manager behind them: Vanguard's
index funds and Vanguard Group Inc are one Vanguard. Each holding carries
its shares, % held, and the change in shares since the holder's previous
report. ASX director trades (Appendix 3Y) and substantial holder notices
(5%+) are planned next; famous US investors' 13F filings later.

Index funds move with their index, not on a view about the company, so
each holding is marked when the holder's name says it's an index fund or
ETF, and the page can hide those."""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import bindparam, text

from src.screening.enriched import score_list

INDEX_FUND = re.compile(r"\b(index|indx|etfs?|tracker|ishares|spdr|msci|ftse|russell|s&p)\b", re.IGNORECASE)
NEW_POSITION = Decimal("1000")  # a change of 1,000% or more: a new, or nearly new, holding

# The manager behind a fund or institution's name, so a family of funds is
# one holder. First match wins; anything else is its own name, tidied.
MANAGERS = [
    ("Vanguard", r"\bvanguard\b"),
    ("BlackRock", r"\b(blackrock|ishares)\b"),
    ("Dimensional", r"\b(dfa|dimensional)\b"),
    ("Fidelity", r"\b(fidelity|fmr)\b"),
    ("State Street", r"\b(state street|spdr|ssga)\b"),
    ("Charles Schwab", r"\bschwab\b"),
    ("Geode Capital", r"\bgeode\b"),
    ("Northern Trust", r"\bnorthern trust\b"),
    ("Norges Bank", r"\bnorges\b"),
    ("Goldman Sachs", r"\bgoldman\b"),
    ("J.P. Morgan", r"\b(jpmorgan|jp morgan|j\.\s?p\.\s?morgan)\b"),
    ("Morgan Stanley", r"\bmorgan stanley\b"),
    ("UBS", r"\bubs\b"),
    ("Invesco", r"\b(invesco|powershares)\b"),
    ("Capital Group", r"\b(american funds|capital group|capital research|capital world)\b"),
    ("T. Rowe Price", r"\bt\.?\s?rowe\b"),
    ("Franklin Templeton", r"\b(franklin|templeton)\b"),
    ("VanEck", r"\bvan\s?eck\b"),
    ("Global X", r"\bglobal x\b"),
    ("Avantis", r"\bavantis\b"),
    ("Columbia Threadneedle", r"\b(columbia|threadneedle)\b"),
    ("Mercer", r"\bmercer\b"),
]
_MANAGERS = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in MANAGERS]
_SUFFIX = re.compile(r"[,\s]+(inc\.?|incorporated|pty\.?|llc|l\.?l\.?c\.?|l\.?p\.?|ltd\.?|limited|plc|corp\.?|corporation|co\.?|"
                     r"group|holdings?|& co\.?|ag|sa|n\.?a\.?)$", re.IGNORECASE)

_HOLDINGS = text("""
    SELECT company_id, holder_kind, holder, shares, percent_held, percent_change, date_reported
    FROM top_holders WHERE company_id IN :ids
""").bindparams(bindparam("ids", expanding=True))


def is_index_fund(holder: str, kind: str) -> bool:
    """A fund whose name says it tracks an index. Institutions (Vanguard
    Group, BlackRock) run both kinds, so they're never marked."""
    return kind == "FUND" and bool(INDEX_FUND.search(holder or ""))


def manager_of(holder: str) -> str:
    """The manager a holder belongs to: "Vanguard Total International Stock
    Index Fund" and "Vanguard Group Inc" are both Vanguard."""
    for name, pattern in _MANAGERS:
        if pattern.search(holder or ""):
            return name
    name = (holder or "").strip()
    while True:
        tidier = _SUFFIX.sub("", name).strip(" ,")
        if tidier == name or not tidier:
            return name
        name = tidier


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def shares_change(shares, percent_change) -> int | None:
    """Shares bought (+) or sold (-) since the previous report, from today's
    holding and its % change: before = now / (1 + change)."""
    if shares is None or percent_change is None or percent_change <= -100:
        return None
    before = Decimal(shares) / (1 + Decimal(percent_change) / 100)
    return int((Decimal(shares) - before).to_integral_value())


def holdings(session, rows: list[dict], watched: dict[str, list[str]]) -> dict:
    """Every top holder of every screener company, with its manager. `rows`
    are load_universe's; `companies` carries what the page shows for each."""
    by_id = {r["company_id"]: r for r in rows if r.get("company_id")}
    companies, out = {}, []
    if by_id:
        for m in session.execute(_HOLDINGS, {"ids": list(by_id)}).mappings():
            r = by_id[m["company_id"]]
            code = r["asx_code"]
            companies.setdefault(code, {"asx_code": code, "company_name": r["company_name"], "action": r["action"],
                                        "price": r.get("current_price"), "held": r["held"] is not None,
                                        "watchlists": watched.get(code, []), "scores": score_list(r)})
            manager = manager_of(m["holder"])
            change = m["percent_change"]
            out.append({"asx_code": code, "holder": m["holder"], "kind": m["holder_kind"], "manager": manager,
                        "manager_id": slug(manager), "index_fund": is_index_fund(m["holder"], m["holder_kind"]),
                        "shares": m["shares"], "percent_held": m["percent_held"], "percent_change": change,
                        "shares_change": shares_change(m["shares"], change),
                        "new": change is not None and change >= NEW_POSITION, "date_reported": m["date_reported"]})
    out.sort(key=lambda m: (m["manager"], m["asx_code"], m["holder"]))
    return {"as_of": max((m["date_reported"] for m in out if m["date_reported"]), default=None),
            "screened": len(rows), "companies": companies, "holdings": out}
