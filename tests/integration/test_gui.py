"""gui.py's web API against a real PostgreSQL instance, through FastAPI's
test client (no server process, no browser). Checks the screener and
company payloads agree with the screener's own rules, and that the
password guard covers every route."""

import base64
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import gui
from src.portfolio.holdings import add_parcel
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration


def _auth(password, user="anyone"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture()
def seeded(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15), Decimal("9.95"))
    db_session.commit()
    return db_session


def test_screener_api_lists_every_company_with_scores_and_actions(seeded):
    data = TestClient(gui.create_app()).get("/api/screener").json()
    rows = {r["asx_code"]: r for r in data["rows"]}
    assert set(rows) == {"GOOD", "DEAR"}
    assert data["axes"] == ["Value", "Performance", "Health", "Dividend", "Momentum"]
    assert len(rows["GOOD"]["scores"]) == 5 and all(0 <= s <= 6 for s in rows["GOOD"]["scores"])
    assert rows["GOOD"]["held"] == 100.0
    assert rows["GOOD"]["action"] == "ACCUMULATE"  # same rules as screen_asx.py
    assert rows["DEAR"]["held"] is None
    assert sum(rows["GOOD"]["scores"]) > sum(rows["DEAR"]["scores"])  # cheaper scores higher on value


def test_company_api_returns_tests_scores_history_and_position(seeded):
    data = TestClient(gui.create_app()).get("/api/company/good").json()  # case-insensitive
    assert data["company"]["asx_code"] == "GOOD"
    assert [t["passed"] for t in data["tests"]] == [True, True, True, True]
    assert set(data["scores"]) == set(data["axes"])
    assert all(len(axis["checks"]) == 6 for axis in data["scores"].values())
    assert len(data["reports"]) == 3 and data["reports"][0]["fiscal_year"] == 2024  # oldest first, for charts
    assert data["prices"] and data["position"]["units"] == 100.0


def test_unknown_company_is_404(seeded):
    res = TestClient(gui.create_app()).get("/api/company/NOPE")
    assert res.status_code == 404
    assert "not in the screener" in res.json()["detail"]


def test_password_guards_api_page_and_static_files(seeded):
    client = TestClient(gui.create_app(password="s3cret-pass"))
    for path in ("/api/screener", "/", "/static/app.js"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_auth("wrong")).status_code == 401
        assert client.get(path, headers=_auth("s3cret-pass")).status_code == 200


def test_malformed_auth_header_is_rejected_not_an_error(seeded):
    client = TestClient(gui.create_app(password="s3cret-pass"))
    assert client.get("/", headers={"Authorization": "Basic !!!not-base64"}).status_code == 401


def test_lan_mode_refuses_to_start_without_a_password(monkeypatch, capsys):
    monkeypatch.delenv("GUI_PASSWORD", raising=False)
    assert gui.main(["--lan"]) == 1
    assert "GUI_PASSWORD" in capsys.readouterr().out
