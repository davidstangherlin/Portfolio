"""LICs in Sift (docs/AS_BUILT.md §27): loaded from the ASX report's LIC
sheet, moved out of the share screener, valued against NTA, and kept under
their own heading in search, the dashboard, portfolios and watchlists."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import gui
from src.etf import asx_report, performance
from src.ingestion import run_ingestion
from src.models import Company
from src.portfolio.holdings import add_parcel
from tests.integration.test_etf_gui import _prices
from tests.integration.test_screener import _seed_and_value
from tests.unit._etf_report import build_asx_2026

pytestmark = pytest.mark.integration
H = {"X-Sift": "1"}


@pytest.fixture()
def lics(db_session, tmp_path):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "AFI", "Financial Services", Decimal("110000000"), Decimal("0.60"), Decimal("7.00"))
    db_session.commit()
    result = asx_report.load_report(db_session, build_asx_2026(tmp_path))
    db_session.commit()
    assert result.lics == 5 and "AFI" in result.reclassified
    _prices(db_session, "AFI", date(2016, 1, 4), 0.0002, payout=0.15)   # ends near $15.6 against NTA $7.93
    db_session.commit()
    performance.update_performance(db_session)
    add_parcel(db_session, "AFI", Decimal("1000"), Decimal("7.40"), date(2025, 5, 5), Decimal("9.50"))
    db_session.commit()
    return db_session


def test_an_lic_in_the_share_list_moves_to_its_own_heading(lics):
    client = TestClient(gui.create_app())
    assert {r["asx_code"] for r in client.get("/api/screener").json()["rows"]} == {"GOOD"}
    assert lics.query(Company).filter_by(asx_code="AFI").one().security_type == "LIC"
    types = {c["code"]: c["type"] for c in client.get("/api/companies").json()}
    assert types["AFI"] == "LIC" and types["VAS"] == "ETF" and types["GOOD"] == "SHARE"


def test_lic_screener_and_premium_to_nta(lics):
    d = TestClient(gui.create_app()).get("/api/lics").json()
    rows = {r["asx_code"]: r for r in d["rows"]}
    assert set(rows) == {"AFI", "ARG", "BKI", "MXT", "WAM"}
    assert d["kind"] == "LIC" and "Fixed Income - Australian Dollar" in d["categories"]
    afi = rows["AFI"]
    # With a price: the latest close against the last NTA.
    expected = round((afi["current_price"] / 7.93 - 1) * 100, 2)
    assert afi["premium_now"] == pytest.approx(expected, abs=0.01) and afi["premium_basis"] == "latest price"
    assert afi["nta_premium_percent"] == -11.1 and afi["performance_fee"] == "No"
    # Without prices yet: the ASX report's figure at the NTA date.
    assert rows["WAM"]["premium_now"] == 5.25 and rows["WAM"]["premium_basis"] == "NTA date"
    assert rows["MXT"]["product_type"] == "LIT"
    assert afi["held"] == 1000.0


def test_lic_page(lics):
    client = TestClient(gui.create_app())
    d = client.get("/api/lic/afi").json()
    assert d["kind"] == "LIC" and d["etf"]["asx_code"] == "AFI"
    assert d["reference"]["asx_code"] in {"ARG", "BKI", "WAM"}  # another LIC in Equity - Australia
    assert all(o["asx_code"] in {"ARG", "BKI", "MXT", "WAM"} for o in d["reference_options"])  # LICs only
    assert d["monthly"][0]["nta_pre_tax"] == 7.93 and d["growth"]["etf"]
    assert client.get("/api/etf/AFI").status_code == 404
    assert client.get("/api/lic/VAS").status_code == 404


def test_dashboard_portfolio_and_watchlists_keep_lics_apart(lics):
    client = TestClient(gui.create_app())
    w = client.post("/api/watchlists", json={"name": "Discounts"}, headers=H).json()
    url = f"/api/watchlists/{w['watchlist_id']}/items"
    assert client.put(f"{url}/ARG", json={"nta_discount_above": "10", "yield_above": "1"}, headers=H).status_code == 200
    bad = client.put(f"{url}/VAS", json={"nta_discount_above": "5"}, headers=H)
    assert bad.status_code == 400 and "NTA discount trigger is for LICs" in bad.json()["detail"]
    bad = client.put(f"{url}/ARG", json={"mos_above": "5"}, headers=H)
    assert bad.status_code == 400 and "ARG is an LIC, which has no margin of safety" in bad.json()["detail"]
    client.put(f"{url}/GOOD", json={}, headers=H)

    detail = client.get(f"/api/watchlists/{w['watchlist_id']}").json()
    assert [e["asx_code"] for e in detail["items"]] == ["GOOD"] and [e["asx_code"] for e in detail["lics"]] == ["ARG"]
    [arg] = detail["lics"]
    # ARG has no prices here, so its discount is the report's 14.3% at the NTA date: the 10% trigger is met.
    assert {t["kind"]: t["met"] for t in arg["triggers"]} == {"yield_above": False, "nta_discount_above": True}
    summary = next(x for x in client.get("/api/watchlists").json()["watchlists"] if x["name"] == "Discounts")
    assert (summary["companies"], summary["etfs"], summary["lics"]) == (1, 0, 1)

    dash = client.get("/api/dashboard").json()
    assert dash["not_screened"] == []
    assert [t["asx_code"] for t in dash["lics"]["triggered"]] == ["ARG"] and dash["triggered"] == []
    assert dash["lics"]["value"]["holdings"] == 1 and dash["portfolio"]["sections"]["LIC"]["holdings"] == 1

    pid = client.get("/api/portfolios").json()["portfolios"][0]["portfolio_id"]
    p = client.get(f"/api/portfolios/{pid}").json()
    assert {x["asx_code"]: x["security_type"] for x in p["positions"]} == {"AFI": "LIC"}
    assert p["lic_codes"] == ["AFI"] and p["positions"][0]["premium_now"] is not None


def test_share_ingestion_leaves_etfs_and_lics_to_the_etf_step(lics, monkeypatch):
    seen = {}
    monkeypatch.setattr(run_ingestion, "ingest_daily_prices", lambda s, codes, **k: seen.setdefault("prices", codes) and {})
    monkeypatch.setattr(run_ingestion, "ingest_fundamentals", lambda s, codes, **k: seen.setdefault("fundamentals", codes) and {})
    monkeypatch.setattr(run_ingestion, "ingest_insights", lambda s, codes, **k: seen.setdefault("insights", codes) and {})
    run_ingestion.main(["--tickers", "GOOD", "AFI", "VAS"])
    assert seen == {"prices": ["GOOD"], "fundamentals": ["GOOD"], "insights": ["GOOD"]}


def test_lics_get_prices_and_performance_from_the_etf_step(lics):
    from src.etf.prices import active_etfs
    kinds = {c.asx_code: c.security_type for c, _ in active_etfs(lics)}
    assert kinds["AFI"] == "LIC" and kinds["VAS"] == "ETF"
    afi = TestClient(gui.create_app()).get("/api/lic/AFI").json()["etf"]
    assert afi["return_5y"] is not None and afi["distribution_yield_12m"] > 0
    assert date.fromisoformat(afi["as_of_date"]) >= date.today() - timedelta(days=5)


def test_a_month_loaded_before_lics_is_loaded_again(db_session, tmp_path, caplog):
    """The user's case: July loaded by the ETF-only reader, so no LICs, and
    the nightly step never reloads a month it already has."""
    from sqlalchemy import text
    folder = tmp_path / "reports"
    folder.mkdir()
    path = build_asx_2026(folder)
    asx_report.load_report(db_session, path)
    # Make it look like the old reader did it: no LICs, no record of the reader.
    db_session.execute(text("DELETE FROM companies WHERE security_type = 'LIC'"))
    db_session.execute(text("DELETE FROM asx_report_loads"))
    db_session.commit()
    today = date(2026, 8, 20)  # July is the newest report there could be: nothing new to fetch
    assert db_session.query(Company).filter_by(security_type="LIC").count() == 0

    result = asx_report.ensure_latest(db_session, today, lambda url: None, folder)
    db_session.commit()
    assert result is not None and result.lics == 5
    assert db_session.query(Company).filter_by(security_type="LIC").count() == 5
    assert asx_report.loaded_by(db_session, date(2026, 7, 1)) == asx_report.READER_VERSION
    # Up to date now: nothing more happens.
    assert asx_report.ensure_latest(db_session, today, lambda url: None, folder) is None

    # Without the file to hand, it says what to do instead of failing.
    db_session.execute(text("UPDATE asx_report_loads SET reader_version = 1"))
    db_session.commit()
    assert asx_report.ensure_latest(db_session, today, lambda url: None, tmp_path / "empty") is None
    assert "loaded by an older version of Sift" in caplog.text


def test_an_open_page_learns_when_sift_is_updated(db_session):
    """Every response names the web files' version, so a tab left open
    reloads itself after an update instead of running the old code."""
    client = TestClient(gui.create_app())
    first = client.get("/api/companies").headers["X-Sift-Version"]
    assert first and client.get("/").headers["X-Sift-Version"] == first
    assert client.get("/api/lics").headers["Cache-Control"] == "no-store"
