"""Watchlists: named lists of companies to follow, each entry with an
optional note and triggers (docs/AS_BUILT.md §22).

An entry is triggered while the company's margin of safety is above its
`mos_above`, or its latest price is at or below its `price_below`. Both are
judged on the same rows the screener shows (src/screening/enriched.py).
Only companies Sift values can be added: anything else has no price or
margin of safety to watch."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import Company, Watchlist, WatchlistItem

MAX_NAME = 60
MAX_NOTE = 500


class WatchlistError(ValueError):
    """A request that breaks a rule; the message is written for the user."""


# ---------- lists ----------

def list_watchlists(session: Session) -> list[Watchlist]:
    return list(session.execute(select(Watchlist).order_by(Watchlist.created_at, Watchlist.name)).scalars())


def get_watchlist(session: Session, watchlist_id: str) -> Watchlist | None:
    try:
        return session.get(Watchlist, uuid.UUID(str(watchlist_id)))
    except ValueError:
        return None


def _clean_name(session: Session, name, except_id=None) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise WatchlistError("a watchlist needs a name")
    if len(name) > MAX_NAME:
        raise WatchlistError(f"watchlist names can be at most {MAX_NAME} characters")
    clash = session.execute(select(Watchlist).where(func.lower(Watchlist.name) == name.lower())).scalar_one_or_none()
    if clash is not None and clash.watchlist_id != except_id:
        raise WatchlistError(f"there is already a watchlist called {clash.name!r}")
    return name


def create_watchlist(session: Session, name) -> Watchlist:
    watchlist = Watchlist(name=_clean_name(session, name))
    session.add(watchlist)
    session.flush()
    return watchlist


def rename_watchlist(session: Session, watchlist: Watchlist, name) -> Watchlist:
    watchlist.name = _clean_name(session, name, except_id=watchlist.watchlist_id)
    session.flush()
    return watchlist


def delete_watchlist(session: Session, watchlist: Watchlist) -> int:
    """Delete a list and its entries (nothing else refers to them). Returns
    how many entries went with it."""
    count = session.execute(
        select(func.count()).where(WatchlistItem.watchlist_id == watchlist.watchlist_id)
    ).scalar_one()
    session.delete(watchlist)
    session.flush()
    return count


# ---------- entries ----------

def _company(session: Session, asx_code) -> Company:
    code = str(asx_code or "").strip().upper()
    company = session.execute(select(Company).where(Company.asx_code == code)).scalar_one_or_none() if code else None
    if company is None:
        raise WatchlistError(f"{code or 'That'} isn't one of the companies Sift values. "
                             "Add it to the nightly ticker file (allords.txt) first.")
    return company


def _optional_number(value, label: str, places: int, limit: Decimal, positive: bool) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "").lstrip("$").rstrip("%"))
    except InvalidOperation:
        raise WatchlistError(f"{label} must be a number") from None
    if not number.is_finite():
        raise WatchlistError(f"{label} must be a number")
    if positive and number <= 0:
        raise WatchlistError(f"{label} must be more than zero")
    if abs(number) >= limit:
        raise WatchlistError(f"{label} is too large")
    if -number.as_tuple().exponent > places:
        raise WatchlistError(f"{label} can have at most {places} decimal places")
    return number


def entry_fields(body: dict) -> dict:
    """Note and triggers from a request, checked. Blank means none."""
    note = str(body.get("note") or "").strip() or None
    if note and len(note) > MAX_NOTE:
        raise WatchlistError(f"notes can be at most {MAX_NOTE} characters")
    return {
        "note": note,
        "mos_above": _optional_number(body.get("mos_above"), "the margin of safety trigger", 2, Decimal("10000"), False),
        "price_below": _optional_number(body.get("price_below"), "the price trigger", 4, Decimal("1e8"), True),
    }


def save_entry(session: Session, watchlist: Watchlist, asx_code, fields: dict) -> WatchlistItem:
    """Add a company to a list, or update its note and triggers if it's already on it."""
    company = _company(session, asx_code)
    item = session.get(WatchlistItem, (watchlist.watchlist_id, company.company_id))
    if item is None:
        item = WatchlistItem(watchlist_id=watchlist.watchlist_id, company_id=company.company_id)
        session.add(item)
    item.note, item.mos_above, item.price_below = fields["note"], fields["mos_above"], fields["price_below"]
    session.flush()
    return item


def remove_entry(session: Session, watchlist: Watchlist, asx_code) -> bool:
    company = _company(session, asx_code)
    item = session.get(WatchlistItem, (watchlist.watchlist_id, company.company_id))
    if item is None:
        return False
    session.delete(item)
    session.flush()
    return True


def entries(session: Session, watchlist_id=None) -> list[tuple[WatchlistItem, str, str]]:
    """(item, asx_code, watchlist name) for one list, or every list."""
    stmt = (select(WatchlistItem, Company.asx_code, Watchlist.name)
            .join(Company, Company.company_id == WatchlistItem.company_id)
            .join(Watchlist, Watchlist.watchlist_id == WatchlistItem.watchlist_id)
            .order_by(Watchlist.created_at, Company.asx_code))
    if watchlist_id is not None:
        stmt = stmt.where(WatchlistItem.watchlist_id == watchlist_id)
    return [tuple(r) for r in session.execute(stmt).all()]


def watched_codes(session: Session) -> dict[str, list[str]]:
    """Each watched company's code and the names of the lists it's on."""
    out: dict[str, list[str]] = {}
    for _, code, name in entries(session):
        out.setdefault(code, []).append(name)
    return out


# ---------- triggers ----------

def triggers(item: WatchlistItem, row: dict | None) -> list[dict]:
    """Each trigger set on the entry, with whether it's met now. A company
    with no current value or price can't meet a trigger."""
    out = []
    mos = row.get("margin_of_safety_percent") if row else None
    price = row.get("current_price") if row else None
    if item.mos_above is not None:
        out.append({"kind": "mos_above", "threshold": item.mos_above, "value": mos,
                    "met": mos is not None and mos > item.mos_above,
                    "label": f"Margin of safety above {item.mos_above.normalize():f}%"})
    if item.price_below is not None:
        out.append({"kind": "price_below", "threshold": item.price_below, "value": price,
                    "met": price is not None and price <= item.price_below,
                    "label": f"Price at or below ${item.price_below:,.2f}"})
    return out
