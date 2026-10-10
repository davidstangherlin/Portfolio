"""Short selling from ASIC (docs/kb/features/volume-and-short-selling.md): the
nightly load (ASIC replaced by a fake), the screener column and caution (a
heavily shorted BUY stays a BUY, with a caution), the company card, Coattail's
Most shorted, the watchlist trigger, and volume on the company page."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.ingestion import short_positions as sp
from src.watchlist import lists
from tests.integration.test_screener import TODAY, _seed_and_value

pytestmark = pytest.mark.integration

D = Decimal


def asic_file(rows):
    lines = ["Product\tProduct Code\tReported Short Positions\tTotal Product in Issue\t% of Total Product in Issue Reported as Short Positions"]
    lines += [f"{code} LTD\t{code}\t{pos}\t{issue}\t{pct}" for code, pos, issue, pct in rows]
    return "\n".join(lines).encode("utf-16")


@pytest.fixture()
def shorted(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", D("110000000"), D("0.60"), D("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", D("110000000"), D("0.60"), D("60.00"))
    db_session.commit()
    today = TODAY + timedelta(days=7)
    files = {}
    for back, good, dear in ((40, "3.00", "1.00"), (5, "12.50", "0.50")):  # GOOD's shorts build up over a month
        day = today - timedelta(days=back)
        while day.weekday() > 4:
            day -= timedelta(days=1)
        files[sp.URL.format(day=day)] = asic_file([("GOOD", 1000, 8000, good), ("DEAR", 10, 2000, dear), ("ZZZ", 5, 10, "50")])
    fetch = lambda url: (200, files[url]) if url in files else (404, b"")  # noqa: E731
    counts = sp.run(db_session, today, days=60, fetch=fetch)
    assert counts["loaded"] == 2
    return db_session, today, fetch


def test_load_is_kept_and_not_repeated(shorted):
    session, today, fetch = shorted
    assert session.execute(text("SELECT count(*) FROM short_positions")).scalar() == 6
    assert sp.run(session, today, days=60, fetch=fetch)["loaded"] == 0  # loaded days aren't fetched again
    good = sp.company_short(session, "GOOD", today)
    assert good["short_percent"] == D("12.5") and good["change_points"] == D("9.5") and len(good["history"]) == 2


def test_heavily_shorted_buy_stays_a_buy_with_a_caution(shorted):
    client = TestClient(gui.create_app())
    rows = {r["asx_code"]: r for r in client.get("/api/screener").json()["rows"]}
    good = rows["GOOD"]
    assert good["short_percent"] == 12.5 and good["action"] == "BUY" and good["short_caution"] == "HIGH"
    assert good["days_to_cover"] == 0.0  # 1,000 short against 100,000 traded a day
    assert "caution: heavily shorted (12.5% of shares sold short, 0.0 days to cover, up 9.5 points in a month)" in good["action_reason"]
    assert rows["DEAR"]["short_caution"] is None
    company = client.get("/api/company/GOOD").json()
    assert company["short_interest"]["change_points"] == 9.5 and company["short_caution"]["level"] == "HIGH"
    assert company["flags"] == []  # a caution, not a red flag
    assert company["volumes"][-1][1] == 100000  # shares traded on the day, for the volume chart


def test_most_shorted_and_rising(shorted):
    d = TestClient(gui.create_app()).get("/api/coattail/shorts").json()
    assert [r["asx_code"] for r in d["most"]][:2] == ["ZZZ", "GOOD"] and d["most"][0]["in_sift"] is False
    assert [r["asx_code"] for r in d["rising"]] == ["GOOD"] and d["rising"][0]["caution"] == "HIGH"


def test_watchlist_short_interest_trigger(shorted):
    session, _, _ = shorted
    w = lists.create_watchlist(session, "Shorts")
    lists.save_entry(session, w, "GOOD", lists.entry_fields({"short_above": "10"}))
    session.commit()
    entry = next(e for e in TestClient(gui.create_app()).get(f"/api/watchlists/{w.watchlist_id}").json()["items"] if e["asx_code"] == "GOOD")
    assert entry["triggered"] and entry["triggers"][0]["label"] == "Short interest above 10%"
