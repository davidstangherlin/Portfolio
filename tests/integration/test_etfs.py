"""ETFs end to end against the real schema (docs/AS_BUILT.md §25): loading
ASX reports, keeping ETFs out of the share screens, prices and
distributions with the first-time backfill and split refetch, and
performance with the check against the report."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from src.etf import asx_report, performance
from src.etf.prices import ingest_etf_prices
from src.ingestion.dividend_history import Payment
from src.ingestion.price_ingestion import fetch_bars
from src.ingestion.yahoo_client import PriceBar
from src.models import Company, DailyPrice, DividendPayment, EtfMonthly, EtfPerformance, ValuationMetric
from src.valuation.engine import run_valuation
from tests.unit._etf_report import ETFS, build_report

pytestmark = pytest.mark.integration


def _company(session, code, kind="SHARE"):
    c = Company(ticker=f"{code}.AX", asx_code=code, company_name=code, security_type=kind)
    session.add(c)
    session.flush()
    return c


def test_load_report_creates_etfs_and_monthly_rows(db_session, tmp_path):
    result = asx_report.load_report(db_session, build_report(tmp_path))
    db_session.commit()
    assert result.month == date(2026, 8, 1) and result.etfs == 5 and result.lics == 1
    assert result.added == ["GOLD", "HACK", "IOZ", "NDQ", "VAS", "ARG"]  # ETFs, then the LIC sheet's ARG
    assert db_session.execute(select(Company.security_type).where(Company.asx_code == "ARG")).scalar_one() == "LIC"
    vas = db_session.execute(select(Company).where(Company.asx_code == "VAS")).scalar_one()
    assert (vas.security_type, vas.ticker, vas.trading_currency, vas.is_active) == ("ETF", "VAS.AX", "AUD", True)
    assert vas.company_name == "Vanguard Australian Shares Index ETF"
    row = db_session.get(EtfMonthly, (vas.company_id, date(2026, 8, 1)))
    assert row.mer_percent == Decimal("0.070") and row.fum_aud == Decimal("18500500000.00")
    assert row.return_1y == Decimal("12.50") and row.raw["Performance (%) 1 Year"] == 12.5
    assert row.source_file == "asx-investment-products-aug-2026.xlsx"

    # Loading the same month again replaces it rather than duplicating.
    again = asx_report.load_report(db_session, build_report(tmp_path))
    db_session.commit()
    assert again.added == []
    assert db_session.execute(text("SELECT COUNT(*) FROM etf_monthly")).scalar_one() == 6


def test_newer_report_retires_and_reclassifies(db_session, tmp_path):
    share = _company(db_session, "HACK")  # somehow known as a share
    asx_report.load_report(db_session, build_report(tmp_path, etfs=[e for e in ETFS if e[0] != "GOLD"]))
    db_session.commit()
    hack = db_session.get(Company, share.company_id)
    assert hack.security_type == "ETF"

    later = build_report(tmp_path, "asx-investment-products-sep-2026.xlsx", etfs=[e for e in ETFS if e[0] != "NDQ"])
    result = asx_report.load_report(db_session, later)
    db_session.commit()
    assert result.deactivated == ["NDQ"] and result.added == ["GOLD"]
    ndq = db_session.execute(select(Company).where(Company.asx_code == "NDQ")).scalar_one()
    assert ndq.is_active is False
    assert db_session.execute(text("SELECT COUNT(*) FROM etf_monthly WHERE company_id = :c"),
                              {"c": ndq.company_id}).scalar_one() == 1  # its history is kept

    # Loading an older month afterwards doesn't retire anything.
    older = asx_report.load_report(db_session, build_report(tmp_path, "asx-investment-products-jul-2026.xlsx",
                                                            etfs=ETFS[:1]))
    assert older.deactivated == []


def test_ensure_latest(db_session, tmp_path):
    calls = []

    def no_network(url):
        calls.append(url)
        return None

    # Nothing anywhere: nothing loaded, and it says so without failing.
    assert asx_report.ensure_latest(db_session, date(2026, 9, 10), no_network, tmp_path) is None
    assert calls  # it tried

    # A file saved by hand is used before any download.
    build_report(tmp_path, "asx-investment-products-aug-2026.xlsx")
    calls.clear()
    assert asx_report.ensure_latest(db_session, date(2026, 9, 10), no_network, tmp_path).month == date(2026, 8, 1)
    db_session.commit()
    assert calls == []

    # Once last month's report is in, no request is made until next month.
    assert asx_report.ensure_latest(db_session, date(2026, 9, 28), no_network, tmp_path) is None
    assert calls == []


def test_etfs_are_kept_out_of_share_valuation_and_the_screener(db_session):
    etf = _company(db_session, "VAS", "ETF")
    db_session.add(DailyPrice(company_id=etf.company_id, price_date=date(2026, 9, 1), close_price=Decimal("100")))
    db_session.add(ValuationMetric(company_id=etf.company_id, as_of_date=date(2026, 9, 1)))  # e.g. left from before
    db_session.commit()
    assert "VAS" not in run_valuation(db_session, ["VAS"])
    assert db_session.execute(text("SELECT COUNT(*) FROM asx_value_screener WHERE asx_code = 'VAS'")).scalar_one() == 0


def test_security_type_is_checked(db_session):
    with pytest.raises(Exception, match="security_type"):
        _company(db_session, "XYZ", "BOND")
    db_session.rollback()


class FakeYahoo:
    """Prices from `days` (date -> close), splits and distributions;
    records the periods asked for."""
    periods: list[str] = []
    days: dict = {}
    splits: list = []
    dividends: list = []

    def __init__(self, code):
        self.asx_code = code
        self.last_splits, self.last_dividends = [], []

    def get_price_history(self, period="1mo", include_market_cap=True):
        FakeYahoo.periods.append(period)
        self.last_splits = list(FakeYahoo.splits)
        self.last_dividends = list(FakeYahoo.dividends)
        days = sorted(FakeYahoo.days.items())
        if period != "max":
            days = days[-22:]
            self.last_splits = [s for s in self.last_splits if s[0] >= days[0][0]]
            self.last_dividends = [p for p in self.last_dividends if p.ex_date >= days[0][0]]
        return [PriceBar(d, Decimal(str(c)), 1000, None) for d, c in days]


def _weekdays(start, end):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def fake_yahoo():
    FakeYahoo.periods, FakeYahoo.splits = [], []
    FakeYahoo.days = {d: 10.0 for d in _weekdays(date(2015, 1, 5), date(2026, 9, 30))}
    FakeYahoo.dividends = [Payment(date(2025, 12, 31), Decimal("0.25")), Payment(date(2026, 9, 15), Decimal("0.25"))]
    return FakeYahoo


def test_backfill_then_monthly_then_split(db_session, fake_yahoo):
    etf = _company(db_session, "VAS", "ETF")
    db_session.commit()

    assert ingest_etf_prices(db_session, client_factory=FakeYahoo)["VAS"] > 2900
    assert FakeYahoo.periods == ["max"]  # first time: the whole history
    paid = db_session.execute(select(DividendPayment.ex_date, DividendPayment.abnormal)
                              .where(DividendPayment.company_id == etf.company_id)).all()
    assert paid == [(date(2025, 12, 31), False), (date(2026, 9, 15), False)]

    FakeYahoo.periods.clear()
    ingest_etf_prices(db_session, client_factory=FakeYahoo)
    assert FakeYahoo.periods == ["1mo"]

    # A 2-for-1 split: the fetched closes before it halve, so the stored
    # history no longer matches and is refetched in full, once.
    split_day = date(2026, 9, 21)
    FakeYahoo.days = {d: (5.0 if d < split_day else 5.0) for d in FakeYahoo.days}
    FakeYahoo.splits = [(split_day, Decimal("2"))]
    FakeYahoo.dividends = [Payment(date(2025, 12, 31), Decimal("0.125")), Payment(date(2026, 9, 15), Decimal("0.125"))]
    FakeYahoo.periods.clear()
    ingest_etf_prices(db_session, client_factory=FakeYahoo)
    assert FakeYahoo.periods == ["1mo", "max"]
    oldest = db_session.execute(select(DailyPrice.close_price).where(DailyPrice.company_id == etf.company_id)
                                .order_by(DailyPrice.price_date).limit(1)).scalar_one()
    assert oldest == Decimal("5.0000")
    amounts = db_session.execute(select(DividendPayment.amount).where(DividendPayment.company_id == etf.company_id)
                                 .order_by(DividendPayment.ex_date)).scalars().all()
    assert amounts == [Decimal("0.1250"), Decimal("0.1250")]

    FakeYahoo.periods.clear()
    ingest_etf_prices(db_session, client_factory=FakeYahoo)
    assert FakeYahoo.periods == ["1mo"]  # history now agrees: no second refetch


def test_share_split_refetches_too(db_session, fake_yahoo):
    share = _company(db_session, "BHP")
    for d in list(FakeYahoo.days)[-60:]:
        db_session.add(DailyPrice(company_id=share.company_id, price_date=d, close_price=Decimal("10")))
    db_session.commit()
    FakeYahoo.days = {d: 5.0 for d in FakeYahoo.days}
    FakeYahoo.splits = [(date(2026, 9, 21), Decimal("2"))]
    bars, full = fetch_bars(db_session, FakeYahoo("BHP"), share, "1mo")
    assert full and FakeYahoo.periods == ["1mo", "max"] and len(bars) > 2900
    left = db_session.execute(text("SELECT COUNT(*) FROM daily_prices WHERE company_id = :c"),
                              {"c": share.company_id}).scalar_one()
    assert left == 0  # old closes cleared, ready for the full history


def test_performance_and_report_check(db_session, tmp_path, fake_yahoo):
    asx_report.load_report(db_session, build_report(tmp_path))
    db_session.commit()
    # VAS grows 10% a year from 2015; nothing else has prices.
    start = date(2015, 1, 5)
    FakeYahoo.days = {d: 10 * 1.1 ** ((d - start).days / 365.25) for d in FakeYahoo.days}
    FakeYahoo.dividends = []
    ingest_etf_prices(db_session, ["VAS"], client_factory=FakeYahoo)

    assert performance.update_performance(db_session) == 1
    db_session.commit()
    vas = db_session.execute(select(EtfPerformance).join(Company).where(Company.asx_code == "VAS")).scalar_one()
    assert vas.as_of_date == date(2026, 9, 30) and vas.first_price_date == start
    for value in (vas.return_1y, vas.return_3y, vas.return_5y, vas.return_10y, vas.return_since_inception):
        assert abs(value - Decimal("10")) < Decimal("0.2")
    assert vas.distribution_yield_12m == Decimal("0.00")
    assert vas.check_month == date(2026, 8, 1)
    assert abs(vas.check_return_1y - Decimal("10")) < Decimal("0.2")
    assert vas.reported_return_1y == Decimal("12.50")
    assert [c for c, _, _ in performance.report_differences(db_session)] == ["VAS"]  # 10 vs 12.5
    assert performance.report_differences(db_session, Decimal("3")) == []
