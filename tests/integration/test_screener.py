"""screen_asx.py against a real PostgreSQL instance - build_query() and
annotate_row() operating on the actual asx_value_screener view, covering
the show-every-company redesign (docs/AS_BUILT.md §9, §10.10/§10.11):
every company appears regardless of pass/fail, NULL metrics read as 'N'
rather than erroring, and --sector/--passing-only/--rank-by all affect the
real SQL query correctly.
"""

from argparse import Namespace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from screen_asx import DEFAULT_MIN_MARGIN_OF_SAFETY, DEFAULT_MIN_MOS_TREND, DEFAULT_MIN_ROE, DEFAULT_MAX_DEBT_TO_EQUITY, DEFAULT_MIN_GROSSED_UP_YIELD, annotate_row, build_query
from src.models import Company, DailyPrice, FinancialReport, ValuationMetric
from src.valuation.engine import run_valuation

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 2)


def _default_args(**overrides):
    defaults = dict(
        min_margin_of_safety=DEFAULT_MIN_MARGIN_OF_SAFETY, min_roe=DEFAULT_MIN_ROE,
        max_debt_equity=DEFAULT_MAX_DEBT_TO_EQUITY, min_yield=DEFAULT_MIN_GROSSED_UP_YIELD,
        min_mos_trend=DEFAULT_MIN_MOS_TREND, sector=None, any_of=False, passing_only=False,
        rank_by="margin_of_safety", limit=None,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def _seed_and_value(session, asx_code, sector, fcf, dps, price, roe_npat=Decimal("120000000")):
    company = Company(ticker=f"{asx_code}.AX", company_name=f"{asx_code} Ltd", sector=sector,
                       industry="Test", asx_code=asx_code, is_active=True)
    session.add(company)
    session.flush()
    session.add(DailyPrice(company_id=company.company_id, price_date=TODAY, close_price=price,
                            volume=100000, market_cap=price * Decimal("100000000")))
    for year in (2024, 2025, 2026):
        session.add(FinancialReport(
            company_id=company.company_id, fiscal_year=year, period_type="FY", report_date=date(year, 6, 30),
            revenue=Decimal("500000000"), ebit=Decimal("150000000"), net_profit_after_tax=roe_npat,
            operating_cash_flow=Decimal("140000000"), free_cash_flow=fcf,
            capital_expenditure=Decimal("30000000"), eps=Decimal("1.20"),
            total_assets=Decimal("900000000"), total_liabilities=Decimal("200000000"),
            total_equity=Decimal("700000000"), total_debt=Decimal("100000000"),
            cash_and_equivalents=Decimal("80000000"), net_tangible_assets=Decimal("650000000"),
            dividends_per_share=dps, franking_percentage=Decimal("100.0"), corporate_tax_rate=Decimal("30.0"),
        ))
    session.commit()
    run_valuation(session, asx_codes=[asx_code])
    session.commit()
    return company


def _query_rows(session, args):
    query, params = build_query(args)
    return session.execute(text(query), params).mappings().all()


def test_show_every_company_not_just_passing(db_session):
    # GOOD clears every threshold; BAD clears none. Both must appear in
    # the unfiltered default query - the whole point of the show-every-
    # company redesign (§9) is that BAD doesn't just vanish.
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "BAD", "Technology", Decimal("3000000"), Decimal("0.01"), Decimal("100.00"), roe_npat=Decimal("5000000"))

    rows = [annotate_row(r, _default_args()) for r in _query_rows(db_session, _default_args())]
    codes = {r["asx_code"] for r in rows}
    assert codes == {"GOOD", "BAD"}

    good = next(r for r in rows if r["asx_code"] == "GOOD")
    bad = next(r for r in rows if r["asx_code"] == "BAD")
    assert good["overall"] == "Y"
    assert bad["overall"] == "N"


def test_sector_is_a_real_sql_filter(db_session):
    _seed_and_value(db_session, "MINE1", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "TECH1", "Technology", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))

    rows = _query_rows(db_session, _default_args(sector="Technology"))
    assert {r["asx_code"] for r in rows} == {"TECH1"}


def test_null_metric_reads_as_n_not_an_error(db_session):
    # A company with no dividend history at all (yield/payout both NULL)
    # must still appear, with yield_ok correctly 'N' rather than raising.
    _seed_and_value(db_session, "NODIV", "Basic Materials", Decimal("110000000"), None, Decimal("10.00"))

    rows = [annotate_row(r, _default_args()) for r in _query_rows(db_session, _default_args())]
    row = next(r for r in rows if r["asx_code"] == "NODIV")
    assert row["grossed_up_dividend_yield"] is None
    assert row["yield_ok"] == "N"


def test_passing_only_filters_after_annotation(db_session):
    _seed_and_value(db_session, "GOOD2", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "BAD2", "Technology", Decimal("3000000"), Decimal("0.01"), Decimal("100.00"), roe_npat=Decimal("5000000"))

    args = _default_args()
    all_rows = [annotate_row(r, args) for r in _query_rows(db_session, args)]
    passing_only = [r for r in all_rows if r["overall"] == "Y"]
    assert {r["asx_code"] for r in passing_only} == {"GOOD2"}


def test_rank_by_momentum_changes_order_by_clause():
    args_default = _default_args()
    args_momentum = _default_args(rank_by="momentum")

    query_default, _ = build_query(args_default)
    query_momentum, _ = build_query(args_momentum)

    assert "ORDER BY margin_of_safety_percent" in query_default
    assert "ORDER BY margin_of_safety_trend" in query_momentum


def test_held_position_gets_held_action_and_unheld_gets_buy_side_action(db_session):
    from src.portfolio.holdings import add_parcel, position_summaries

    _seed_and_value(db_session, "OWND", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "NOWN", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    add_parcel(db_session, "OWND", Decimal("200"), Decimal("8.50"), date(2025, 1, 15), Decimal("9.95"))
    db_session.commit()

    args = _default_args()
    positions = position_summaries(db_session, TODAY)
    rows = {r["asx_code"]: annotate_row(r, args, positions.get(r["asx_code"]), TODAY)
            for r in _query_rows(db_session, args)}

    # Identical companies: the held one gets a held-side action, the other a buy-side one
    assert rows["OWND"]["held"] == Decimal("200")
    assert rows["OWND"]["action"] == "ACCUMULATE"
    assert rows["OWND"]["action_reason"] == "still passes all four value tests with no red flags, consider adding"
    assert rows["NOWN"]["held"] is None
    assert rows["NOWN"]["action"] == "BUY"


def test_trap_risk_flags_cheap_but_declining_fundamentals(db_session):
    # mos_ok=Y (cheap) but fundamentals_trend will be DECLINING given a
    # sharply falling ROE/revenue profile - trap_risk must be Y.
    company = Company(ticker="TRAP1.AX", company_name="Trap1 Ltd", sector="Consumer Discretionary",
                       industry="Retail", asx_code="TRAP1", is_active=True)
    db_session.add(company)
    db_session.flush()
    db_session.add(DailyPrice(company_id=company.company_id, price_date=TODAY, close_price=Decimal("8.00"),
                               volume=100000, market_cap=Decimal("400000000")))
    roe_profile = {2023: Decimal("120000000"), 2024: Decimal("80000000"), 2025: Decimal("40000000"), 2026: Decimal("10000000")}
    revenue_profile = {2023: Decimal("900000000"), 2024: Decimal("800000000"), 2025: Decimal("700000000"), 2026: Decimal("600000000")}
    for year in (2023, 2024, 2025, 2026):
        db_session.add(FinancialReport(
            company_id=company.company_id, fiscal_year=year, period_type="FY", report_date=date(year, 6, 30),
            revenue=revenue_profile[year], ebit=roe_profile[year] * 2, net_profit_after_tax=roe_profile[year],
            operating_cash_flow=roe_profile[year], free_cash_flow=roe_profile[year] - Decimal("5000000"),
            capital_expenditure=Decimal("5000000"), eps=Decimal("0.20"),
            total_assets=Decimal("900000000"), total_liabilities=Decimal("300000000"),
            total_equity=Decimal("600000000"), total_debt=Decimal("150000000"),
            cash_and_equivalents=Decimal("50000000"), net_tangible_assets=Decimal("550000000"),
            dividends_per_share=Decimal("0.40"), franking_percentage=Decimal("100.0"), corporate_tax_rate=Decimal("30.0"),
        ))
    db_session.commit()
    run_valuation(db_session, asx_codes=["TRAP1"])
    db_session.commit()

    args = _default_args()
    rows = [annotate_row(r, args) for r in _query_rows(db_session, args)]
    row = next(r for r in rows if r["asx_code"] == "TRAP1")
    assert row["fundamentals_trend"] == "DECLINING"
    assert row["mos_ok"] == "Y"  # this profile (docs/AS_BUILT.md §10.11) is cheap enough to pass
    assert row["trap_risk"] == "Y"


def test_statements_that_cannot_be_converted_lower_confidence_and_rule_out_buy(db_session):
    """BFL, KSL and SST report in Papua New Guinea kina (known issue #36):
    while their statements can't be refreshed, nothing built on them is
    trusted enough to be a BUY."""
    from src.models import ValuationMetric
    from src.screening.actions import suggest_action

    company = _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    metric = lambda: db_session.query(ValuationMetric).filter_by(company_id=company.company_id).one()  # noqa: E731
    assert metric().data_confidence != "LOW"
    company.statements_issue = "statements can't be converted: no PGK/AUD rate within 10 days of 2025-12-31"
    db_session.commit()
    run_valuation(db_session, asx_codes=["GOOD"])
    db_session.commit()
    db_session.expire_all()
    assert metric().data_confidence == "LOW"
    row = {"mos_ok": "Y", "roe_ok": "Y", "de_ok": "Y", "yield_ok": "Y", "data_confidence": "LOW"}
    action, reason = suggest_action(row)
    assert action == "INVESTIGATE" and "low data confidence" in reason
