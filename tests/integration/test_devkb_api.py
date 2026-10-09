"""The developer knowledge base through the API and search (docs/AS_BUILT.md
§36): admins only, articles and generated pages render, and search shows
developer articles to admins and to nobody else."""

import pytest
from fastapi.testclient import TestClient

import gui
from src import accounts, version
from src.devkb import generated
from src.search import indexer
from src.search.query import search

pytestmark = pytest.mark.integration

OWNER, SAM = "owner@sift.local", "sam@example.com"


@pytest.fixture()
def client(db_session):
    accounts.owner(db_session)
    accounts.create_user(db_session, SAM, "Sam")
    db_session.commit()
    return TestClient(gui.create_app(resolve_user=gui.test_header_user))


def as_(email):
    return {"X-Test-User": email}


def test_only_admins_reach_the_knowledge_base(client):
    for path in ("/api/admin/kb", "/api/admin/kb/search", "/api/admin/kb/register", "/api/admin/kb/ref-api"):
        assert client.get(path, headers=as_(SAM)).status_code == 403
        assert client.get(path, headers=as_(OWNER)).status_code == 200


def test_home_article_and_register(client):
    home = client.get("/api/admin/kb", headers=as_(OWNER)).json()
    assert home["version"] == version.VERSION and home["latest_release"]["release"] == version.VERSION
    ids = {a["id"] for a in home["articles"]}
    assert {"kb-guide", "search", "rb-nightly-run-failed", "adr-007-owner-scoping", "ref-data-dictionary"} <= ids
    assert home["register"]["open"] > 0 and set(home["reviews"]) == {"overdue", "due", "total", "drafts"}

    a = client.get("/api/admin/kb/search", headers=as_(OWNER)).json()
    assert a["title"] == "Search across Sift" and a["owner"] and a["review"] in ("ok", "due", "overdue")
    assert '<h2 id="purpose">Purpose</h2>' in a["html"] and any(t["id"] == "code-map" for t in a["toc"])
    assert {"id": "accounts-owners", "title": "Accounts and owners (multi-user Phase 1)"} in a["related"]
    assert any(b["id"] == "developer-kb" for b in a["backlinks"])
    assert client.get("/api/admin/kb/nope", headers=as_(OWNER)).status_code == 404

    reg = client.get("/api/admin/kb/register", headers=as_(OWNER)).json()
    assert reg["items"][0]["id"] == "IMP-001" and reg["items"][0]["article_titles"]


def test_generated_pages_describe_the_running_system(client, db_session):
    dd = client.get("/api/admin/kb/ref-data-dictionary", headers=as_(OWNER)).json()
    assert dd["generated"] and 'id="impersonations"' in dd["html"] and "per person" in dd["html"]
    api = client.get("/api/admin/kb/ref-api", headers=as_(OWNER)).json()["html"]
    assert "/api/admin/kb/{article_id}" in api and "admin, change" in api
    deps = generated.dependencies(db_session)
    assert "fastapi" in deps and "PostgreSQL" in deps


def test_developer_articles_are_searched_only_in_their_own_scope_by_admins(db_session):
    accounts.owner(db_session)
    sam = accounts.create_user(db_session, SAM, "Sam")
    indexer.reindex(db_session, ("devkb", "help"), "manual")
    db_session.commit()
    kb = lambda res: [r for r in res["results"] if r["url"].startswith("#/admin/kb")]  # noqa: E731
    assert kb(search(db_session, "impersonation runbook")) == []  # never in Everything, even for an admin
    found = kb(search(db_session, "impersonation runbook", scope="devkb"))
    assert found and found[0]["url"] == "#/admin/kb/rb-impersonation"
    assert all(r["url"].startswith("#/admin/kb") for r in search(db_session, "search", scope="devkb")["results"])
    with accounts.acting_as(sam.user_id):
        assert search(db_session, "impersonation runbook", scope="devkb")["results"] == []  # members: nothing


def test_the_search_api_takes_the_scope(client):
    r = client.get("/api/search", params={"q": "nightly run", "scope": "devkb"}, headers=as_(OWNER))
    assert r.status_code == 200
    assert client.get("/api/search", params={"q": "x", "scope": "web"}, headers=as_(OWNER)).status_code == 400
    assert client.get("/api/search", params={"q": "nightly run", "scope": "devkb"}, headers=as_(SAM)).json()["results"] == []
