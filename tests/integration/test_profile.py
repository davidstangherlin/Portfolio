"""Profile, Preferences, the Users tab and impersonation (docs/AS_BUILT.md
§35): settings are checked and personal; admins manage accounts within
guardrails; an admin can act as a member, everything they do is as that
person, the admin console closes meanwhile, and every session is logged."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src import accounts, preferences

pytestmark = pytest.mark.integration

OWNER, SAM, ALEX = "owner@sift.local", "sam@example.com", "alex@example.com"


def as_(email, write=False):
    return {"X-Test-User": email} | ({"X-Sift": "1"} if write else {})


@pytest.fixture()
def client(db_session):
    accounts.owner(db_session)
    accounts.create_user(db_session, SAM, "Sam")
    db_session.commit()
    return TestClient(gui.create_app(resolve_user=gui.test_header_user))


def test_settings_are_checked_merged_and_personal(client):
    me = client.get("/api/me", headers=as_(OWNER)).json()
    assert me["settings"] == preferences.SETTINGS_DEFAULTS and me["impersonated_by"] is None
    saved = client.put("/api/me/settings", json={"theme": "dark", "compact": True}, headers=as_(OWNER, True)).json()
    assert saved["settings"]["theme"] == "dark" and saved["settings"]["compact"] is True
    client.put("/api/me/settings", json={"start_page": "screener"}, headers=as_(OWNER, True))
    s = client.get("/api/me", headers=as_(OWNER)).json()["settings"]
    assert (s["theme"], s["compact"], s["start_page"]) == ("dark", True, "screener")  # merged, not replaced
    assert client.get("/api/me", headers=as_(SAM)).json()["settings"]["theme"] == "system"  # Sam's are his own

    for bad, message in (({"theme": "pink"}, "theme must be system, light, dark"), ({"compact": "yes"}, "compact must be true or false"),
                         ({"rows_shown": "100"}, "rows_shown must be 50, 100, 250"), ({"colour": 1}, "Unknown setting: colour")):
        r = client.put("/api/me/settings", json=bad, headers=as_(OWNER, True))
        assert r.status_code == 400 and r.json()["detail"].startswith(message[0].upper() + message[1:])
    reset = client.delete("/api/me/settings", headers=as_(OWNER, True)).json()["settings"]
    assert reset == preferences.SETTINGS_DEFAULTS


def test_profile_name(client):
    r = client.patch("/api/me", json={"display_name": "  David   S "}, headers=as_(OWNER, True))
    assert r.status_code == 200 and r.json()["display_name"] == "David S"
    assert client.patch("/api/me", json={"display_name": " "}, headers=as_(OWNER, True)).status_code == 400


def test_the_users_tab_keeps_at_least_one_admin(client, db_session):
    assert client.get("/api/admin/users", headers=as_(SAM)).status_code == 403
    made = client.post("/api/admin/users", json={"email": "Alex@Example.com", "display_name": "Alex"}, headers=as_(OWNER, True))
    assert made.status_code == 200 and (made.json()["email"], made.json()["role"]) == (ALEX, "member")
    assert client.post("/api/admin/users", json={"email": ALEX}, headers=as_(OWNER, True)).status_code == 400
    listed = client.get("/api/admin/users", headers=as_(OWNER)).json()
    assert {u["email"] for u in listed["users"]} == {OWNER, SAM, ALEX}

    owner_id = listed["me"]
    r = client.patch(f"/api/admin/users/{owner_id}", json={"role": "member"}, headers=as_(OWNER, True))
    assert r.status_code == 400 and "your own admin role" in r.json()["detail"]
    sam_id = next(u["user_id"] for u in listed["users"] if u["email"] == SAM)
    assert client.patch(f"/api/admin/users/{sam_id}", json={"role": "admin"}, headers=as_(OWNER, True)).json()["admin"] is True
    # With two admins, either can make the other a member, but nobody demotes or disables themselves.
    assert client.patch(f"/api/admin/users/{owner_id}", json={"role": "member"}, headers=as_(SAM, True)).status_code == 200
    r = client.patch(f"/api/admin/users/{sam_id}", json={"status": "disabled"}, headers=as_(SAM, True))
    assert r.status_code == 400  # not himself
    assert client.patch(f"/api/admin/users/{'0' * 32}", json={}, headers=as_(SAM, True)).status_code == 404


def test_impersonation_acts_as_the_member_and_is_logged(client):
    sam_id = next(u["user_id"] for u in client.get("/api/admin/users", headers=as_(OWNER)).json()["users"] if u["email"] == SAM)
    started = client.post("/api/admin/impersonate", json={"user_id": sam_id}, headers=as_(OWNER, True))
    assert started.status_code == 200 and started.json()["impersonating"]["email"] == SAM

    me = client.get("/api/me", headers=as_(OWNER)).json()
    assert me["email"] == SAM and me["impersonated_by"]["email"] == OWNER
    assert client.get("/api/status", headers=as_(OWNER)).json()["impersonating"] is True
    client.post("/api/watchlists", json={"name": "Made while impersonating"}, headers=as_(OWNER, True))
    assert [w["name"] for w in client.get("/api/watchlists", headers=as_(SAM)).json()["watchlists"]] == ["Made while impersonating"]
    assert client.get("/api/admin/users", headers=as_(OWNER)).status_code == 403  # the console is closed meanwhile

    assert client.delete("/api/impersonation", headers=as_(OWNER, True)).json() == {"ended": True}
    assert client.get("/api/me", headers=as_(OWNER)).json()["email"] == OWNER
    assert client.get("/api/watchlists", headers=as_(OWNER)).json()["watchlists"] == []
    [entry] = client.get("/api/admin/users", headers=as_(OWNER)).json()["log"]
    assert (entry["admin_email"], entry["target_email"], entry["ended_how"]) == (OWNER, SAM, "ended")


def test_impersonation_guardrails(client, db_session):
    users = {u["email"]: u["user_id"] for u in client.get("/api/admin/users", headers=as_(OWNER)).json()["users"]}
    owner_id, sam_id = users[OWNER], users[SAM]
    for target, why in ((owner_id, "can't impersonate yourself"), ("nope", "no such account")):
        r = client.post("/api/admin/impersonate", json={"user_id": target}, headers=as_(OWNER, True))
        assert r.status_code == 400 and why in r.json()["detail"].lower()
    assert client.post("/api/admin/impersonate", json={"user_id": owner_id}, headers=as_(SAM, True)).status_code == 403

    client.post("/api/admin/impersonate", json={"user_id": sam_id}, headers=as_(OWNER, True))
    db_session.execute(text("UPDATE users SET status = 'disabled' WHERE email = :e"), {"e": SAM})
    db_session.commit()
    assert client.get("/api/me", headers=as_(OWNER)).json()["email"] == OWNER  # a disabled account ends it
    db_session.execute(text("UPDATE users SET status = 'active' WHERE email = :e"), {"e": SAM})
    db_session.commit()

    client.post("/api/admin/impersonate", json={"user_id": sam_id}, headers=as_(OWNER, True))
    db_session.execute(text("UPDATE impersonations SET started_at = started_at - interval '9 hours' WHERE ended_at IS NULL"))
    db_session.commit()
    assert client.get("/api/me", headers=as_(OWNER)).json()["email"] == OWNER  # and it runs out after 8 hours
    hows = [e["ended_how"] for e in client.get("/api/admin/users", headers=as_(OWNER)).json()["log"]]
    assert sorted(hows) == ["expired", "unavailable"]  # the test moved one start back in time
