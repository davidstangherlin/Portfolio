"""Dividend reinvestment and share registries on the company page
(docs/kb/features/drp-and-registry.md)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src import accounts, registries
from src.drp import drp_payload
from src.models import DividendPayment
from src.portfolio.holdings import add_parcel
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

D = Decimal


@pytest.fixture()
def payer(db_session):
    good = _seed_and_value(db_session, "GOOD", "Basic Materials", D("110000000"), D("0.60"), D("10.00"))
    today = date.today()
    for days, amount, abnormal in ((500, "0.40", False), (300, "0.45", False), (120, "0.50", False), (60, "2.00", True)):
        db_session.add(DividendPayment(company_id=good.company_id, ex_date=today - timedelta(days=days), amount=D(amount), abnormal=abnormal))
    db_session.commit()
    return db_session, good, today


def test_shares_needed_for_the_dividends_to_buy_a_share(payer):
    session, good, today = payer
    x = drp_payload(session, good.company_id, D("10.00"), today)
    assert x["last_payment"]["amount"] == D("0.50")  # the one-off 2.00 is left out
    assert (x["year_total"], x["payments_in_year"]) == (D("0.95"), 2)
    assert x["per_payment"] == {"shares": 20, "value": D("200.00")}   # 10.00 / 0.50
    assert x["per_year"] == {"shares": 11, "value": D("110.00")}      # 10.00 / 0.95, rounded up
    mine = drp_payload(session, good.company_id, D("10.00"), today, units=D("100"))["yours"]
    assert (mine["per_payment"], mine["per_year"]) == (D("5.00"), D("9.50"))
    assert drp_payload(session, good.company_id, D("10.00"), today + timedelta(days=600)) is None  # stopped paying


def test_company_page_carries_drp_and_registry(payer):
    session, good, _ = payer
    add_parcel(session, "GOOD", D("40"), D("9"), date(2026, 1, 5))
    session.commit()
    d = TestClient(gui.create_app()).get("/api/company/GOOD").json()
    assert d["drp"]["per_payment"]["shares"] >= 1 and d["drp"]["yours"]["units"] == 40
    assert d["registry"]["registry"] is None and len(d["registry"]["choices"]) == len(registries.REGISTRIES)


def test_registry_from_asx_and_an_admins_correction(payer):
    session, good, _ = payer
    fake = lambda url: (200, b'{"data": {"shareRegistry": {"name": "Link Market Services Limited"}}}')  # noqa: E731
    assert registries.refresh(session, fetch=fake) == {"found": 1, "not_found": 0}
    row = session.execute(text("SELECT registry_id, registry_source FROM companies WHERE asx_code = 'GOOD'")).one()
    assert tuple(row) == ("mufg", "asx")
    assert registries.due(session) == []  # checked: not again for a month

    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    admin = {"X-Test-User": "owner@sift.local", "X-Sift": "1"}
    set_ = client.put("/api/admin/company/GOOD/registry", json={"registry_id": "computershare"}, headers=admin).json()
    assert set_["registry"]["name"] == "Computershare" and set_["source"] == "admin"
    session.execute(text("UPDATE companies SET registry_checked_at = NULL"))
    session.commit()
    registries.refresh(session, codes=["GOOD"], fetch=fake)
    assert session.execute(text("SELECT registry_id FROM companies WHERE asx_code = 'GOOD'")).scalar() == "computershare"  # the admin's stays

    other = client.put("/api/admin/company/GOOD/registry", json={"name": "Smith Registry Services"}, headers=admin).json()
    assert other["registry"] == {"registry_id": None, "name": "Smith Registry Services", "portal": None, "website": None}
    assert client.put("/api/admin/company/GOOD/registry", json={"registry_id": "nope"}, headers=admin).status_code == 400
    assert client.put("/api/admin/company/NOPE/registry", json={"registry_id": "automic"}, headers=admin).status_code == 404
    back = client.put("/api/admin/company/GOOD/registry", json={}, headers=admin).json()
    assert back["source"] is None and registries.due(session) == ["GOOD"]  # back to ASX's on the next run

    accounts.create_user(session, "sam@example.com", "Sam")
    session.commit()
    refused = client.put("/api/admin/company/GOOD/registry", json={"registry_id": "automic"},
                         headers={"X-Test-User": "sam@example.com", "X-Sift": "1"})
    assert refused.status_code == 403  # members can't change it
