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


def test_company_api_states_the_model_assumptions_it_used(seeded):
    data = TestClient(gui.create_app()).get("/api/company/GOOD").json()
    assert data["model"] == {"method": "DCF", "growth_rate": 0.08, "stage1_years": 5,
                             "terminal_growth_rate": 0.025, "discount_rate": 0.09}


def test_page_is_branded_sift(seeded):
    assert "<title>Sift | ASX value screener</title>" in TestClient(gui.create_app()).get("/").text


def test_company_api_lists_the_years_dividends_for_the_price_chart(seeded):
    from src.models import Company, DividendPayment
    from sqlalchemy import select

    company = seeded.execute(select(Company).where(Company.asx_code == "GOOD")).scalar_one()
    seeded.add_all([
        DividendPayment(company_id=company.company_id, ex_date=date(2026, 3, 5), amount=Decimal("0.30"), abnormal=False),
        DividendPayment(company_id=company.company_id, ex_date=date(2024, 3, 5), amount=Decimal("0.25"), abnormal=False),
    ])
    seeded.commit()
    data = TestClient(gui.create_app()).get("/api/company/GOOD").json()
    assert data["dividends"] == [{"ex_date": "2026-03-05", "amount": 0.3, "abnormal": False}]  # last 12 months only


def test_dashboard_lists_holdings_attention_and_opportunities(seeded, tmp_path):
    from datetime import datetime

    from src.tracking.signals import record_signals

    record_signals(seeded, date(2026, 10, 2))
    seeded.commit()
    data = gui._json_ready(gui.dashboard_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9, 0), log_dir=tmp_path))

    assert data["companies"] == 2 and data["action_counts"]["ACCUMULATE"] == 1
    holding = data["portfolio"]["holdings"][0]
    assert holding["asx_code"] == "GOOD" and holding["value"] == 1000.0 and holding["action"] == "ACCUMULATE"
    assert data["portfolio"]["gain"] == 190.05  # 100 x $10 less $800 + $9.95 brokerage
    assert data["portfolio"]["day_change"] is None  # only one close stored
    assert data["attention"] == [] and data["not_screened"] == []
    assert [t["asx_code"] for t in data["top"]] == []  # GOOD is held, DEAR is not a buy
    assert data["tracking"]["signals_recorded"] == 2
    assert data["changes"]["changes"] == []
    assert data["status"]["as_of"] == "2026-10-02" and data["status"]["stale"] is False
    assert data["status"]["last_run"] is None


def test_cgt_discount_dates_within_90_days_need_attention(seeded):
    from datetime import datetime

    add_parcel(seeded, "DEAR", Decimal("10"), Decimal("50.00"), date(2025, 12, 1))
    seeded.commit()
    data = gui._json_ready(gui.dashboard_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9, 0)))
    assert data["cgt_soon"] == [{"asx_code": "DEAR", "date": "2026-12-02", "units": 10.0, "days": 58}]


def test_status_api_flags_stale_data(seeded):
    from datetime import datetime

    fresh = gui.status_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9, 0))  # Monday: Friday's data is current
    stale = gui.status_payload(seeded, date(2026, 10, 7), datetime(2026, 10, 7, 9, 0))  # Wednesday: Tuesday's is missing
    assert fresh["stale"] is False and stale["stale"] is True
    assert TestClient(gui.create_app()).get("/api/status").status_code == 200


def test_companies_api_feeds_the_search_box(seeded):
    assert TestClient(gui.create_app()).get("/api/companies").json() == [
        {"code": "DEAR", "name": "DEAR Ltd"}, {"code": "GOOD", "name": "GOOD Ltd"}]


def test_dashboard_api_responds(seeded):
    data = TestClient(gui.create_app()).get("/api/dashboard").json()
    assert {"status", "attention", "portfolio", "changes", "tracking", "top"} <= set(data)
