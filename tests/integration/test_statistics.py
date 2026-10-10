"""The nightly statistics (docs/kb/features/statistics.md): two years of
made-up prices where the share's daily moves are 1.5 times an ASX 200
fund's plus its own noise. Sift should find a volatility near the one
built in and a beta near 1.5, and show the likely range and the chance of
reaching its estimated value on the company page and in the AI tool."""

import math
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.ai import tools
from src.analytics import prices
from src.models import Company, DailyPrice
from tests.integration.test_screener import TODAY, _seed_and_value

pytestmark = pytest.mark.integration


@pytest.fixture()
def priced(db_session):
    share = _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    fund = Company(ticker="IOZ.AX", company_name="iShares Core S&P/ASX 200 ETF", asx_code="IOZ", is_active=True, security_type="ETF")
    db_session.add(fund)
    db_session.flush()
    days = [d for d in (TODAY - timedelta(days=i) for i in range(1, 730)) if d.weekday() < 5]  # newest first
    rng = np.random.default_rng(7)
    market = rng.normal(0, 0.01, len(days))
    own = rng.normal(0, 0.01, len(days))
    s_price, m_price = 10.0, 30.0
    db_session.add(DailyPrice(company_id=fund.company_id, price_date=TODAY, close_price=Decimal("30")))
    for d, m, e in zip(days, market, own):  # walk back from today's close
        s_price /= math.exp(1.5 * m + e)
        m_price /= math.exp(m)
        db_session.add(DailyPrice(company_id=share.company_id, price_date=d, close_price=Decimal(f"{s_price:.4f}")))
        db_session.add(DailyPrice(company_id=fund.company_id, price_date=d, close_price=Decimal(f"{m_price:.4f}")))
    db_session.commit()
    counts = prices.refresh(db_session, TODAY)
    db_session.commit()
    return db_session, share, counts


def test_volatility_beta_and_range_are_found(priced):
    session, share, counts = priced
    assert counts["market"] == "IOZ" and counts["securities"] == 2
    st = prices.company_statistics(session, share.company_id)
    built_in = math.sqrt(1.5 ** 2 * 0.01 ** 2 + 0.01 ** 2) * math.sqrt(252)   # about 28% a year
    assert st["volatility_percent"] / 100 == pytest.approx(built_in, rel=0.1)
    assert 1.25 < st["beta"] < 1.75 and st["market_code"] == "IOZ"
    assert st["price"] == 10.0 and st["range_low"] < 10 < st["range_high"]
    assert st["range_high"] == pytest.approx(10 * math.exp(st["volatility_percent"] / 100), rel=1e-3)


def test_chance_of_reaching_the_estimated_value(priced):
    session, share, _ = priced
    st = prices.company_statistics(session, share.company_id)
    value = next(x for x in st["chances"] if x["kind"] == "value")
    expected = prices.chance_of_reaching(10.0, value["level"], st["volatility_percent"] / 100)
    if value["already_reached"]:
        assert value["chance"] is None
    else:
        assert value["chance"] == pytest.approx(expected, abs=1e-4) and value["words"]["word"]


def test_on_the_company_page_and_in_the_ai_tool(priced):
    session, share, _ = priced
    company = TestClient(gui.create_app()).get("/api/company/GOOD").json()
    assert company["statistics"]["market_code"] == "IOZ" and company["statistics"]["chances"]
    facts = tools.call(session, "company", {"code": "GOOD"})
    stats = facts["price_statistics"]
    assert stats["beta_against_asx200"] == pytest.approx(company["statistics"]["beta"])
    assert len(stats["likely_range_12_months_two_years_in_three"]) == 2


def test_rerun_replaces_and_a_new_listing_has_no_volatility(priced):
    session, _, _ = priced
    fresh = _seed_and_value(session, "NEWCO", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("5.00"))
    for i in range(1, 30):  # a month of prices: listed recently
        session.add(DailyPrice(company_id=fresh.company_id, price_date=TODAY - timedelta(days=i), close_price=Decimal("5") + Decimal(i % 3) / 10))
    session.commit()
    prices.refresh(session, TODAY)
    session.commit()
    assert session.execute(text("SELECT count(*) FROM price_statistics")).scalar() == 3
    st = prices.company_statistics(session, fresh.company_id)
    assert st["volatility_percent"] is None and st["range_low"] is None
    assert all(x["chance"] is None for x in st["chances"])
