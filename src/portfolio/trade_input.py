"""Checks on trades and portfolio changes typed into the web GUI, before
they reach src/portfolio/holdings.py. Every problem is raised as a
HoldingsError with a message written for the person at the keyboard."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from src.portfolio import cgt
from src.portfolio.holdings import ACQUISITION_METHODS, SELL_ORDERS, HoldingsError

_CODE = re.compile(r"^[A-Z0-9]{1,6}$")
MAX_TEXT = 500

# (decimal places, upper limit) matching the holdings columns' NUMERIC sizes.
_UNITS = (4, Decimal("1e10"))
_PRICE = (4, Decimal("1e8"))
_BROKERAGE = (2, Decimal("1e8"))


def _text(body: dict, key: str, limit: int = MAX_TEXT) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    value = str(value).strip()
    if len(value) > limit:
        raise HoldingsError(f"{key} can be at most {limit} characters")
    return value or None


def _number(body: dict, key: str, label: str, rules: tuple[int, Decimal], required: bool = True,
            positive: bool = False) -> Decimal:
    raw = body.get(key)
    if raw is None or str(raw).strip() == "":
        if required:
            raise HoldingsError(f"enter the {label}")
        return Decimal("0")
    try:
        value = Decimal(str(raw).strip().replace(",", "").lstrip("$"))
    except InvalidOperation:
        raise HoldingsError(f"{label} must be a number") from None
    if not value.is_finite():
        raise HoldingsError(f"{label} must be a number")
    places, limit = rules
    if value < 0 or (positive and value == 0):
        raise HoldingsError(f"{label} must be more than zero" if positive else f"{label} can't be negative")
    if value >= limit:
        raise HoldingsError(f"{label} is too large")
    if -value.as_tuple().exponent > places:
        raise HoldingsError(f"{label} can have at most {places} decimal places")
    return value


def _trade_date(body: dict, today: date) -> date:
    raw = body.get("date")
    try:
        value = date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        raise HoldingsError("enter the trade date") from None
    if value > today:
        raise HoldingsError("the trade date can't be in the future")
    return value


def _code(body: dict) -> str:
    code = str(body.get("asx_code") or "").strip().upper()
    if not _CODE.match(code):
        raise HoldingsError("enter an ASX code of up to 6 letters or digits, such as BHP")
    return code


def parse_buy(body: dict, today: date) -> dict:
    """Keyword arguments for holdings.add_parcel()."""
    method = str(body.get("method") or "PURCHASE").strip().upper()
    if method not in ACQUISITION_METHODS:
        raise HoldingsError(f"method must be one of {', '.join(ACQUISITION_METHODS)}")
    return {
        "asx_code": _code(body),
        "units": _number(body, "units", "units", _UNITS, positive=True),
        "buy_price": _number(body, "price", "price", _PRICE),
        "buy_date": _trade_date(body, today),
        "buy_brokerage": _number(body, "brokerage", "brokerage", _BROKERAGE, required=False),
        "acquisition_method": method,
        "broker": _text(body, "broker", 50),
        "notes": _text(body, "notes"),
    }


def parse_sell(body: dict, today: date) -> dict:
    """Keyword arguments for holdings.sell()."""
    order = str(body.get("order") or "fifo").strip().lower()
    if order not in SELL_ORDERS:
        raise HoldingsError(f"order must be one of {', '.join(SELL_ORDERS)}")
    return {
        "asx_code": _code(body),
        "units": _number(body, "units", "units", _UNITS, positive=True),
        "sell_price": _number(body, "price", "price", _PRICE),
        "sell_date": _trade_date(body, today),
        "sell_brokerage": _number(body, "brokerage", "brokerage", _BROKERAGE, required=False),
        "order": order,
        "parcel_id": _text(body, "parcel_id", 36),
    }


def parse_portfolio(body: dict, partial: bool = False) -> dict:
    """Name and tax type for a new portfolio, or whichever of name, tax
    type and archived are present for an update."""
    out: dict = {}
    if "name" in body or not partial:
        out["name"] = str(body.get("name") or "")
    if "tax_type" in body or not partial:
        tax_type = str(body.get("tax_type") or "INDIVIDUAL").strip().upper()
        if tax_type not in cgt.TAX_TYPES:
            raise HoldingsError(f"tax type must be one of {', '.join(cgt.TAX_TYPES)}")
        out["tax_type"] = tax_type
    if partial and "archived" in body:
        if not isinstance(body["archived"], bool):
            raise HoldingsError("archived must be true or false")
        out["archived"] = body["archived"]
    return out
