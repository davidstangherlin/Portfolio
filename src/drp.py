"""Dividend reinvestment: how many shares it takes for the dividends to buy
whole new shares (docs/kb/features/drp-and-registry.md).

A dividend reinvestment plan (DRP) uses your cash dividend to buy new
shares. On today's price and the company's current dividend:

- per payment: shares needed for one dividend to buy one new share
  = price / the latest ordinary dividend per share, rounded up;
- per year: shares needed for a year's dividends to buy one new share
  = price / the ordinary dividends paid in the last 12 months, rounded up.

Franking credits don't count: they're a tax credit, not cash a DRP can
spend. One-off (abnormal) payments are left out, as everywhere in Sift.
DRP prices are often an average over a few days, sometimes at a small
discount, so these are close guides, not exact counts."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

RECENT_DAYS = 365        # the year of dividends counted
STALE_DAYS = 548         # no ordinary dividend for 18 months: the company isn't paying now


def _needed(price: Decimal, dividend: Decimal | None) -> dict | None:
    if not dividend or dividend <= 0 or not price or price <= 0:
        return None
    shares = math.ceil(price / dividend)
    return {"shares": shares, "value": (price * shares).quantize(Decimal("0.01"))}


def drp_payload(session, company_id, price, today: date, units=None) -> dict | None:
    """The DRP card's figures, or None when the company pays no ordinary
    dividend now (none in the last 18 months)."""
    rows = session.execute(text("""
        SELECT ex_date, amount FROM dividend_payments
        WHERE company_id = :c AND NOT abnormal AND amount > 0 AND ex_date >= :since AND ex_date <= :today
        ORDER BY ex_date"""), {"c": company_id, "since": today - timedelta(days=STALE_DAYS), "today": today}).all()
    if not rows or price is None:
        return None
    price = Decimal(str(price))
    last_date, last_amount = rows[-1]
    year = [a for d, a in rows if d > today - timedelta(days=RECENT_DAYS)]
    year_total = sum(year, Decimal(0)) if year else None
    out = {
        "price": price,
        "last_payment": {"ex_date": last_date, "amount": last_amount},
        "year_total": year_total, "payments_in_year": len(year),
        "per_payment": _needed(price, last_amount),
        "per_year": _needed(price, year_total),
    }
    if units:
        units = Decimal(str(units))
        out["yours"] = {"units": units,
                        "per_payment": (units * last_amount / price).quantize(Decimal("0.01")),
                        "per_year": (units * year_total / price).quantize(Decimal("0.01")) if year_total else None}
    return out
