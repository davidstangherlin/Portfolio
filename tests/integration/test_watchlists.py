"""Watchlists against a real PostgreSQL instance and through the web API:
names, entries, the company rule, cascades, and where watchlists show up
(screener, company page, dashboard)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import gui
from src.models import Watchlist, WatchlistItem
from src.watchlist import lists
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

WRITE = {"X-Sift": "1"}


@pytest.fixture()
def seeded(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    db_session.commit()
    return db_session


def test_names_are_unique_and_entries_update_in_place(seeded):
    w = lists.create_watchlist(seeded, " Dividend  ideas ")
    assert w.name == "Dividend ideas"
    with pytest.raises(lists.WatchlistError, match="already a watchlist"):
        lists.create_watchlist(seeded, "dividend IDEAS")
    lists.save_entry(seeded, w, "good", lists.entry_fields({"note": "first"}))
    lists.save_entry(seeded, w, "GOOD", lists.entry_fields({"note": "second", "price_below": "9"}))
    [(item, code, name)] = lists.entries(seeded)
    assert (code, item.note, item.price_below, name) == ("GOOD", "second", Decimal("9"), "Dividend ideas")


def test_only_valued_companies_can_be_watched(seeded):
    w = lists.create_watchlist(seeded, "Ideas")
    with pytest.raises(lists.WatchlistError, match="isn't a company Sift values or an ETF it follows"):
        lists.save_entry(seeded, w, "NOPE", lists.entry_fields({}))


def test_deleting_a_list_takes_its_entries_only(seeded):
    a, b = lists.create_watchlist(seeded, "A"), lists.create_watchlist(seeded, "B")
    for w in (a, b):
        lists.save_entry(seeded, w, "GOOD", lists.entry_fields({}))
    assert lists.delete_watchlist(seeded, a) == 1
    seeded.commit()
    assert lists.watched_codes(seeded) == {"GOOD": ["B"]}
    assert seeded.query(Watchlist).count() == 1 and seeded.query(WatchlistItem).count() == 1


def test_browser_flow_and_where_watchlists_show(seeded):
    client = TestClient(gui.create_app())
    assert client.post("/api/watchlists", json={"name": "Ideas"}).status_code == 403  # no X-Sift header
    w = client.post("/api/watchlists", json={"name": "Ideas", "asx_code": "dear"}, headers=WRITE).json()
    base = f"/api/watchlists/{w['watchlist_id']}"
    saved = client.put(f"{base}/items/good", json={"mos_above": "20", "note": "cheap"}, headers=WRITE)
    assert saved.status_code == 200 and saved.json()["asx_code"] == "GOOD"
    bad = client.put(f"{base}/items/GOOD", json={"price_below": "0"}, headers=WRITE)
    assert bad.status_code == 400 and bad.json()["detail"] == "The price trigger must be more than zero"

    detail = client.get(base).json()
    assert [(e["asx_code"], e["triggered"]) for e in detail["items"]] == [("GOOD", True), ("DEAR", False)]  # triggered first
    assert client.get("/api/watchlists").json()["watchlists"] == [
        {"watchlist_id": w["watchlist_id"], "name": "Ideas", "companies": 2, "etfs": 0, "triggered": 1}]

    rows = {r["asx_code"]: r for r in client.get("/api/screener").json()["rows"]}
    assert rows["GOOD"]["watchlists"] == ["Ideas"]
    company = client.get("/api/company/GOOD").json()
    assert company["watchlists"][0]["member"] is True and company["watchlists"][0]["note"] == "cheap"

    data = gui._json_ready(gui.dashboard_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9)))
    assert [(t["asx_code"], t["watchlist"]) for t in data["triggered"]] == [("GOOD", "Ideas")]

    assert client.delete(f"{base}/items/DEAR", headers=WRITE).json() == {"removed": True}
    assert client.patch(base, json={"name": "Renamed"}, headers=WRITE).json()["name"] == "Renamed"
    assert client.delete(base, headers=WRITE).json() == {"deleted": "Renamed", "companies": 1}
    assert client.get(base).status_code == 404


def test_watched_changes_come_first(seeded, monkeypatch):
    lists.save_entry(seeded, lists.create_watchlist(seeded, "Ideas"), "DEAR", lists.entry_fields({}))
    seeded.commit()
    fake = {"from_date": date(2026, 10, 2), "to_date": date(2026, 10, 5), "changes": [
        {"asx_code": "GOOD", "direction": "up"}, {"asx_code": "DEAR", "direction": "down"}]}
    monkeypatch.setattr(gui, "signal_changes", lambda session: fake)
    data = gui.dashboard_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9))
    assert [(c["asx_code"], c["watchlists"]) for c in data["changes"]["changes"]] == [("DEAR", ["Ideas"]), ("GOOD", [])]
