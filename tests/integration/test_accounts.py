"""Multi-user Phase 1 (docs/AS_BUILT.md §33): each person sees and changes
only their own portfolios, watchlists, scenarios, layout and personal
search results; shared data stays shared; the admin console is for admins."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

import gui
from src import accounts, preferences
from src.portfolio import holdings
from src.search import indexer
from src.search.query import search
from src.watchlist import lists
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

OWNER, SAM = "owner@sift.local", "sam@example.com"


def headers(email, write=False):
    return {"X-Test-User": email} | ({"X-Sift": "1"} if write else {})


@pytest.fixture()
def two_users(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    sam = accounts.create_user(db_session, SAM, "Sam")
    db_session.commit()
    return db_session, accounts.owner(db_session), sam


def test_the_owner_is_the_default_and_exists_once(db_session):
    first = accounts.owner(db_session)
    assert (first.email, first.role, first.is_admin) == (OWNER, "admin", True)
    assert accounts.current_user_id(db_session) == first.user_id
    assert len(accounts.all_users(db_session)) == 1
    with pytest.raises(accounts.AccountError, match="already an account"):
        accounts.create_user(db_session, " OWNER@sift.local ", "Again")


def test_data_layer_scopes_to_the_current_user(two_users):
    session, owner, sam = two_users
    mine = lists.create_watchlist(session, "Ideas")
    lists.save_entry(session, mine, "GOOD", lists.entry_fields({}))
    holdings.add_parcel(session, "GOOD", Decimal("10"), Decimal("9"), date(2026, 1, 5))
    preferences.set_preference(session, "dashboard_layout", {"cards": [{"id": "movers", "hidden": True, "wide": None}]})
    with accounts.acting_as(sam.user_id):
        assert lists.list_watchlists(session) == [] and lists.watched_codes(session) == {}
        assert lists.get_watchlist(session, str(mine.watchlist_id)) is None
        assert holdings.list_portfolios(session) == [] and holdings.open_parcels(session) == []
        assert holdings.position_summaries(session, date(2026, 10, 9)) == {}
        assert preferences.get_preference(session, "dashboard_layout") is None
        with pytest.raises(holdings.HoldingsError, match="no portfolio"):
            holdings.find_portfolio(session, "My portfolio")
        theirs = lists.create_watchlist(session, "Ideas")  # the same name is fine for someone else
        assert theirs.owner_id == sam.user_id
    assert [w.name for w in lists.list_watchlists(session)] == ["Ideas"]
    assert lists.watched_codes(session) == {"GOOD": ["Ideas"]}
    assert set(holdings.position_summaries(session, date(2026, 10, 9))) == {"GOOD"}


def test_the_api_keeps_each_persons_data_apart(two_users):
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    w = client.post("/api/watchlists", json={"name": "Ideas", "asx_code": "GOOD"}, headers=headers(OWNER, True)).json()
    p = client.post("/api/portfolios", json={"name": "Super"}, headers=headers(OWNER, True)).json()
    assert client.get("/api/me", headers=headers(SAM)).json()["display_name"] == "Sam"

    assert client.get("/api/watchlists", headers=headers(SAM)).json()["watchlists"] == []
    assert client.get("/api/portfolios", headers=headers(SAM)).json()["portfolios"] == []
    for path in (f"/api/watchlists/{w['watchlist_id']}", f"/api/portfolios/{p['portfolio_id']}"):
        assert client.get(path, headers=headers(SAM)).status_code == 404
        assert client.delete(path, headers=headers(SAM, True)).status_code == 404
        assert client.get(path, headers=headers(OWNER)).status_code == 200

    rows = {r["asx_code"]: r for r in client.get("/api/screener", headers=headers(SAM)).json()["rows"]}
    assert rows["GOOD"]["watchlists"] == []  # shared screener, personal flags
    rows = {r["asx_code"]: r for r in client.get("/api/screener", headers=headers(OWNER)).json()["rows"]}
    assert rows["GOOD"]["watchlists"] == ["Ideas"]

    saved = client.post("/api/watchlists", json={"name": "Ideas"}, headers=headers(SAM, True))
    assert saved.status_code == 200 and saved.json()["name"] == "Ideas"


def test_search_shows_only_your_own_personal_results(two_users):
    session, owner, sam = two_users
    lists.create_watchlist(session, "Owner gold ideas")
    with accounts.acting_as(sam.user_id):
        lists.create_watchlist(session, "Sam gold ideas")
    indexer.reindex(session, ("personal",), "manual")
    assert [r["title"] for r in search(session, "gold ideas")["results"]] == ["Owner gold ideas"]
    with accounts.acting_as(sam.user_id):
        assert [r["title"] for r in search(session, "gold ideas")["results"]] == ["Sam gold ideas"]
        # A save rebuilds only the saver's rows: the owner's stay put.
        lists.create_watchlist(session, "Sam gold two")
        indexer.reindex(session, ("personal",), "saved", everyone=False)
        assert {r["title"] for r in search(session, "gold")["results"]} == {"Sam gold ideas", "Sam gold two"}
    assert [r["title"] for r in search(session, "gold")["results"]] == ["Owner gold ideas"]


def test_the_admin_console_is_for_admins_and_disabled_accounts_are_refused(two_users):
    session, owner, sam = two_users
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    assert client.get("/api/admin/settings", headers=headers(OWNER)).status_code == 200
    refused = client.get("/api/admin/settings", headers=headers(SAM))
    assert refused.status_code == 403 and refused.json()["detail"] == "Only an admin can do that."
    assert client.get("/api/status", headers=headers(SAM)).json()["user"]["admin"] is False
    assert client.get("/api/me", headers=headers("nobody@example.com")).status_code == 401

    session.execute(text("UPDATE users SET status = 'disabled' WHERE email = :e"), {"e": SAM})
    session.commit()
    assert client.get("/api/watchlists", headers=headers(SAM)).status_code == 403
    assert client.get("/", headers=headers(SAM)).status_code == 200  # the page itself isn't personal


def test_without_logins_everything_is_the_owners_as_before(two_users):
    client = TestClient(gui.create_app())
    client.post("/api/watchlists", json={"name": "Ideas"}, headers={"X-Sift": "1"})
    me = client.get("/api/me").json()
    assert (me["email"], me["admin"]) == (OWNER, True)
    session, owner, _ = two_users
    assert [w.name for w in lists.list_watchlists(session)] == ["Ideas"]


def _age(session, email, minutes):
    """Move someone's last request (and their latest session's) back in time."""
    session.execute(text("""
        UPDATE users SET last_seen_at = last_seen_at - make_interval(mins => :m) WHERE email = :e;
        UPDATE user_sessions s SET started_at = s.started_at - make_interval(mins => :m),
                                   last_seen_at = s.last_seen_at - make_interval(mins => :m)
        FROM users u WHERE u.user_id = s.user_id AND u.email = :e"""), {"m": minutes, "e": email})
    session.commit()


def test_sessions_start_after_an_idle_gap_and_are_kept_per_person(two_users):
    session, owner, sam = two_users
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    phone = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"}
    client.get("/api/me", headers=headers(SAM) | phone)
    client.get("/api/me", headers=headers(SAM) | phone)  # the same minute: nothing more to note
    _age(session, SAM, 20)
    client.get("/api/me", headers=headers(SAM))  # 20 minutes later: the same session, now 20 minutes long
    _age(session, SAM, 45)
    me = client.get("/api/me", headers=headers(SAM)).json()  # 45 minutes idle: a new session
    assert me["previous_session"]["client"] == "Safari on iPhone"

    users = {u["email"]: u for u in client.get("/api/admin/users", headers=headers(OWNER)).json()["users"]}
    assert users[SAM]["sessions"] == 2 and users[SAM]["last_login_at"] is not None
    assert users[OWNER]["sessions"] == 1  # the admin's own request just now
    log = client.get("/api/admin/users", headers=headers(OWNER)).json()["sessions"]
    sams = [x for x in log if x["email"] == SAM]
    assert [x["minutes"] for x in sams] == [0, 20] and [x["active"] for x in sams] == [True, False]
    assert client.get("/api/admin/users", headers=headers(SAM)).status_code == 403  # the log is for admins


def test_an_admin_impersonating_is_their_own_session_and_flagged_on_searches(two_users):
    session, owner, sam = two_users
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    client.get("/api/search?q=gold&log=1", headers=headers(SAM))
    assert client.post("/api/admin/impersonate", json={"user_id": str(sam.user_id)}, headers=headers(OWNER, True)).status_code == 200
    me = client.get("/api/me", headers=headers(OWNER)).json()
    assert me["impersonated_by"]["email"] == OWNER and me["previous_session"] is None
    client.get("/api/search?q=gold&log=1", headers=headers(OWNER))
    rows = session.execute(text("""
        SELECT u.email, q.impersonated_by, q.scope FROM search_queries q JOIN users u ON u.user_id = q.owner_id
        ORDER BY q.query_id""")).all()
    assert [(r.email, r.impersonated_by, r.scope) for r in rows] == [(SAM, None, "all"), (SAM, owner.user_id, "all")]
    started = session.execute(text("SELECT u.email FROM user_sessions s JOIN users u USING (user_id) ORDER BY u.email")).scalars().all()
    assert started == [OWNER, SAM]  # the admin's session is the admin's, not Sam's

    client.delete("/api/impersonation", headers=headers(OWNER, True))
    insights = client.get("/api/admin/search/insights", headers=headers(OWNER)).json()
    assert insights["totals"]["searches"] == 2 and insights["totals"]["impersonated"] == 1
    assert [(p["person"], p["searches"]) for p in insights["people"]] == [("Sam", 1)]


def test_client_label_is_a_few_words_never_the_raw_agent():
    label = accounts.client_label
    assert label("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Edg/128.0") == "Edge on Windows"
    assert label("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36") == "Chrome on Windows"
    assert label("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36") == "Chrome on Android"
    assert label("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15") == "Safari on Mac"
    assert label("testclient") == "Other" and label(None) is None
