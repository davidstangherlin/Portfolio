"""AI and graph readiness (docs/kb/features/ai-and-graph.md): managers and
holders become records and fund holdings link to companies; the graph
export writes Neo4j-ready files; the read-only AI tools answer from Sift's
data for the current person only; the API and the MCP server offer them."""

import asyncio
import csv
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src import accounts
from src.ai import tools
from src.graph import entities, export
from src.models import Company
from src.portfolio.holdings import add_parcel
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

D = Decimal


@pytest.fixture()
def market(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", D("110000000"), D("0.60"), D("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", D("110000000"), D("0.60"), D("60.00"))
    for code in ("VAS", "IOZ"):
        db_session.add(Company(ticker=f"{code}.AX", company_name=f"{code} Index Fund", asx_code=code, security_type="ETF"))
    db_session.flush()
    ids = dict(db_session.execute(text("SELECT asx_code, company_id FROM companies")).all())
    for fund, rank, symbol, name, weight in (("VAS", 1, "GOOD.AX", "Good Ltd", 5), ("VAS", 2, "NVDA", "NVIDIA", 3),
                                            ("IOZ", 1, "GOOD.AX", "Good Ltd", 4), ("IOZ", 2, "DEAR", "Dear Ltd", 3)):
        db_session.execute(text("INSERT INTO fund_holdings (company_id, rank, symbol, name, weight_percent) VALUES (:c, :r, :s, :n, :w)"),
                           {"c": ids[fund], "r": rank, "s": symbol, "n": name, "w": weight})
    for kind, rank, holder, change in (("FUND", 1, "Vanguard Total Stock Index Fund", 2.5), ("INSTITUTION", 1, "BlackRock Inc.", -1.0)):
        db_session.execute(text("""INSERT INTO top_holders (company_id, holder_kind, rank, holder, shares, percent_held, percent_change, date_reported)
                                   VALUES (:c, :k, :r, :h, 1000000, 2.5, :ch, '2026-06-30')"""),
                           {"c": ids["GOOD"], "k": kind, "r": rank, "h": holder, "ch": change})
    db_session.commit()
    return db_session


def test_holders_and_fund_holdings_become_linked_records(market):
    done = entities.refresh(market)
    market.commit()
    assert (done.managers, done.holders, done.holdings_linked) == (2, 2, 2)
    assert (done.fund_lines_matched, done.fund_lines) == (3, 4)  # NVDA isn't a Sift company
    rows = dict(market.execute(text("SELECT name, manager_id || ':' || index_fund FROM holders")).all())
    assert rows == {"Vanguard Total Stock Index Fund": "vanguard:true", "BlackRock Inc.": "blackrock:false"}
    assert entities.refresh(market).holders == 2  # safe to re-run


def test_the_graph_export_is_ready_for_neo4j(market, tmp_path):
    add_parcel(market, "GOOD", D("100"), D("8"), date(2025, 1, 15))
    market.commit()
    manifest = export.export(market, tmp_path)
    read = lambda name: list(csv.DictReader(open(tmp_path / name, encoding="utf-8")))  # noqa: E731
    companies = {r["id"]: r for r in read("companies.csv")}
    assert companies["GOOD"]["type"] == "SHARE" and companies["GOOD"]["action"] == "BUY"  # the shared call, not the owner's held one
    assert companies["VAS"]["type"] == "ETF"
    assert {(r["fund"], r["company"]) for r in read("fund_holds.csv")} == {("VAS", "GOOD"), ("IOZ", "GOOD"), ("IOZ", "DEAR")}
    assert len(read("holds.csv")) == 2 and {r["id"] for r in read("managers.csv")} == {"vanguard", "blackrock"}
    assert [(r["company"], r["units"]) for r in read("positions.csv")] == [("GOOD", "100")]
    script = (tmp_path / "load.cypher").read_text()
    for needle in ("CREATE CONSTRAINT company_id IF NOT EXISTS", "file:///fund_holds.csv", "MERGE (a)-[r:HOLDS_POSITION]->(b)", "SET c:ETF"):
        assert needle in script
    assert manifest["counts"]["fund_holds"] == 3 and json.loads((tmp_path / "manifest.json").read_text())["personal"] is True

    shared = export.export(market, tmp_path / "shared", personal=False)
    assert not (tmp_path / "shared" / "positions.csv").exists() and "User" not in (tmp_path / "shared" / "load.cypher").read_text()
    assert "users" not in shared["counts"]


def test_tools_answer_for_the_current_person_only(market):
    entities.refresh(market)
    add_parcel(market, "GOOD", D("100"), D("8"), date(2025, 1, 15))
    sam = accounts.create_user(market, "sam@example.com", "Sam")
    market.commit()

    held = tools.call(market, "who_holds", {"code": "good.ax"})
    assert [h["manager"] for h in held["holders"]] == ["Vanguard", "BlackRock"]
    assert [f["fund"] for f in held["funds_in_sift_holding_it"]] == ["VAS", "IOZ"]
    overlap = tools.call(market, "fund_overlap", {"codes": ["VAS", "IOZ"]})
    assert overlap["pairs"][0] == {"funds": ["IOZ", "VAS"], "overlap_percent": 4.0, "shared_holdings": ["GOOD"]}
    assert overlap["my_shares_also_inside_these_funds"] == {"IOZ": ["GOOD"], "VAS": ["GOOD"]}
    assert tools.call(market, "manager", {"name": "vanguard"})["adding"] == ["GOOD"]

    from src import registries
    registries.set_by_admin(market, "GOOD", "computershare")
    facts = tools.call(market, "company", {"code": "GOOD"})
    assert facts["share_registry"]["name"] == "Computershare" and "dividend_reinvestment" in facts and "short_selling" in facts

    why = tools.call(market, "explain_call", {"code": "GOOD"})
    assert why["action"] == "ACCUMULATE" and why["held"] is True and len(why["tests"]) == 4 and "not financial advice" in why["note"]
    assert [h["asx_code"] for h in tools.call(market, "my_portfolio")["holdings"]] == ["GOOD"]
    with accounts.acting_as(sam.user_id):
        assert tools.call(market, "my_portfolio")["holdings"] == []
        assert tools.call(market, "explain_call", {"code": "GOOD"})["action"] == "BUY"  # not held by Sam
        assert tools.call(market, "fund_overlap")["funds"] == []

    for name, args, message in (("nope", {}, "no tool"), ("company", {}, "needs code"), ("company", {"code": "GOOD", "x": 1}, "doesn't take x"),
                                ("company", {"code": "ZZZ"}, "doesn't follow"), ("explain_call", {"code": "VAS"}, "doesn't make calls on funds")):
        with pytest.raises(tools.ToolError, match=message):
            tools.call(market, name, args)


def test_the_api_offers_the_tools(market):
    client = TestClient(gui.create_app())
    catalogue = client.get("/api/ai/tools").json()["tools"]
    assert {t["name"] for t in catalogue} == set(tools.BY_NAME)
    assert next(t for t in catalogue if t["name"] == "who_holds")["input_schema"]["required"] == ["code"]
    assert client.post("/api/ai/tools/screener", json={"action": "BUY"}).status_code == 403  # changes and tools come from Sift's pages
    r = client.post("/api/ai/tools/screener", json={"action": "BUY"}, headers={"X-Sift": "1"})
    assert r.status_code == 200 and [s["code"] for s in r.json()["shares"]] == ["GOOD"]
    assert client.post("/api/ai/tools/nope", json={}, headers={"X-Sift": "1"}).status_code == 404
    assert client.post("/api/ai/tools/company", json={}, headers={"X-Sift": "1"}).status_code == 400


def test_the_mcp_server_offers_every_tool_read_only(market):
    pytest.importorskip("mcp")
    from src.ai.mcp_server import build_server, resolve_user

    server = build_server(resolve_user(None).user_id)

    async def run():
        listed = await server.list_tools()
        result = await server.call_tool("screener", {"action": "BUY"})
        return listed, result
    listed, result = asyncio.run(run())
    assert {t.name for t in listed} == set(tools.BY_NAME)
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in listed)
    assert next(t for t in listed if t.name == "company").input_schema["required"] == ["code"]
    assert not result.is_error and '"GOOD"' in result.content[0].text
