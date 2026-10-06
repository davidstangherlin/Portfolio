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
    assert data["cgt_soon"] == [{"asx_code": "DEAR", "date": "2026-12-02", "units": 10.0, "days": 58, "security_type": "SHARE"}]


def test_status_api_flags_stale_data(seeded):
    from datetime import datetime

    fresh = gui.status_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9, 0))  # Monday: Friday's data is current
    stale = gui.status_payload(seeded, date(2026, 10, 7), datetime(2026, 10, 7, 9, 0))  # Wednesday: Tuesday's is missing
    assert fresh["stale"] is False and stale["stale"] is True
    assert TestClient(gui.create_app()).get("/api/status").status_code == 200


def test_companies_api_feeds_the_search_box(seeded):
    assert TestClient(gui.create_app()).get("/api/companies").json() == [
        {"code": "DEAR", "name": "DEAR Ltd", "type": "SHARE"}, {"code": "GOOD", "name": "GOOD Ltd", "type": "SHARE"}]


def test_dashboard_api_responds(seeded):
    data = TestClient(gui.create_app()).get("/api/dashboard").json()
    assert {"status", "attention", "portfolio", "changes", "tracking", "top"} <= set(data)


# ---------- portfolios and trades from the browser (§19.1) ----------

WRITE = {"X-Sift": "1"}


def test_changes_need_sifts_header_and_the_password(seeded):
    client = TestClient(gui.create_app(password="s3cret-pass"))
    body = {"name": "Super", "tax_type": "SMSF"}
    assert client.post("/api/portfolios", json=body, headers=WRITE).status_code == 401
    assert client.post("/api/portfolios", json=body, headers=_auth("s3cret-pass")).status_code == 403
    cross = _auth("s3cret-pass") | WRITE | {"Origin": "https://evil.example"}
    assert client.post("/api/portfolios", json=body, headers=cross).status_code == 403
    assert client.post("/api/portfolios", json=body, headers=_auth("s3cret-pass") | WRITE).status_code == 200


def test_create_buy_sell_undo_and_report(seeded):
    client = TestClient(gui.create_app())
    pf = client.post("/api/portfolios", json={"name": "Super", "tax_type": "SMSF"}, headers=WRITE).json()
    base = f"/api/portfolios/{pf['portfolio_id']}"
    assert pf["discount_rate"] == pytest.approx(1 / 3)

    bought = client.post(f"{base}/buys", headers=WRITE, json={
        "asx_code": "good", "units": "200", "price": "8.00", "date": "2024-07-01", "brokerage": "10"})
    assert bought.status_code == 200 and bought.json()["cost_base"] == 1610.0

    bad = client.post(f"{base}/sales", headers=WRITE, json={"asx_code": "GOOD", "units": "500", "price": "10", "date": "2026-07-01"})
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Only 200 units of GOOD held in Super")

    sale = client.post(f"{base}/sales", headers=WRITE, json={"asx_code": "GOOD", "units": "50", "price": "10", "date": "2026-07-01"}).json()
    assert (sale["parcels"], sale["gain"], sale["discounted_units"]) == (1, 97.5, 50.0)  # 500 - 402.50 cost base

    detail = client.get(base).json()
    assert detail["positions"][0]["units"] == 150.0 and detail["positions"][0]["action"] == "ACCUMULATE"
    assert detail["cgt"] == [{"financial_year": "2026-27", "sales": 1, "discountable_gains": 97.5, "non_discountable_gains": 0.0,
                              "capital_losses": 0.0, "net_capital_gain": 65.0, "unused_losses": 0.0}]  # two thirds taxable
    assert client.delete(f"/api/parcels/{detail['sales'][0]['holding_id']}", headers=WRITE).status_code == 400  # sold: undo instead
    assert client.post(f"/api/parcels/{detail['sales'][0]['holding_id']}/undo-sale", headers=WRITE).json()["units"] == 200.0

    overview = client.get("/api/portfolios").json()["portfolios"]
    assert [(p["name"], p["holdings"]) for p in overview] == [("My portfolio", 1), ("Super", 1)]
    menu = client.get("/api/portfolios?brief=1").json()["portfolios"]
    assert "value" not in menu[0]


def test_archive_and_delete_rules_reach_the_browser(seeded):
    client = TestClient(gui.create_app())
    pf = client.post("/api/portfolios", json={"name": "Spare"}, headers=WRITE).json()
    base = f"/api/portfolios/{pf['portfolio_id']}"
    client.post(f"{base}/buys", headers=WRITE, json={"asx_code": "DEAR", "units": "1", "price": "60", "date": "2026-01-02"})
    refused = client.patch(base, json={"archived": True}, headers=WRITE)
    assert refused.status_code == 400 and "still holds 1 open parcel" in refused.json()["detail"]
    assert client.patch(base, json={"name": "my PORTFOLIO"}, headers=WRITE).status_code == 400  # name taken
    assert client.delete(base, headers=WRITE).json() == {"deleted": "Spare", "parcels_deleted": 1}
    assert client.get(base).status_code == 404
    assert client.get("/api/portfolios/not-a-uuid").status_code == 404


def test_dashboard_lists_each_active_portfolio(seeded):
    from datetime import datetime

    client = TestClient(gui.create_app())
    client.post("/api/portfolios", json={"name": "Super", "tax_type": "SMSF"}, headers=WRITE)
    data = gui._json_ready(gui.dashboard_payload(seeded, date(2026, 10, 5), datetime(2026, 10, 5, 9, 0)))
    assert [p["name"] for p in data["portfolio"]["portfolios"]] == ["My portfolio", "Super"]
    assert data["portfolio"]["value"] == 1000.0


def test_an_unexpected_error_reads_as_a_message_not_a_bare_500(seeded, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("something odd")
    monkeypatch.setattr(gui, "dashboard_payload", broken)
    res = TestClient(gui.create_app(), raise_server_exceptions=False).get("/api/dashboard")
    assert res.status_code == 500
    assert res.json()["detail"].startswith("Server error (RuntimeError): something odd.")


def test_a_database_behind_the_code_says_how_to_fix_it():
    from sqlalchemy.exc import ProgrammingError

    class UndefinedTable(Exception):
        pass

    exc = ProgrammingError("SELECT ...", {}, UndefinedTable('relation "portfolios" does not exist'))
    assert "python -m src.apply_schema" in gui.error_message(exc)


def test_startup_brings_the_database_up_to_date(_test_database):
    assert gui.prepare_database() is None  # idempotent: safe on every start


def test_main_updates_the_database_then_serves(monkeypatch, capsys, _test_database):
    import uvicorn

    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: started.update(host=host, port=port))
    monkeypatch.delenv("GUI_PASSWORD", raising=False)
    assert gui.main(["--port", "8123"]) == 0
    assert started == {"host": "127.0.0.1", "port": 8123}
    assert "Database: up to date." in capsys.readouterr().out


def test_unarchive_through_the_browser(seeded):
    client = TestClient(gui.create_app())
    pf = client.post("/api/portfolios", json={"name": "Old"}, headers=WRITE).json()
    base = f"/api/portfolios/{pf['portfolio_id']}"
    assert client.patch(base, json={"archived": True}, headers=WRITE).json()["archived"] is True  # empty: allowed
    assert client.patch(base, json={"archived": False}, headers=WRITE).json()["archived"] is False


def test_knowledge_base_is_served_behind_the_password(seeded):
    client = TestClient(gui.create_app(password="s3cret-pass"))
    assert client.get("/static/knowledge.json").status_code == 401
    kb = client.get("/static/knowledge.json", headers=_auth("s3cret-pass")).json()
    assert {"categories", "entries"} <= set(kb)


def test_company_page_has_a_short_description_with_the_rest_on_request(seeded):
    from src.models import Company
    company = seeded.query(Company).filter_by(asx_code="GOOD").one()
    company.business_summary = "Good Ltd. mines iron ore. It sells to China. It was founded in 1901."
    seeded.commit()
    c = TestClient(gui.create_app()).get("/api/company/GOOD").json()["company"]
    assert c["business_summary_short"] == "Good Ltd. mines iron ore. It sells to China."
    assert c["business_summary"].endswith("founded in 1901.")
    company.business_summary = ""  # Yahoo has none
    seeded.commit()
    c = TestClient(gui.create_app()).get("/api/company/GOOD").json()["company"]
    assert c["business_summary"] is None and c["business_summary_short"] is None
