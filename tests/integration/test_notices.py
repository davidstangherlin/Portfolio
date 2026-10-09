"""ASX director trades and substantial holder notices (docs/kb/features/coattail.md):
the nightly load from ASX's lists (with ASX replaced by a fake), reading
each PDF, retrying failed downloads, and showing the notices on Coattail,
the company page, the dashboard (each person's own companies) and to AI."""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src import accounts
from src.ai import tools
from src.coattail import notices
from src.portfolio.holdings import add_parcel
from src.watchlist import lists
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "notices"
TODAY = "/asx/v2/statistics/todayAnns.do"
PDF = "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId="


def row(code, ids, headline, when="09/10/2026<br>4:12 pm"):
    return (f'<tr><td>{code}</td><td>{when}</td><td class="pricesens">&nbsp;</td><td>'
            f'<a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId={ids}">{headline} 2 pages 90KB</a></td></tr>')


PAGE = ("<table>" + row("GOOD", "100", "Change of Director's Interest Notice") + row("GOOD", "101", "Change in substantial holding from Perpetual")
        + row("ZZZ", "102", "Becoming a substantial holder") + row("GOOD", "103", "Half Year Accounts") + "</table>").encode()


class FakeAsx:
    """ASX's lists and PDFs; `down` lists PDFs that fail to download."""

    def __init__(self, down=()):
        self.down, self.calls = set(down), []

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith(TODAY):
            return 200, PAGE
        if url.endswith("prevBusDayAnns.do"):
            return 200, ("<table>" + row("DEAR", "099", "Investor Presentation", "08/10/2026<br>9:30 am") + "</table>").encode()
        ids = url.rsplit("=", 1)[-1]
        if ids in self.down:
            return 503, b""
        return 200, {"100": (FIXTURES / "3y.pdf"), "101": (FIXTURES / "604.pdf")}.get(ids, FIXTURES / "604.pdf").read_bytes()


@pytest.fixture()
def loaded(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    db_session.commit()
    asx = FakeAsx(down={"102"})
    listings, problems = notices.fetch_lists(fetch=asx)
    assert problems == [] and sorted(n.notice_id for n in listings) == ["100", "101", "102"]  # not the accounts
    assert notices.save(db_session, listings) == 3 and notices.save(db_session, listings) == 0  # once only
    db_session.commit()
    counts = notices.read_unread(db_session, fetch=asx)
    assert counts == {"read": 2, "failed": 1}
    return db_session, asx


def test_the_nightly_load_reads_each_notice(loaded):
    session, asx = loaded
    rows = {r.notice_id: r for r in session.execute(text("SELECT * FROM asx_notices"))}
    assert rows["100"].company_id is not None and rows["102"].company_id is None  # ZZZ isn't in Sift
    assert (rows["100"].entity_name, rows["100"].read_status, rows["100"].reader_version) == ("Good Mining Limited", "read", 1)
    trade = session.execute(text("SELECT * FROM director_trades WHERE notice_id = '100'")).one()
    assert (trade.director, trade.direction, trade.nature_kind, trade.acquired, trade.consideration) == (
        "Jane Citizen", "BUY", "ON_MARKET", 50000, 212500)
    holding = session.execute(text("SELECT * FROM substantial_holdings WHERE notice_id = '101'")).one()
    assert (holding.manager, holding.previous_pct, holding.present_pct) == ("Perpetual", Decimal("6.12"), Decimal("7.15"))
    assert rows["102"].read_status == "failed" and rows["102"].read_attempts == 1


def test_failed_downloads_are_retried_then_given_up(loaded):
    session, asx = loaded
    for _ in range(notices.MAX_ATTEMPTS - 1):
        assert notices.read_unread(session, fetch=asx) == {"failed": 1}
    assert notices.read_unread(session, fetch=asx) == {}  # tried on three nights: left for --reread
    asx.down.clear()
    # The fake answers with a form 604, so the "Becoming" reader can't find its date: kept, marked partial.
    assert notices.read_unread(session, fetch=asx, reread=True) == {"partial": 1}
    assert session.execute(text("SELECT read_status FROM asx_notices WHERE notice_id = '102'")).scalar() == "partial"


def test_coattail_tabs_company_page_and_ai(loaded):
    session, _ = loaded
    client = TestClient(gui.create_app())
    d = client.get("/api/coattail/notices?group=directors&days=365").json()
    assert [r["notice_id"] for r in d["rows"]] == ["100"]
    assert d["summary"]["buying"][0]["asx_code"] == "GOOD" and d["summary"]["buying"][0]["net"] == 212500
    s = client.get("/api/coattail/notices?group=substantial&days=365").json()
    assert {r["notice_id"] for r in s["rows"]} == {"101", "102"} and s["summary"]["raised"] == 1
    assert next(r for r in s["rows"] if r["notice_id"] == "102")["company_name"] is None
    assert client.get("/api/coattail/notices?group=other").status_code == 400
    assert client.get("/api/coattail/notices?days=12").status_code == 400
    company = client.get("/api/company/GOOD").json()
    assert {n["notice_id"] for n in company["company"]["notices"]} == {"100", "101"}
    answer = tools.call(session, "notices", {"code": "GOOD", "kind": "directors", "days": 365})
    assert answer["notices"][0]["what"] == "Jane Citizen bought 50,000 shares for $212,500 ($4.25 each), on market"
    with pytest.raises(tools.ToolError):
        tools.call(session, "notices", {"kind": "rumours"})


def test_the_dashboard_shows_each_person_their_own_companies(loaded):
    session, _ = loaded
    sam = accounts.create_user(session, "sam@example.com", "Sam")
    add_parcel(session, "GOOD", Decimal("10"), Decimal("9"), __import__("datetime").date(2026, 1, 5))  # the owner holds GOOD
    with accounts.acting_as(sam.user_id):
        lists.save_entry(session, lists.create_watchlist(session, "Ideas"), "DEAR", lists.entry_fields({}))
    session.commit()
    client = TestClient(gui.create_app(resolve_user=gui.test_header_user))
    mine = client.get("/api/dashboard", headers={"X-Test-User": "owner@sift.local"}).json()["notices"]
    assert {n["notice_id"] for n in mine} >= {"100", "101"} and all(n["asx_code"] == "GOOD" for n in mine)
    assert all(n["held"] for n in mine)
    assert client.get("/api/dashboard", headers={"X-Test-User": "sam@example.com"}).json()["notices"] == []  # Sam watches DEAR only
    yours = client.get("/api/coattail/notices?group=directors&days=365", headers={"X-Test-User": "sam@example.com"}).json()
    assert yours["rows"][0]["held"] is False  # shared notices, Sam's own flags
    with accounts.acting_as(sam.user_id):
        assert tools.call(session, "notices", {"mine": True, "days": 365})["notices"] == []


def test_dry_run_saves_nothing(db_session, monkeypatch, capsys):
    monkeypatch.setattr(notices, "get", FakeAsx())
    assert notices.main(["--dry-run", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "Director trade" in out and "read: Jane Citizen buy" in out
    assert db_session.execute(text("SELECT count(*) FROM asx_notices")).scalar() == 0
