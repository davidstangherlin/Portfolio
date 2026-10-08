"""The dashboard's biggest movers: the shares, ETFs and LICs that rose and
fell most, by percentage, from the previous close to the latest one.

Only rows priced on the latest trading day in the group count, so a
suspended or delisted stock's last move, possibly weeks old, isn't shown
as today's."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import bindparam, text

from src.screening.enriched import score_list

SHARE_MOVERS = 5
FUND_MOVERS = 5
CLOSES_WINDOW_DAYS = 31  # how far back to look for the previous close (long breaks, a missed night)

_CLOSES = text("""
    SELECT company_id, price_date, close_price, n FROM (
        SELECT company_id, price_date, close_price,
               ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY price_date DESC) AS n
        FROM daily_prices WHERE company_id IN :ids AND price_date >= :since
    ) last_two WHERE n <= 2
""").bindparams(bindparam("ids", expanding=True))


def day_change(before, now) -> Decimal | None:
    """Percentage move from the previous close, to two places."""
    return ((now - before) / before * 100).quantize(Decimal("0.01")) if before and now else None


def last_two_closes(session, company_ids, today: date) -> dict:
    """{company_id: (latest date, latest close, previous close or None)}."""
    ids = [i for i in company_ids if i is not None]
    if not ids:
        return {}
    out: dict = {}
    for cid, day, close, n in session.execute(_CLOSES, {"ids": ids, "since": today - timedelta(days=CLOSES_WINDOW_DAYS)}):
        latest = out.setdefault(cid, [None, None, None])
        if n == 1:
            latest[0], latest[1] = day, close
        else:
            latest[2] = close
    return {cid: tuple(v) for cid, v in out.items()}


def top_movers(rows: list[dict], n: int) -> dict:
    """The `n` biggest rises and falls. Each row: asx_code, company_name,
    price, change_percent, price_date, held, watchlists."""
    priced = [r for r in rows if r["change_percent"] is not None and r["price_date"] is not None]
    if not priced:
        return {"as_of": None, "traded": 0, "up": [], "down": []}
    day = max(r["price_date"] for r in priced)
    current = [r for r in priced if r["price_date"] == day]
    up = sorted((r for r in current if r["change_percent"] > 0), key=lambda r: (-r["change_percent"], r["asx_code"]))
    down = sorted((r for r in current if r["change_percent"] < 0), key=lambda r: (r["change_percent"], r["asx_code"]))
    return {"as_of": day, "traded": len(current), "up": up[:n], "down": down[:n]}


def share_movers(session, rows: list[dict], watched: dict[str, list[str]], today: date, n: int = SHARE_MOVERS) -> dict:
    """Movers among the screener's companies (`rows` from load_universe), each with its score wheel."""
    closes = last_two_closes(session, [r["company_id"] for r in rows], today)
    out = []
    for r in rows:
        day, now, before = closes.get(r["company_id"], (None, None, None))
        out.append({"asx_code": r["asx_code"], "company_name": r["company_name"], "price": now, "price_date": day,
                    "change_percent": day_change(before, now), "held": r["held"] is not None,
                    "watchlists": watched.get(r["asx_code"], []), "scores": score_list(r)})
    return top_movers(out, n)


def fund_movers(funds: dict[str, dict], n: int = FUND_MOVERS) -> dict:
    """Movers among ETFs or LICs (`etf_rows` by code, which carry the day's move)."""
    return top_movers([{"asx_code": r["asx_code"], "company_name": r["company_name"], "price": r["current_price"],
                        "price_date": r["price_date"], "change_percent": r["day_change_percent"],
                        "held": r["held"] is not None, "watchlists": r["watchlists"]} for r in funds.values()], n)
