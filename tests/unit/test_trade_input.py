"""Web GUI input checks (src/portfolio/trade_input.py), the CGT discount
by tax type, and the guard that only accepts changes from Sift's own
pages (gui._same_site_write)."""

from datetime import date
from decimal import Decimal

import pytest
from starlette.requests import Request

import gui
from src.portfolio import cgt
from src.portfolio.holdings import HoldingsError
from src.portfolio.trade_input import parse_buy, parse_portfolio, parse_sell

TODAY = date(2026, 10, 5)
GOOD = {"asx_code": " bhp ", "units": "1,000", "price": "$42.50", "date": "2026-10-01", "brokerage": ""}


def test_buy_is_cleaned_up():
    out = parse_buy(GOOD, TODAY)
    assert out["asx_code"] == "BHP" and out["units"] == Decimal("1000") and out["buy_price"] == Decimal("42.50")
    assert out["buy_brokerage"] == Decimal("0") and out["acquisition_method"] == "PURCHASE"
    assert out["buy_date"] == date(2026, 10, 1)


@pytest.mark.parametrize("change, message", [
    ({"asx_code": "BH-P"}, "ASX code"),
    ({"units": "0"}, "units must be more than zero"),
    ({"units": "abc"}, "units must be a number"),
    ({"units": "1.00001"}, "at most 4 decimal places"),
    ({"price": "-1"}, "can't be negative"),
    ({"price": ""}, "enter the price"),
    ({"brokerage": "9.999"}, "at most 2 decimal places"),
    ({"date": "2026-10-06"}, "can't be in the future"),
    ({"date": "next week"}, "enter the trade date"),
    ({"method": "GIFT"}, "method must be one of"),
    ({"units": "NaN"}, "units must be a number"),
])
def test_buy_mistakes_get_plain_messages(change, message):
    with pytest.raises(HoldingsError, match=message):
        parse_buy(GOOD | change, TODAY)


def test_sell_order_and_specific_parcel():
    out = parse_sell(GOOD | {"order": "MIN-TAX", "parcel_id": "abc"}, TODAY)
    assert out["order"] == "min-tax" and out["parcel_id"] == "abc" and out["sell_price"] == Decimal("42.50")
    with pytest.raises(HoldingsError, match="order must be one of"):
        parse_sell(GOOD | {"order": "lifo"}, TODAY)


def test_portfolio_fields():
    assert parse_portfolio({"name": "Super"}) == {"name": "Super", "tax_type": "INDIVIDUAL"}
    assert parse_portfolio({"archived": True}, partial=True) == {"archived": True}
    with pytest.raises(HoldingsError, match="tax type"):
        parse_portfolio({"name": "x", "tax_type": "charity"})
    with pytest.raises(HoldingsError, match="true or false"):
        parse_portfolio({"archived": "yes"}, partial=True)


def _gain(amount, eligible):
    return cgt.RealisedGain("BHP", Decimal("1"), date(2024, 1, 1), date(2026, 1, 1), Decimal("0"), Decimal(amount), eligible)


@pytest.mark.parametrize("tax_type, net", [
    ("INDIVIDUAL", Decimal("700.00")),  # 200 + 1000 x 50%
    ("TRUST", Decimal("700.00")),
    ("SMSF", Decimal("866.67")),        # 200 + 1000 x 2/3
    ("COMPANY", Decimal("1200.00")),
])
def test_cgt_discount_depends_on_the_owner(tax_type, net):
    gains = [_gain("1000", True), _gain("200", False)]
    assert cgt.summarise("2025-26", gains, cgt.DISCOUNT_RATES[tax_type]).net_capital_gain == net


def _request(headers):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/api/portfolios", "headers": raw})


@pytest.mark.parametrize("headers, allowed", [
    ({"host": "localhost:8000", "x-sift": "1"}, True),
    ({"host": "localhost:8000", "x-sift": "1", "origin": "http://localhost:8000", "sec-fetch-site": "same-origin"}, True),
    ({"host": "localhost:8000"}, False),                                                        # a plain form post
    ({"host": "localhost:8000", "x-sift": "1", "origin": "https://evil.example"}, False),
    ({"host": "localhost:8000", "x-sift": "1", "sec-fetch-site": "cross-site"}, False),
    ({"host": "192.168.1.20:8000", "x-sift": "1", "origin": "http://192.168.1.20:8000"}, True),  # phone on the LAN
])
def test_changes_only_from_sifts_own_pages(headers, allowed):
    assert gui._same_site_write(_request(headers)) is allowed
