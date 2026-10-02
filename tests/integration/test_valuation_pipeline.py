"""src/valuation/engine.py against a real PostgreSQL instance - the parts
that need an actual database: gather_inputs()'s queries, the upsert path's
overflow clamping, run_valuation()'s per-company crash isolation and
commit behaviour, and margin_of_safety_trend's cross-row lookup. Every one
of these has broken in practice at some point (see docs/AS_BUILT.md §10,
§11 known-issues #12/#13/#15) in ways a mocked session would not have
caught - this is why these are real-database tests, not unit tests with a
stub session, consistent with how the rest of this project has always
been validated.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models import Company, DailyPrice, FinancialReport, ValuationMetric
from src.valuation.engine import (
    DEFAULT_TREND_DAYS,
    gather_inputs,
    run_valuation,
    run_valuation_for_company,
    upsert_valuation_metric,
)

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 2)


def _seed_company(session, asx_code, sector="Basic Materials", fcf=Decimal("110000000"), dps=Decimal("0.60"), price=Decimal("10.00")):
    company = Company(
        ticker=f"{asx_code}.AX", company_name=f"{asx_code} Ltd", sector=sector,
        industry="Test", asx_code=asx_code, is_active=True,
    )
    session.add(company)
    session.flush()
    session.add(DailyPrice(company_id=company.company_id, price_date=TODAY, close_price=price,
                            volume=100000, market_cap=price * Decimal("100000000")))
    for year in (2024, 2025, 2026):
        session.add(FinancialReport(
            company_id=company.company_id, fiscal_year=year, period_type="FY", report_date=date(year, 6, 30),
            revenue=Decimal("500000000"), ebit=Decimal("150000000"), net_profit_after_tax=Decimal("120000000"),
            operating_cash_flow=Decimal("140000000"), free_cash_flow=fcf,
            capital_expenditure=Decimal("30000000"), eps=Decimal("1.20"),
            total_assets=Decimal("900000000"), total_liabilities=Decimal("200000000"),
            total_equity=Decimal("700000000"), total_debt=Decimal("100000000"),
            cash_and_equivalents=Decimal("80000000"), net_tangible_assets=Decimal("650000000"),
            dividends_per_share=dps, franking_percentage=Decimal("100.0"), corporate_tax_rate=Decimal("30.0"),
        ))
    session.commit()
    return company


def test_gather_inputs_round_trip(db_session):
    company = _seed_company(db_session, "ABC")
    inputs = gather_inputs(db_session, company)
    assert inputs is not None
    assert inputs.price.close_price == Decimal("10.00")
    assert len(inputs.reports) == 3  # default fcf_average_years=3
    assert inputs.prior_margin_of_safety_percent is None  # no prior snapshot seeded


def test_gather_inputs_none_when_no_price_or_reports(db_session):
    company = Company(ticker="NOPRICE.AX", company_name="No Price Ltd", sector="Basic Materials",
                       industry="Test", asx_code="NOPRIC", is_active=True)
    db_session.add(company)
    db_session.commit()
    assert gather_inputs(db_session, company) is None


def test_margin_of_safety_trend_uses_snapshot_at_least_trend_days_old(db_session):
    company = _seed_company(db_session, "TRND")
    old_date = TODAY - timedelta(days=DEFAULT_TREND_DAYS + 5)
    db_session.add(ValuationMetric(company_id=company.company_id, as_of_date=old_date,
                                    margin_of_safety_percent=Decimal("10.00")))
    db_session.commit()

    inputs = gather_inputs(db_session, company)
    assert inputs.prior_margin_of_safety_percent == Decimal("10.00")


def test_margin_of_safety_trend_ignores_snapshot_too_recent(db_session):
    # A snapshot only 5 days old (well under the default 30-day window)
    # must NOT be used as the baseline - this is the cold-start guard
    # working correctly, not a bug if it looks "unused".
    company = _seed_company(db_session, "RECNT")
    recent_date = TODAY - timedelta(days=5)
    db_session.add(ValuationMetric(company_id=company.company_id, as_of_date=recent_date,
                                    margin_of_safety_percent=Decimal("10.00")))
    db_session.commit()

    inputs = gather_inputs(db_session, company)
    assert inputs.prior_margin_of_safety_percent is None


def test_upsert_valuation_metric_clamps_overflow_before_write(db_session):
    # Regression for known-issue #15: a value that would overflow its
    # NUMERIC column must be stored as NULL, not crash the upsert, and the
    # returned dict must match what's actually in the database (known-issue
    # #15's same-day follow-up fix).
    company = _seed_company(db_session, "OVFL")
    metrics = {
        "as_of_date": TODAY, "pe_ratio": Decimal("15.00"), "pb_ratio": None,
        "price_to_fcf": None, "ev_to_ebit": None, "roe": Decimal("134600.00"),
        "roic": None, "debt_to_equity": None, "current_ratio": None,
        "uncapped_dividend_yield": None, "grossed_up_dividend_yield": None,
        "payout_ratio": None, "dcf_intrinsic_value": None, "graham_number": None,
        "margin_of_safety_percent": None, "valuation_method": None,
        "margin_of_safety_trend": None, "fundamentals_trend": None,
    }
    returned = upsert_valuation_metric(db_session, company.company_id, metrics)
    db_session.commit()

    assert returned["roe"] is None  # clamped in the return value too
    assert returned["pe_ratio"] == Decimal("15.00")

    stored = db_session.execute(
        select(ValuationMetric).where(ValuationMetric.company_id == company.company_id)
    ).scalar_one()
    assert stored.roe is None
    assert stored.pe_ratio == Decimal("15.00")


def test_run_valuation_for_company_ddm_routing_persists_valuation_method(db_session):
    bank = _seed_company(db_session, "BANK1", sector="Financial Services",
                          fcf=Decimal("-3500000000"), dps=Decimal("2.0000"), price=Decimal("25.00"))
    metrics = run_valuation_for_company(db_session, bank)
    db_session.commit()

    assert metrics is not None
    assert metrics["valuation_method"] == "DDM"

    stored = db_session.execute(
        select(ValuationMetric).where(ValuationMetric.company_id == bank.company_id)
    ).scalar_one()
    assert stored.valuation_method == "DDM"


def test_run_valuation_isolates_crash_and_commits_the_rest(db_session, monkeypatch):
    # Regression for known-issue #13: before per-company isolation was
    # added, a single company's exception mid-batch lost every other
    # company's already-computed work too, since the whole run shared one
    # commit() at the end. Forces a real exception for one company via
    # monkeypatch and confirms the other company's row still committed.
    good = _seed_company(db_session, "GOOD1")
    bad = _seed_company(db_session, "BAD1")

    import src.valuation.engine as engine_module
    original_compute = engine_module.compute_metrics

    def _boom(inputs, **kwargs):
        if inputs.company.asx_code == "BAD1":
            raise RuntimeError("simulated crash for BAD1")
        return original_compute(inputs, **kwargs)

    monkeypatch.setattr(engine_module, "compute_metrics", _boom)

    results = run_valuation(db_session, asx_codes=["GOOD1", "BAD1"])

    assert "GOOD1" in results
    assert "BAD1" not in results

    good_row = db_session.execute(
        select(ValuationMetric).where(ValuationMetric.company_id == good.company_id)
    ).scalar_one_or_none()
    bad_row = db_session.execute(
        select(ValuationMetric).where(ValuationMetric.company_id == bad.company_id)
    ).scalar_one_or_none()
    assert good_row is not None
    assert bad_row is None


def test_run_valuation_skips_company_with_no_data_without_crashing(db_session):
    company = Company(ticker="EMPTY.AX", company_name="Empty Ltd", sector="Basic Materials",
                       industry="Test", asx_code="EMPTY", is_active=True)
    db_session.add(company)
    db_session.commit()

    results = run_valuation(db_session, asx_codes=["EMPTY"])
    assert results == {}
