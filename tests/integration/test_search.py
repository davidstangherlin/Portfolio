"""Sift-wide search (docs/AS_BUILT.md §32) against a real PostgreSQL: the
index built from every area, ranked matches, typo tolerance, tick-box
facets, personal data searchable the moment it's saved, and the API."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import gui
from src.portfolio.holdings import add_parcel
from src.search import indexer
from src.search.query import search
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration
WRITE = {"X-Sift": "1"}


@pytest.fixture()
def indexed(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15), Decimal("9.95"))
    counts = indexer.reindex(db_session, today=date(2026, 10, 5))
    db_session.commit()
    assert counts["market"] == 2 and counts["help"] > 50 and counts["pages"] > 20
    return db_session


def test_an_exact_code_ranks_first_and_help_and_settings_are_found(indexed):
    r = search(indexed, "good")
    assert r["results"][0]["code"] == "GOOD" and r["results"][0]["url"] == "#/company/GOOD"
    titles = [x["title"] for x in search(indexed, "discount rate")["results"]]
    assert "Discount rate" in titles[:2]  # the setting and the help article
    assert search(indexed, "franking")["results"][0]["type"] == "Help articles"


def test_word_starts_and_typos(indexed):
    assert any(x["title"] == "Margin of safety" for x in search(indexed, "marg")["results"])
    assert search(indexed, "screenr")["results"][0]["title"] == "Screener"  # near miss on a page title


def test_tick_boxes_count_and_narrow(indexed):
    r = search(indexed, "basic materials")
    types = {f["group"]: f for f in r["facets"]}["type"]["boxes"]
    assert {"value": "Shares", "count": 2, "ticked": False} in types
    mine = {f["group"]: f for f in r["facets"]}["mine"]["boxes"]
    assert {"value": "Held", "count": 1, "ticked": False} in mine
    held = search(indexed, "basic materials", {"mine": ["Held"]})
    assert [x["code"] for x in held["results"]] == ["GOOD"]
    # The ticked group still shows its other boxes' counts.
    assert {b["value"] for b in {f["group"]: f for f in held["facets"]}["type"]["boxes"]} >= {"Shares"}


def test_a_saved_watchlist_is_searchable_at_once_and_the_api_answers(indexed):
    client = TestClient(gui.create_app())
    client.post("/api/watchlists", json={"name": "Lithium hopefuls", "asx_code": "DEAR"}, headers=WRITE)
    data = client.get("/api/search", params={"q": "lithium"}).json()
    assert [(x["type"], x["title"]) for x in data["results"]] == [("Watchlists", "Lithium hopefuls")]
    data = client.get("/api/search", params=[("q", "materials"), ("type", "Shares"), ("mine", "On a watchlist")]).json()
    assert [x["code"] for x in data["results"]] == ["DEAR"]


def test_admin_status_and_rebuild_on_demand(indexed):
    client = TestClient(gui.create_app())
    status = client.get("/api/admin/search").json()
    assert {a["area"]: a["items"] for a in status["areas"]}["market"] == 2
    rebuilt = client.post("/api/admin/search/reindex", json={"areas": ["help"]}, headers=WRITE).json()
    assert list(rebuilt["rebuilt"]) == ["help"]
    assert {a["area"]: a["last"]["trigger"] for a in rebuilt["areas"]}["help"] == "manual"
    assert client.post("/api/admin/search/reindex", json={}).status_code == 403  # Sift's own pages only


def test_startup_builds_everything_when_empty_then_only_help_and_pages(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    db_session.commit()
    assert "market 1" in gui.prepare_search()
    assert "market" not in gui.prepare_search()
