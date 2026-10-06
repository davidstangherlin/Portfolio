"""Analyst ratings and holders (docs/AS_BUILT.md §29): the weekly
staggered fetch, storage, and the company page payload. Yahoo is
replaced by an in-memory stand-in."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.ingestion import insights_ingestion as ii
from src.ingestion.yahoo_client import Holder, Insights, RatingMonth
from src.models import Company
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration
TODAY = date.today()


def _insights(month=date(2026, 10, 1), funds=2):
    return Insights(recommendation_key="buy", recommendation_mean=Decimal("2.1"), analyst_count=12,
                    target_low=Decimal("8"), target_mean=Decimal("11.5"), target_median=Decimal("11"),
                    target_high=Decimal("14"), insiders_percent=Decimal("3.12"), institutions_percent=Decimal("41.27"),
                    institutions_float_percent=Decimal("42.6"), institutions_count=312,
                    ratings=[RatingMonth(month, 3, 6, 2, 1, 0)],
                    funds=[Holder(i, f"Fund {i}", Decimal("1000"), Decimal("1.2"), None, Decimal("-1.5"), date(2026, 6, 30))
                           for i in range(1, funds + 1)],
                    institutions=[Holder(1, "Big Institution", Decimal("5000"), Decimal("4"), None, None, None)])


class _FakeYahoo:
    calls = []

    def __init__(self, code):
        self.code = code

    def get_insights(self, today):
        _FakeYahoo.calls.append(self.code)
        return None if self.code == "ERR" else _insights()


def _companies(session, codes):
    for code in codes:
        session.add(Company(ticker=f"{code}.AX", company_name=code, asx_code=code))
    session.flush()


def _fetched(session, code, days_ago):
    session.execute(text("""
        INSERT INTO company_insights (company_id, fetched_at)
        SELECT company_id, CURRENT_TIMESTAMP - make_interval(days => :d) FROM companies WHERE asx_code = :c
    """), {"c": code, "d": days_ago})


def test_a_seventh_each_night_never_fetched_first_then_oldest(db_session):
    codes = [f"C{i:02d}" for i in range(14)]
    _companies(db_session, codes)
    for i, code in enumerate(codes[:12]):
        _fetched(db_session, code, 7 + i % 3 if i < 4 else 2)  # C00-C03 a week or more old, the rest fresh
    db_session.commit()
    due = ii.due_for_refresh(db_session, codes, TODAY)
    assert due == ["C12", "C13"]  # 14 / 7 = 2 a night; never fetched first
    assert ii.due_for_refresh(db_session, codes, TODAY, all_now=True) == ["C12", "C13", "C02", "C01", "C00", "C03"]
    assert "C04" not in ii.due_for_refresh(db_session, codes, TODAY, all_now=True)  # fetched 2 days ago


def test_ingest_stores_and_a_failure_is_retried(db_session):
    _companies(db_session, ["AAA", "ERR"])
    db_session.commit()
    _FakeYahoo.calls = []
    assert ii.ingest_insights(db_session, ["AAA", "ERR"], TODAY, all_now=True, client_factory=_FakeYahoo) == {
        "AAA": True, "ERR": False}
    assert ii.due_for_refresh(db_session, ["AAA", "ERR"], TODAY, all_now=True) == ["ERR"]
    n = db_session.execute(text("SELECT count(*) FROM top_holders")).scalar()
    assert n == 3


def test_a_new_fetch_replaces_holders_and_keeps_rating_history(db_session):
    _companies(db_session, ["AAA"])
    cid = db_session.query(Company).filter_by(asx_code="AAA").one().company_id
    ii.store_insights(db_session, cid, _insights(date(2026, 9, 1), funds=5))
    ii.store_insights(db_session, cid, _insights(date(2026, 10, 1), funds=1))
    db_session.commit()
    holders = db_session.execute(text("SELECT holder_kind, count(*) FROM top_holders GROUP BY 1 ORDER BY 1")).all()
    assert holders == [("FUND", 1), ("INSTITUTION", 1)]
    months = db_session.execute(text("SELECT rating_month FROM analyst_ratings ORDER BY 1")).scalars().all()
    assert months == [date(2026, 9, 1), date(2026, 10, 1)]


def test_company_page_shows_insights(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    db_session.commit()
    client = TestClient(gui.create_app())
    assert client.get("/api/company/GOOD").json()["company"]["insights"] is None  # not fetched yet

    cid = db_session.query(Company).filter_by(asx_code="GOOD").one().company_id
    ii.store_insights(db_session, cid, _insights())
    db_session.commit()
    c = client.get("/api/company/GOOD").json()["company"]
    ins = c["insights"]
    assert ins["recommendation_key"] == "buy" and ins["target_mean"] == 11.5 and ins["institutions_count"] == 312
    assert [r["strong_buy"] for r in ins["ratings"]] == [3]
    assert [f["holder"] for f in ins["funds"]] == ["Fund 1", "Fund 2"] and ins["institutions"][0]["holder"] == "Big Institution"
    assert ins["funds"][0]["value_now"] == pytest.approx(1000 * c["current_price"])
    assert date.fromisoformat(ins["fetched_at"][:10]) >= TODAY - timedelta(days=1)
