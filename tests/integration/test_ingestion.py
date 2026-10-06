"""Ingestion write paths against a real PostgreSQL instance: the
financial_reports upsert's franking handling and the companies.country
backfill. No network - Yahoo is replaced by an in-memory stand-in."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ingestion.common import ensure_profile, get_or_create_company
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
    ensure_profile(company, client)
    ensure_profile(company, client)
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


def test_ingestion_replaces_an_inflated_dividend_and_records_the_abnormal_one(db_session, monkeypatch):
    # Tower-shaped: the stored FY25 figure had the March 2025 capital return
    # summed in as a dividend (the old calendar-year sum). Re-ingesting must
    # overwrite it with the ordinary dividend and keep the excluded amount.
    from src.ingestion import fundamentals_ingestion
    from src.ingestion.dividend_history import Payment

    company = _company(db_session, "TWR", country="New Zealand")
    db_session.add(FinancialReport(company_id=company.company_id, fiscal_year=2025, period_type="FY",
                                   report_date=date(2025, 9, 30), eps=Decimal("0.229"), dividends_per_share=Decimal("1.19")))
    db_session.commit()

    payments = [Payment(date.fromisoformat(d), Decimal(a)) for d, a in (
        ("2023-06-14", "0.030"), ("2024-06-12", "0.030"), ("2025-01-15", "0.065"), ("2025-03-18", "1.0777"),
        ("2025-06-11", "0.072"), ("2026-01-14", "0.150"))]

    class FakeYahoo:
        def __init__(self, code):
            self.asx_code = code

        def get_profile(self):
            return {"country": "New Zealand"}

        def get_annual_fundamentals(self, max_years=4):
            return [FundamentalsSnapshot(fiscal_year=2025, period_type="FY", report_date=date(2025, 9, 30), eps=Decimal("0.229"))]

        def get_dividend_payments(self):
            return payments

    monkeypatch.setattr(fundamentals_ingestion, "YahooClient", FakeYahoo)
    fundamentals_ingestion.ingest_fundamentals(db_session, ["TWR"])

    db_session.expire_all()
    report = db_session.execute(select(FinancialReport)).scalar_one()
    assert report.dividends_per_share == Decimal("0.2220")  # June 2025 interim + January 2026 final
    assert report.abnormal_distributions_per_share == Decimal("1.0777")


class _StatementsYahoo:
    """A US-dollar reporter trading in AUD, BHP-shaped."""
    fx = [(date(2025, 6, 30), Decimal("1.5"))]

    def __init__(self, code):
        self.asx_code = code

    def get_profile(self):
        return {"company_name": "Big Miner Ltd", "country": "Australia", "trading_currency": "AUD", "financial_currency": "USD"}

    def get_annual_fundamentals(self, max_years=4):
        return [FundamentalsSnapshot(fiscal_year=2025, period_type="FY", report_date=date(2025, 6, 30),
                                     eps=Decimal("2.00"), net_profit_after_tax=Decimal("1000"), total_equity=Decimal("5000"))]

    def get_dividend_payments(self):
        return []

    def get_fx_history(self, from_currency, to_currency, start, end):
        assert (from_currency, to_currency) == ("USD", "AUD")
        return self.fx


def test_us_dollar_statements_are_stored_in_aud_with_the_rate(db_session, monkeypatch):
    from src.ingestion import fundamentals_ingestion

    monkeypatch.setattr(fundamentals_ingestion, "YahooClient", _StatementsYahoo)
    assert fundamentals_ingestion.ingest_fundamentals(db_session, ["BIG"]) == {"BIG": 1}

    db_session.expire_all()
    company = db_session.execute(select(Company)).scalar_one()
    report = db_session.execute(select(FinancialReport)).scalar_one()
    assert (company.trading_currency, company.financial_currency) == ("AUD", "USD")
    assert report.eps == Decimal("3.0000")  # US$2.00 x 1.5
    assert report.net_profit_after_tax == Decimal("1500.00")
    assert (report.reporting_currency, report.fx_rate) == ("USD", Decimal("1.500000"))


def test_no_exchange_rate_skips_the_company_instead_of_storing_unconverted(db_session, monkeypatch):
    from src.ingestion import fundamentals_ingestion

    class NoRates(_StatementsYahoo):
        fx = []

    monkeypatch.setattr(fundamentals_ingestion, "YahooClient", NoRates)
    assert fundamentals_ingestion.ingest_fundamentals(db_session, ["BIG"]) == {"BIG": 0}
    assert db_session.execute(select(FinancialReport)).first() is None


def test_existing_company_gets_its_currencies_backfilled_once(db_session):
    company = _company(db_session, "OLD", country="Australia")
    client = _StatementsYahoo("OLD")
    calls = []
    client.get_profile = lambda: calls.append(1) or _StatementsYahoo.get_profile(client)
    ensure_profile(company, client)
    ensure_profile(company, client)
    assert (company.trading_currency, company.financial_currency) == ("AUD", "USD")
    assert len(calls) == 1


def test_dividend_payments_are_stored_with_one_offs_flagged(db_session, monkeypatch):
    from src.ingestion import fundamentals_ingestion
    from src.ingestion.dividend_history import Payment
    from src.models import DividendPayment

    payments = [Payment(date.fromisoformat(d), Decimal(a)) for d, a in (
        ("2024-06-12", "0.030"), ("2025-01-15", "0.065"), ("2025-03-18", "1.0777"), ("2025-06-11", "0.072"))]

    class FakeYahoo(_StatementsYahoo):
        def get_profile(self):
            return {"country": "New Zealand"}

        def get_dividend_payments(self):
            return payments

    monkeypatch.setattr(fundamentals_ingestion, "YahooClient", FakeYahoo)
    fundamentals_ingestion.ingest_fundamentals(db_session, ["TWR"])
    fundamentals_ingestion.ingest_fundamentals(db_session, ["TWR"])  # re-run updates, never duplicates

    rows = db_session.execute(select(DividendPayment).order_by(DividendPayment.ex_date)).scalars().all()
    assert [(r.ex_date.isoformat(), r.abnormal) for r in rows] == [
        ("2024-06-12", False), ("2025-01-15", False), ("2025-03-18", True), ("2025-06-11", False)]


class _SummaryClient:
    def __init__(self, profile):
        self.profile, self.calls = profile, 0

    def get_profile(self):
        self.calls += 1
        return self.profile


def test_business_summary_is_backfilled_once_and_a_missing_one_is_not_asked_for_again(db_session):
    base = {"country": "Australia", "trading_currency": "AUD", "financial_currency": "AUD"}
    company = _company(db_session, "SUM", country="Australia")
    client = _SummaryClient({**base, "business_summary": "Sum Ltd makes things."})
    ensure_profile(company, client)
    ensure_profile(company, client)
    assert company.business_summary == "Sum Ltd makes things." and client.calls == 1

    none = _company(db_session, "NON", country="Australia")
    client = _SummaryClient({**base, "business_summary": ""})
    ensure_profile(none, client)
    ensure_profile(none, client)
    assert none.business_summary == "" and client.calls == 1

    failed = _company(db_session, "ERR", country="Australia")
    ensure_profile(failed, _SummaryClient({}))  # fetch failed: try again next run
    assert failed.business_summary is None
    created = get_or_create_company(db_session, "NEW", client=_SummaryClient({**base, "business_summary": "New."}))
    assert created.business_summary == "New."


def test_weekly_fundamentals_take_the_oldest_seventh_and_a_failed_fetch_is_retried(db_session, monkeypatch):
    from sqlalchemy import text
    from src.ingestion import fundamentals_ingestion
    from src.ingestion.fundamentals_ingestion import due_for_fundamentals

    codes = [f"F{i:02d}" for i in range(14)]
    for code in codes:
        _company(db_session, code)
    db_session.execute(text("UPDATE companies SET fundamentals_fetched_at = CURRENT_TIMESTAMP"))
    db_session.execute(text("UPDATE companies SET fundamentals_fetched_at = CURRENT_TIMESTAMP - interval '9 days' WHERE asx_code = 'F03'"))
    db_session.execute(text("UPDATE companies SET fundamentals_fetched_at = NULL WHERE asx_code = 'F07'"))
    db_session.commit()
    assert due_for_fundamentals(db_session, codes + ["NEW"]) == ["F07", "NEW", "F03"]  # 15 / 7 -> 3 a night

    class Failing(_StatementsYahoo):
        def __init__(self, code):
            super().__init__(code)
            self.statements_failed = code == "F03"

        def get_annual_fundamentals(self, max_years=4):
            return [] if self.statements_failed else super().get_annual_fundamentals(max_years)

    monkeypatch.setattr(fundamentals_ingestion, "YahooClient", Failing)
    fundamentals_ingestion.ingest_fundamentals(db_session, ["F07", "F03"])
    stamped = dict(db_session.execute(text(
        "SELECT asx_code, fundamentals_fetched_at > CURRENT_TIMESTAMP - interval '1 hour' FROM companies "
        "WHERE asx_code IN ('F07', 'F03')")).all())
    assert stamped == {"F07": True, "F03": False}  # F03's request failed: due again tomorrow, not in a week
    assert due_for_fundamentals(db_session, codes) == ["F03"]
