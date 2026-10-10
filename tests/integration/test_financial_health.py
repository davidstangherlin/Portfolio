"""Financial health end to end (docs/kb/features/financial-health.md): the
nightly refresh, the screener columns, the company page, the AI tool and the
Z-Score caution, which never changes the action."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.ai import tools
from src.analytics import health
from tests.integration.test_screener import TODAY, _seed_and_value

pytestmark = pytest.mark.integration
D = Decimal


@pytest.fixture()
def scored(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", D("110000000"), D("0.60"), D("10.00"))
    _seed_and_value(db_session, "BANK", "Financial Services", D("110000000"), D("0.60"), D("10.00"))
    # The newest year improves on every count and has the fields the new checks need
    db_session.execute(text("""
        UPDATE financial_reports r SET current_assets = 300000000 + (r.fiscal_year - 2024) * 50000000,
               current_liabilities = 150000000, gross_profit = 200000000 + (r.fiscal_year - 2024) * 20000000,
               retained_earnings = 400000000, shares_outstanding = 100000000,
               revenue = 500000000 + (r.fiscal_year - 2024) * 50000000,
               net_profit_after_tax = 120000000 + (r.fiscal_year - 2024) * 10000000,
               total_debt = 100000000 - (r.fiscal_year - 2024) * 10000000
        FROM companies c WHERE c.company_id = r.company_id AND c.asx_code IN ('GOOD', 'BANK')"""))
    db_session.commit()
    counts = health.refresh(db_session, TODAY)
    db_session.commit()
    return db_session, counts


def test_scores_and_exclusions(scored):
    session, counts = scored
    assert counts == {"companies": 2, "f_scored": 1, "distress": 0}
    page = TestClient(gui.create_app()).get("/api/company/GOOD").json()["health"]
    assert page["f_level"] == "STRONG" and page["f_checks"] == 9 and page["f_words"] == "Strong"
    assert page["z_zone"] in ("SAFE", "GREY") and page["z_words"]
    bank = TestClient(gui.create_app()).get("/api/company/BANK").json()["health"]
    assert bank["f_score"] is None and "banks" in bank["excluded_reason"]


def test_screener_and_ai_tool_carry_it(scored):
    session, _ = scored
    rows = {r["asx_code"]: r for r in TestClient(gui.create_app()).get("/api/screener").json()["rows"]}
    assert rows["GOOD"]["f_level"] == "STRONG" and rows["GOOD"]["z_zone"] in ("SAFE", "GREY")
    facts = tools.call(session, "company", {"code": "GOOD"})["financial_health"]
    assert facts["f_score_reading"] == "Strong" and len(facts["f_score_checks"]) == 9


def test_distress_is_a_caution_not_a_new_action(scored):
    session, _ = scored
    before = {r["asx_code"]: r for r in TestClient(gui.create_app()).get("/api/screener").json()["rows"]}["GOOD"]["action"]
    session.execute(text("""UPDATE financial_reports r SET retained_earnings = -900000000, ebit = -50000000,
        current_assets = 50000000, current_liabilities = 400000000
        FROM companies c WHERE c.company_id = r.company_id AND c.asx_code = 'GOOD' AND r.fiscal_year = 2026"""))
    session.execute(text("UPDATE daily_prices SET market_cap = 10000000"))
    session.commit()
    health.refresh(session, TODAY)
    session.commit()
    row = {r["asx_code"]: r for r in TestClient(gui.create_app()).get("/api/screener").json()["rows"]}["GOOD"]
    assert row["z_zone"] == "DISTRESS" and row["action"] == before
    assert "caution: possible financial distress (Altman Z-Score" in row["action_reason"] or row["action"] == "IGNORE"
