"""src/portfolio/holdings.py against a real PostgreSQL instance: parcel
splitting on partial sales, brokerage apportionment, sale ordering and the
guards that keep the records consistent."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from src.models import Company, DailyPrice, Holding
from src.portfolio import cgt
from src.portfolio.holdings import (
    HoldingsError,
    add_parcel,
    delete_parcel,
    latest_prices,
    open_parcels,
    position_summaries,
    realised_gain,
    sell,
)

pytestmark = pytest.mark.integration

D = Decimal


def test_partial_sale_splits_parcel_and_preserves_cost_base(db_session):
    parcel = add_parcel(db_session, "bhp", D("100"), D("40.00"), date(2024, 3, 1), D("10.00"))
    original_cost = cgt.cost_base(parcel.units, parcel.buy_price, parcel.buy_brokerage)

    sold = sell(db_session, "BHP", D("30"), D("50.00"), date(2025, 6, 1), D("9.95"))
    db_session.commit()

    assert len(sold) == 1
    sold_portion = sold[0]
    assert sold_portion.units == D("30")
    assert sold_portion.buy_brokerage == D("3.00")
    assert sold_portion.split_from_id == parcel.holding_id
    assert sold_portion.sell_brokerage == D("9.95")

    remaining = db_session.get(Holding, parcel.holding_id)
    assert remaining.units == D("70")
    assert remaining.buy_brokerage == D("7.00")
    assert remaining.is_open

    split_cost = (cgt.cost_base(remaining.units, remaining.buy_price, remaining.buy_brokerage)
                  + cgt.cost_base(sold_portion.units, sold_portion.buy_price, sold_portion.buy_brokerage))
    assert split_cost == original_cost

    gain = realised_gain(sold_portion)
    assert gain.cost_base == D("1203.00")
    assert gain.proceeds == D("1490.05")
    assert gain.discount_eligible


def test_fifo_sells_oldest_parcel_first_across_parcels(db_session):
    old = add_parcel(db_session, "CBA", D("10"), D("100"), date(2023, 1, 10))
    new = add_parcel(db_session, "CBA", D("10"), D("150"), date(2026, 5, 1))

    sold = sell(db_session, "CBA", D("15"), D("160"), date(2026, 9, 1), D("10.00"))
    db_session.commit()

    assert [s.buy_date for s in sold] == [old.buy_date, new.buy_date]
    assert [s.units for s in sold] == [D("10"), D("5")]
    assert sum((s.sell_brokerage for s in sold), D("0")) == D("10.00")  # apportioned, nothing lost to rounding
    assert db_session.get(Holding, new.holding_id).units == D("5")


def test_min_tax_prefers_the_smaller_taxable_gain(db_session):
    # Old cheap parcel: $60/unit gain, discounted to $30 taxable.
    # New dear parcel: $10/unit gain, not discounted - still smaller, sold first.
    add_parcel(db_session, "WES", D("10"), D("40"), date(2023, 1, 10))
    dear = add_parcel(db_session, "WES", D("10"), D("90"), date(2026, 6, 1))

    sold = sell(db_session, "WES", D("10"), D("100"), date(2026, 9, 1), order="min-tax")
    db_session.commit()

    assert len(sold) == 1
    assert sold[0].holding_id == dear.holding_id


def test_specific_parcel_sale(db_session):
    add_parcel(db_session, "CSL", D("5"), D("250"), date(2023, 1, 10))
    chosen = add_parcel(db_session, "CSL", D("5"), D("280"), date(2024, 1, 10))

    sold = sell(db_session, "CSL", D("5"), D("300"), date(2026, 9, 1), parcel_id=str(chosen.holding_id)[:8])
    assert sold[0].holding_id == chosen.holding_id


def test_cannot_sell_more_than_held(db_session):
    add_parcel(db_session, "WOW", D("10"), D("30"), date(2025, 1, 10))
    with pytest.raises(HoldingsError, match="only 10"):
        sell(db_session, "WOW", D("11"), D("35"), date(2026, 9, 1))


def test_cannot_sell_before_the_parcel_was_bought(db_session):
    add_parcel(db_session, "WOW", D("10"), D("30"), date(2026, 9, 1))
    with pytest.raises(HoldingsError):
        sell(db_session, "WOW", D("10"), D("35"), date(2026, 8, 1))


def test_schema_rejects_sell_before_buy(db_session):
    db_session.add(Holding(asx_code="XYZ", units=D("1"), buy_price=D("1"), buy_date=date(2026, 9, 1),
                           sell_date=date(2026, 8, 1), sell_price=D("1")))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_delete_parcel(db_session):
    parcel = add_parcel(db_session, "TLS", D("100"), D("4"), date(2025, 1, 10))
    db_session.commit()
    delete_parcel(db_session, str(parcel.holding_id)[:8])
    db_session.commit()
    assert open_parcels(db_session, "TLS") == []


def test_position_summary_reports_next_cgt_discount_date(db_session):
    add_parcel(db_session, "BHP", D("100"), D("40"), date(2024, 1, 10))  # already eligible
    add_parcel(db_session, "BHP", D("25"), D("45"), date(2026, 3, 1))     # eligible from 2 Mar 2027
    db_session.commit()

    summary = position_summaries(db_session, date(2026, 10, 2))["BHP"]
    assert summary.units == D("125")
    assert summary.next_discount_date == date(2027, 3, 2)
    assert summary.units_pending_discount == D("25")


def test_latest_prices_uses_most_recent_close(db_session):
    company = Company(ticker="BHP.AX", company_name="BHP", asx_code="BHP", sector="Basic Materials")
    db_session.add(company)
    db_session.flush()
    db_session.add_all([
        DailyPrice(company_id=company.company_id, price_date=date(2026, 9, 30), close_price=D("44.00")),
        DailyPrice(company_id=company.company_id, price_date=date(2026, 10, 1), close_price=D("45.50")),
    ])
    db_session.commit()
    assert latest_prices(db_session, {"BHP", "NOTLISTED"}) == {"BHP": D("45.5000")}
