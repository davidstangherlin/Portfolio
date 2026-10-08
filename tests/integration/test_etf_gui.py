"""ETFs in Sift (docs/AS_BUILT.md §26): the ETF screener and page, and
ETFs kept under their own heading in search, the dashboard, portfolios
and watchlists, with the yield trigger and the share/ETF trigger rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import gui
from src.etf import asx_report, performance
from src.etf.prices import upsert_distributions
from src.ingestion.dividend_history import Payment
from src.ingestion.price_ingestion import upsert_daily_prices
from src.ingestion.yahoo_client import PriceBar
from src.models import Company
from src.portfolio.holdings import add_parcel
from tests.integration.test_screener import _seed_and_value
from tests.unit._etf_report import build_report

pytestmark = pytest.mark.integration
H = {"X-Sift": "1"}
END = date.today() - timedelta(days=1)


def _prices(session, code, start, daily_growth, payout=None):
    company = session.query(Company).filter_by(asx_code=code).one()
    bars, dists, price, d = [], [], 10.0, start
    while d <= END:
        if d.weekday() < 5:
            price *= 1 + daily_growth
            bars.append(PriceBar(d, Decimal(str(round(price, 4))), 1000, None))
            if payout and d.day <= 7 and d.month % 3 == 1 and d.weekday() == 0:
                dists.append(Payment(d, Decimal(str(payout))))
        d += timedelta(days=1)
    upsert_daily_prices(session, company.company_id, bars)
    upsert_distributions(session, company.company_id, dists)


@pytest.fixture()
def etfs(db_session, tmp_path):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    asx_report.load_report(db_session, build_report(tmp_path))
    db_session.commit()
    _prices(db_session, "VAS", date(2014, 1, 6), 0.0003, payout=0.1)
    _prices(db_session, "IOZ", date(2016, 1, 4), 0.0002, payout=0.1)
    _prices(db_session, "NDQ", date(2019, 1, 7), 0.0006)
    db_session.commit()
    performance.update_performance(db_session)
    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15), Decimal("9.95"))
    add_parcel(db_session, "VAS", Decimal("50"), Decimal("9.00"), date(2024, 1, 15), Decimal("9.95"))
    db_session.commit()
    return db_session


def test_etf_screener_lists_every_active_etf_apart_from_shares(etfs):
    client = TestClient(gui.create_app())
    data = client.get("/api/etfs").json()
    rows = {r["asx_code"]: r for r in data["rows"]}
    assert set(rows) == {"VAS", "IOZ", "NDQ", "HACK", "GOLD"}
    assert data["categories"] == ["Australian Equities", "Commodities", "Global Equities"]
    vas = rows["VAS"]
    assert vas["held"] == 50.0 and vas["mer_percent"] == 0.07 and vas["category"] == "Australian Equities"
    assert vas["return_10y"] is not None and vas["distribution_yield_12m"] > 0
    assert rows["NDQ"]["return_10y"] is None  # younger than ten years
    assert rows["HACK"]["current_price"] is None  # no prices yet: still listed
    screener = {r["asx_code"] for r in client.get("/api/screener").json()["rows"]}
    assert screener == {"GOOD"}  # the share screener stays shares only


def test_etf_page(etfs):
    client = TestClient(gui.create_app())
    d = client.get("/api/etf/vas").json()
    assert d["etf"]["asx_code"] == "VAS"
    assert d["reference"]["asx_code"] == "IOZ"  # largest other fund in Australian Equities
    assert d["category_average"]["etfs"] == 2
    assert len(d["growth"]["etf"]) > 500 and d["growth"]["reference"]
    assert d["prices"] and d["distributions"] and d["distributions_by_year"][-1]["partial"] is True
    assert d["position"]["units"] == 50.0
    assert d["monthly"][0]["report_month"] == "2026-08-01"
    assert [o["asx_code"] for o in d["reference_options"]][:1] == ["IOZ"]  # same category first
    assert client.get("/api/etf/VAS?compare=NDQ").json()["reference"]["asx_code"] == "NDQ"
    assert client.get("/api/etf/VAS?compare=VAS").json()["reference"]["asx_code"] == "IOZ"  # not itself
    assert client.get("/api/etf/GOOD").status_code == 404  # a share
    assert client.get("/api/etf/NOPE").status_code == 404


def test_search_marks_etfs(etfs):
    index = TestClient(gui.create_app()).get("/api/companies").json()
    types = {c["code"]: c["type"] for c in index}
    assert types["GOOD"] == "SHARE" and types["VAS"] == "ETF" and types["GOLD"] == "ETF"


def test_dashboard_keeps_etfs_in_their_own_card(etfs):
    client = TestClient(gui.create_app())
    w = client.post("/api/watchlists", json={"name": "Income"}, headers=H).json()
    client.put(f"/api/watchlists/{w['watchlist_id']}/items/IOZ", json={"yield_above": "0.01"}, headers=H)
    client.put(f"/api/watchlists/{w['watchlist_id']}/items/GOOD", json={"mos_above": "1"}, headers=H)
    d = client.get("/api/dashboard").json()
    assert d["not_screened"] == []  # the held ETF isn't "held but not screened"
    assert [t["asx_code"] for t in d["triggered"]] == ["GOOD"]
    assert [t["asx_code"] for t in d["etfs"]["triggered"]] == ["IOZ"]
    assert [f["asx_code"] for f in d["etfs"]["followed"]] == ["VAS", "IOZ"]  # held first
    assert d["etfs"]["count"] == 5 and d["etfs"]["value"]["holdings"] == 1
    sections = d["portfolio"]["sections"]
    assert sections["SHARE"]["holdings"] == 1 and sections["ETF"]["holdings"] == 1
    assert d["portfolio"]["value"] == pytest.approx(sections["SHARE"]["value"] + sections["ETF"]["value"])


def test_portfolio_shows_shares_and_etfs_separately(etfs):
    client = TestClient(gui.create_app())
    pid = client.get("/api/portfolios").json()["portfolios"][0]["portfolio_id"]
    d = client.get(f"/api/portfolios/{pid}").json()
    kinds = {p["asx_code"]: p["security_type"] for p in d["positions"]}
    assert kinds == {"GOOD": "SHARE", "VAS": "ETF"}
    vas = next(p for p in d["positions"] if p["asx_code"] == "VAS")
    assert vas["return_1y"] is not None and vas["category"] == "Australian Equities" and vas["action"] is None
    assert d["sections"]["ETF"]["holdings"] == 1 and d["etf_codes"] == ["VAS"]
    summary = client.get("/api/portfolios").json()["portfolios"][0]
    assert summary["sections"]["ETF"]["holdings"] == 1 and summary["sections"]["SHARE"]["holdings"] == 1


def test_watchlist_triggers_by_type(etfs):
    client = TestClient(gui.create_app())
    w = client.post("/api/watchlists", json={"name": "Mixed"}, headers=H).json()
    url = f"/api/watchlists/{w['watchlist_id']}/items"
    bad = client.put(f"{url}/VAS", json={"mos_above": "10"}, headers=H)
    assert bad.status_code == 400 and "ETF, which has no margin of safety" in bad.json()["detail"]
    bad = client.put(f"{url}/GOOD", json={"yield_above": "4"}, headers=H)
    assert bad.status_code == 400 and "yield trigger is for ETFs" in bad.json()["detail"]
    ok = client.put(f"{url}/VAS", json={"yield_above": "0.01", "price_below": "1"}, headers=H).json()
    assert ok["yield_above"] == 0.01
    client.put(f"{url}/GOOD", json={}, headers=H)
    detail = client.get(f"/api/watchlists/{w['watchlist_id']}").json()
    assert [e["asx_code"] for e in detail["items"]] == ["GOOD"]
    [vas] = detail["etfs"]
    assert vas["security_type"] == "ETF" and vas["triggered"] is True
    assert [(t["kind"], t["met"]) for t in vas["triggers"]] == [("price_below", False), ("yield_above", True)]
    assert {k: vas[k] is not None for k in ("return_1y", "distribution_yield_12m", "price")} == \
        {"return_1y": True, "distribution_yield_12m": True, "price": True}
    summary = next(x for x in client.get("/api/watchlists").json()["watchlists"] if x["name"] == "Mixed")
    assert (summary["companies"], summary["etfs"], summary["triggered"]) == (1, 1, 1)
    # The ETF page shows which lists it's on.
    lists = client.get("/api/etf/VAS").json()["watchlists"]
    assert [(x["name"], x["member"], x["triggered"]) for x in lists] == [("Mixed", True, True)]
    # The ETF list carries each list's id, for the row star that adds to it.
    assert client.get("/api/etfs").json()["watchlists"] == [{"watchlist_id": w["watchlist_id"], "name": "Mixed"}]
