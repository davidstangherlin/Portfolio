"""Importing a broker's export into a portfolio (docs/kb/features/broker-import.md):
trade histories and holdings from several brokers' layouts, other markets
skipped, unknown codes left to check, nothing added twice, each person's
own portfolios only."""

import base64
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import gui
from src import accounts
from src.portfolio import holdings, importer
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

D = Decimal
TODAY = date(2026, 10, 10)
COMMSEC = """Date,Reference,Details,Debit($),Credit($),Balance($)
02/03/2026,C123,B 100 GOOD @ 10.000000,1019.95,,5000.00
15/04/2026,C124,S 40 GOOD @ 12.500000,,480.05,5480.05
20/04/2026,D125,Dividend GOOD,,30.00,5510.05
"""
SHARESIES = """Order ID,Trade date,Instrument code,Market code,Quantity,Price,Transaction type,Transaction fee,Currency,Amount
1,2026-05-01,DEAR,ASX,10,60,BUY,5,AUD,605
2,2026-05-02,AIR,NZX,50,1.2,BUY,1,NZD,61
3,2026-05-03,AAPL,NASDAQ,2,170,BUY,1,USD,341
4,2026-05-04,ZZZX,ASX,5,2,BUY,1,AUD,11
"""
HOLDINGS = """Code,Avail Units,Purchase $,Last $,Mkt Value $
GOOD,200,9.50,10.00,2000.00
DEAR,5,55.00,60.00,300.00
"""


def payload(text_or_bytes, filename="export.csv", **extra):
    raw = text_or_bytes.encode() if isinstance(text_or_bytes, str) else text_or_bytes
    return {"filename": filename, "content": base64.b64encode(raw).decode()} | extra


@pytest.fixture()
def market(db_session):
    for code, price in (("GOOD", "10.00"), ("DEAR", "60.00")):
        _seed_and_value(db_session, code, "Basic Materials", D("110000000"), D("0.60"), D(price))
    db_session.commit()
    return db_session


def test_commsec_trade_history(market):
    d = importer.preview(market, payload(COMMSEC), TODAY)
    assert (d["broker"], d["kind"]) == ("commsec", "trades")
    lines = {l["row"]: l for l in d["lines"]}
    assert (lines[2]["side"], lines[2]["units"], lines[2]["price"], lines[2]["brokerage"]) == ("BUY", D(100), D("10.000000"), D("19.95"))
    assert (lines[3]["side"], lines[3]["brokerage"]) == ("SELL", D("19.95"))
    assert lines[4]["status"] == "skip"  # the dividend
    out = importer.apply(market, payload(COMMSEC, new_portfolio="CommSec"), TODAY)
    assert (out["bought"], out["sold"], out["problems"]) == (1, 1, [])
    pf = holdings.find_portfolio(market, "CommSec")
    left = holdings.open_parcels(market, "GOOD", pf.portfolio_id)
    assert [(p.units, p.buy_date) for p in left] == [(D(60), date(2026, 3, 2))]
    again = importer.preview(market, payload(COMMSEC, portfolio_id=str(pf.portfolio_id)), TODAY)
    assert [l["status"] for l in again["lines"][:2]] == ["duplicate", "duplicate"]  # importing twice adds nothing


def test_sharesies_other_markets_and_unknown_codes(market):
    d = importer.preview(market, payload(SHARESIES), TODAY)
    status = {l["code"]: (l["status"], l["include"]) for l in d["lines"]}
    assert status["DEAR"] == ("new", True) and status["AIR"][0] == "skip" and status["AAPL"][0] == "skip"
    assert status["ZZZX"] == ("check", False)  # not a code Sift knows: unticked
    out = importer.apply(market, payload(SHARESIES, new_portfolio="Sharesies"), TODAY)
    assert out["bought"] == 1
    rows = [l["row"] for l in d["lines"] if l["code"] in ("DEAR", "ZZZX")]
    pf = holdings.find_portfolio(market, "Sharesies")
    out = importer.apply(market, payload(SHARESIES, portfolio_id=str(pf.portfolio_id), rows=rows), TODAY)
    assert out["bought"] == 1  # ZZZX ticked by the person; DEAR already there


def test_holdings_snapshot_from_excel(market):
    book = Workbook()
    ws = book.active
    ws.append(["My holdings"])
    for line in HOLDINGS.strip().splitlines():
        ws.append([x if i == 0 else float(x) for i, x in enumerate(line.split(","))] if not line.startswith("Code") else line.split(","))
    buf = io.BytesIO()
    book.save(buf)
    d = importer.preview(market, payload(buf.getvalue(), "holdings.xlsx", holdings_date="2025-07-01"), TODAY)
    assert d["kind"] == "holdings" and [(l["code"], l["units"], l["price"], l["date"]) for l in d["lines"]] == [
        ("GOOD", D(200), D("9.5"), date(2025, 7, 1)), ("DEAR", D(5), D(55), date(2025, 7, 1))]
    with pytest.raises(importer.HoldingsError, match="future"):
        importer.preview(market, payload(HOLDINGS, holdings_date="2027-01-01"), TODAY)


def test_the_person_can_correct_a_column(market):
    oddly_named = "When,Stock,How many,Paid each,Way\n2026-05-01,GOOD,10,9,Buy\n"
    d = importer.preview(market, payload(oddly_named), TODAY)
    assert "code" in d["missing"] or d["lines"][0]["status"] == "skip"
    fixed = importer.preview(market, payload(oddly_named, kind="trades", mapping={"date": 0, "code": 1, "units": 2, "price": 3, "side": 4}), TODAY)
    assert fixed["missing"] == [] and fixed["lines"][0]["status"] == "new"


def test_each_person_imports_into_their_own_portfolios(market):
    mine = holdings.create_portfolio(market, "Mine")
    accounts.create_user(market, "sam@example.com", "Sam")
    market.commit()
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    sam = {"X-Test-User": "sam@example.com", "X-Sift": "1"}
    refused = client.post("/api/portfolios/import", json=payload(COMMSEC, portfolio_id=str(mine.portfolio_id)), headers=sam)
    assert refused.status_code == 400 and "no such portfolio" in refused.json()["detail"].lower()
    ok = client.post("/api/portfolios/import", json=payload(COMMSEC, new_portfolio="Sam's CommSec"), headers=sam)
    assert ok.status_code == 200 and ok.json()["bought"] == 1
    preview = client.post("/api/portfolios/import/preview", json=payload("nothing,here\n1,2\n"), headers=sam)
    assert preview.status_code == 200 and {"code", "units"} <= set(preview.json()["missing"])
    blank = client.post("/api/portfolios/import/preview", json={"filename": "x.csv", "content": ""}, headers=sam)
    assert blank.status_code == 400
