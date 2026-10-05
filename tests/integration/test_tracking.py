"""Nightly signal snapshots (src/tracking/signals.py) against a real
PostgreSQL instance: one row per screened company per valuation date,
never edited once written, skipped when the valuation is behind the price,
and the action changes the dashboard's "What changed" panel reads."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models import DailyPrice, SignalSnapshot
from src.portfolio.holdings import add_parcel
from src.tracking.signals import RULES_VERSION, record_signals, signal_changes, tracking_status
from src.valuation.engine import run_valuation
from tests.integration.test_screener import TODAY, _seed_and_value

pytestmark = pytest.mark.integration

NEXT_DAY = TODAY + timedelta(days=3)  # Friday to Monday


def _seed(session):
    good = _seed_and_value(session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    dear = _seed_and_value(session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    return good, dear


def _snapshots(session):
    return {s.company_id: s for s in session.execute(select(SignalSnapshot)).scalars()}


def _new_close(session, company, price, on=NEXT_DAY):
    session.add(DailyPrice(company_id=company.company_id, price_date=on, close_price=price,
                           volume=100000, market_cap=price * Decimal("100000000")))
    session.commit()


def test_records_one_row_per_company_as_screened(db_session):
    good, dear = _seed(db_session)
    result = record_signals(db_session, TODAY)
    db_session.commit()

    assert (result.recorded, result.already_recorded, result.stale) == (2, 0, [])
    assert result.dates == {TODAY}
    snaps = _snapshots(db_session)
    g = snaps[good.company_id]
    assert g.snapshot_date == TODAY and g.price == Decimal("10.0000")
    assert g.action == "BUY" and g.held is False and g.valuation_status == "Undervalued"
    assert (g.mos_ok, g.roe_ok, g.de_ok, g.yield_ok) == (True, True, True, True)
    assert g.valuation_method == "DCF" and g.estimated_value > g.price
    assert g.score_total == g.score_value + g.score_performance + g.score_health + g.score_dividend + g.score_momentum
    assert g.rules_version == RULES_VERSION and g.red_flags == []
    assert snaps[dear.company_id].valuation_status == "Overvalued"


def test_a_recorded_date_is_never_rewritten(db_session):
    good, _ = _seed(db_session)
    record_signals(db_session, TODAY)
    db_session.commit()

    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15))  # action would now be ACCUMULATE
    db_session.commit()
    result = record_signals(db_session, TODAY)
    db_session.commit()

    assert (result.recorded, result.already_recorded) == (0, 2)
    g = _snapshots(db_session)[good.company_id]
    assert g.action == "BUY" and g.held is False  # what Sift said at the time


def test_valuation_behind_the_price_is_skipped_not_mispaired(db_session):
    good, dear = _seed(db_session)
    _new_close(db_session, good, Decimal("11.00"))  # price moved on, valuation not rerun
    result = record_signals(db_session, NEXT_DAY)
    db_session.commit()

    assert result.stale == ["GOOD"] and result.recorded == 1
    assert set(_snapshots(db_session)) == {dear.company_id}


def test_changes_between_the_latest_two_dates(db_session):
    good, dear = _seed(db_session)
    record_signals(db_session, TODAY)
    db_session.commit()
    assert signal_changes(db_session)["changes"] == []  # needs two dates

    for company, price in ((good, Decimal("60.00")), (dear, Decimal("60.00"))):  # GOOD is now dear too
        _new_close(db_session, company, price)
    run_valuation(db_session, asx_codes=["GOOD", "DEAR"])
    db_session.commit()
    record_signals(db_session, NEXT_DAY)
    db_session.commit()

    out = signal_changes(db_session)
    assert (out["from_date"], out["to_date"]) == (TODAY, NEXT_DAY)
    assert [(c["asx_code"], c["previous"], c["direction"]) for c in out["changes"]] == [("GOOD", "BUY", "down")]


def test_moves_caused_by_buying_are_not_changes(db_session):
    good, _ = _seed(db_session)
    record_signals(db_session, TODAY)
    db_session.commit()
    _new_close(db_session, good, Decimal("10.00"))
    run_valuation(db_session, asx_codes=["GOOD", "DEAR"])
    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15))
    db_session.commit()
    record_signals(db_session, NEXT_DAY)
    db_session.commit()

    assert signal_changes(db_session)["changes"] == []  # BUY to ACCUMULATE: same signal, now held


def test_tracking_status_counts_and_due_dates(db_session):
    assert tracking_status(db_session)["first_date"] is None
    _seed(db_session)
    record_signals(db_session, TODAY)
    db_session.commit()

    status = tracking_status(db_session)
    assert (status["first_date"], status["latest_date"]) == (TODAY, TODAY)
    assert (status["days_recorded"], status["signals_recorded"], status["companies_latest"]) == (1, 2, 2)
    assert status["results_due"][0] == {"months": 1, "date": date(2026, 11, 2)}
    assert [d["months"] for d in status["results_due"]] == [1, 3, 6, 12]
