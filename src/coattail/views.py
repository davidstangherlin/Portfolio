"""The Coattail page (docs/AS_BUILT.md §31): following the "smart money".

Stage 1 is big funds and institutions adding to, or cutting, their
holdings in the screener's companies, from the holder lists Sift already
collects weekly from Yahoo Finance (`top_holders`, §29). Each holder's
change is since its previous report. ASX director trades (Appendix 3Y) and
substantial holder notices (5%+) are planned next; famous US investors'
13F filings later.

Index funds move with their index, not on a view about the company, so
each move is marked when the holder's name says it's an index fund or ETF,
and the page hides those by default."""

from __future__ import annotations

import re

from sqlalchemy import bindparam, text

from src.screening.enriched import score_list

INDEX_FUND = re.compile(r"\b(index|indx|etfs?|tracker|ishares|spdr|msci|ftse|russell|s&p)\b", re.IGNORECASE)

_MOVES = text("""
    SELECT company_id, holder_kind, holder, shares, percent_held, percent_change, date_reported
    FROM top_holders
    WHERE company_id IN :ids AND percent_change IS NOT NULL AND percent_change <> 0
""").bindparams(bindparam("ids", expanding=True))


def is_index_fund(holder: str, kind: str) -> bool:
    """A fund whose name says it tracks an index. Institutions (Vanguard
    Group, BlackRock) run both kinds, so they're never marked."""
    return kind == "FUND" and bool(INDEX_FUND.search(holder or ""))


def holder_moves(session, rows: list[dict], watched: dict[str, list[str]]) -> dict:
    """Every reported change in a top holder's stake in a screener company,
    biggest change first. `rows` are load_universe's."""
    by_id = {r["company_id"]: r for r in rows if r.get("company_id")}
    companies, moves = {}, []
    if by_id:
        for m in session.execute(_MOVES, {"ids": list(by_id)}).mappings():
            r = by_id[m["company_id"]]
            code = r["asx_code"]
            companies.setdefault(code, {"asx_code": code, "company_name": r["company_name"], "action": r["action"],
                                        "held": r["held"] is not None, "watchlists": watched.get(code, []),
                                        "scores": score_list(r)})
            moves.append({"asx_code": code, "holder": m["holder"], "kind": m["holder_kind"],
                          "index_fund": is_index_fund(m["holder"], m["holder_kind"]),
                          "shares": m["shares"], "percent_held": m["percent_held"],
                          "percent_change": m["percent_change"], "date_reported": m["date_reported"]})
    moves.sort(key=lambda m: (-abs(m["percent_change"]), m["asx_code"], m["holder"]))
    return {"as_of": max((m["date_reported"] for m in moves if m["date_reported"]), default=None),
            "screened": len(rows), "companies": companies, "moves": moves}
