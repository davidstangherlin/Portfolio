"""Ingestion write paths against a real PostgreSQL instance: the
financial_reports upsert's franking handling and the companies.country
backfill. No network - Yahoo is replaced by an in-memory stand-in."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ingestion.common import ensure_country, get_or_create_company
from src.ingestion.fundamentals_ingestion import upsert_financial_report
from src.ingestion.yahoo_client import FundamentalsSnapshot
from src.models import Company, FinancialReport

pytestmark = pytest.mark.integration


class _FakeClient:
    def __init__(self, country):
        self.country = country
        self.profile_calls = 0

    def get_profile(self):
        self.profile_calls += 1
        return {"company_name": "Test Ltd", "sector": "Industrials", "industry": "Test", "country": self.country}


def _company(session, asx_code="TST", country=None):
    company = Company(ticker=f"{asx_code}.AX", company_name="Test Ltd", asx_code=asx_code, country=country)
    session.add(company)
    session.flush()
    return company


def _snapshot(dps=Decimal("0.50")):
    return FundamentalsSnapshot(fiscal_year=2026, period_type="FY", report_date=date(2026, 6, 30),
                                dividends_per_share=dps)


def _franking(session, company):
    session.expire_all()
    return session.execute(
        select(FinancialReport.franking_percentage).where(FinancialReport.company_id == company.company_id)
    ).scalar_one()


def test_new_company_captures_country(db_session):
    company = get_or_create_company(db_session, "NZC", client=_FakeClient("New Zealand"))
    assert company.country == "New Zealand"


def test_existing_company_country_is_backfilled_once(db_session):
    company = _company(db_session)
    client = _FakeClient("United States")
    ensure_country(company, client)
    ensure_country(company, client)
    assert company.country == "United States"
    assert client.profile_calls == 1


def test_foreign_company_is_stored_unfranked(db_session):
    company = _company(db_session, country="New Zealand")
    upsert_financial_report(db_session, company.company_id, _snapshot(), company.country)
    assert _franking(db_session, company) == Decimal("0")


def test_foreign_company_corrects_rows_stored_at_the_old_default(db_session):
    # Years ingested before country was known were written at 100%; the
    # next run must correct them, not just new years.
    company = _company(db_session)
    upsert_financial_report(db_session, company.company_id, _snapshot())
    assert _franking(db_session, company) == Decimal("100")

    company.country = "New Zealand"
    upsert_financial_report(db_session, company.company_id, _snapshot(), company.country)
    assert _franking(db_session, company) == Decimal("0")


def test_hand_corrected_franking_survives_reingestion_for_australian_company(db_session):
    company = _company(db_session, country="Australia")
    upsert_financial_report(db_session, company.company_id, _snapshot(), company.country)
    report = db_session.execute(select(FinancialReport)).scalar_one()
    report.franking_percentage = Decimal("50")  # the documented manual correction
    db_session.flush()

    upsert_financial_report(db_session, company.company_id, _snapshot(), company.country)
    assert _franking(db_session, company) == Decimal("50")
