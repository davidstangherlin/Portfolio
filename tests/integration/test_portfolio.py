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


# ---------- portfolios (§19.1) ----------

from src.models import Portfolio  # noqa: E402
from src.portfolio.holdings import (  # noqa: E402
    archive_portfolio,
    create_portfolio,
    default_portfolio,
    delete_portfolio,
    find_portfolio,
    sold_parcels,
    undo_sale,
    update_portfolio,
)


def test_first_parcel_creates_my_portfolio(db_session):
    parcel = add_parcel(db_session, "BHP", D("10"), D("40"), date(2025, 1, 10))
    portfolio = db_session.get(Portfolio, parcel.portfolio_id)
    assert portfolio.name == "My portfolio" and portfolio.tax_type == "INDIVIDUAL"


def test_with_two_portfolios_you_must_choose(db_session):
    create_portfolio(db_session, "Mine")
    create_portfolio(db_session, "Super", "SMSF")
    with pytest.raises(HoldingsError, match="say which one"):
        add_parcel(db_session, "BHP", D("10"), D("40"), date(2025, 1, 10))


def test_names_are_unique_ignoring_case_and_spacing(db_session):
    create_portfolio(db_session, "Super  fund")
    with pytest.raises(HoldingsError, match="already a portfolio"):
        create_portfolio(db_session, "super fund")
    assert find_portfolio(db_session, "SUPER FUND").name == "Super fund"


def test_a_sale_only_uses_that_portfolios_parcels(db_session):
    mine = create_portfolio(db_session, "Mine")
    smsf = create_portfolio(db_session, "Super", "SMSF")
    add_parcel(db_session, "BHP", D("100"), D("40"), date(2024, 1, 10), portfolio=mine)
    add_parcel(db_session, "BHP", D("50"), D("30"), date(2024, 1, 10), portfolio=smsf)

    with pytest.raises(HoldingsError, match="only 50 units of BHP held in Super"):
        sell(db_session, "BHP", D("60"), D("45"), date(2026, 9, 1), portfolio=smsf)
    sold = sell(db_session, "BHP", D("20"), D("45"), date(2026, 9, 1), portfolio=smsf)
    assert sold[0].portfolio_id == smsf.portfolio_id  # the split-off sold portion stays in the portfolio
    assert open_parcels(db_session, "BHP", mine.portfolio_id)[0].units == D("100")


def test_min_tax_uses_the_portfolios_discount(db_session):
    # Old parcel: $60/unit gain, discount-eligible. New parcel: $35/unit, not eligible.
    # Individual (50%): old is $30 taxable, sold first. Company (no discount): new is smaller.
    for tax_type, expected_buy in (("INDIVIDUAL", date(2023, 1, 10)), ("COMPANY", date(2026, 6, 1))):
        p = create_portfolio(db_session, tax_type.title(), tax_type)
        add_parcel(db_session, "WES", D("10"), D("40"), date(2023, 1, 10), portfolio=p)
        add_parcel(db_session, "WES", D("10"), D("65"), date(2026, 6, 1), portfolio=p)
        sold = sell(db_session, "WES", D("10"), D("100"), date(2026, 9, 1), order="min-tax", portfolio=p)
        assert sold[0].buy_date == expected_buy, tax_type


def test_company_parcels_never_wait_for_a_discount(db_session):
    co = create_portfolio(db_session, "Pty Ltd", "COMPANY")
    add_parcel(db_session, "BHP", D("25"), D("45"), date(2026, 3, 1), portfolio=co)
    summary = position_summaries(db_session, date(2026, 10, 2))["BHP"]
    assert summary.units == D("25") and summary.next_discount_date is None


def test_undo_sale_puts_a_split_portion_back(db_session):
    parcel = add_parcel(db_session, "BHP", D("100"), D("40"), date(2024, 3, 1), D("10.00"))
    sold = sell(db_session, "BHP", D("30"), D("50"), date(2025, 6, 1))
    reopened = undo_sale(db_session, str(sold[0].holding_id))
    assert reopened.holding_id == parcel.holding_id
    assert (reopened.units, reopened.buy_brokerage) == (D("100"), D("10.00"))
    assert sold_parcels(db_session) == []


def test_undo_sale_of_a_whole_parcel_reopens_it(db_session):
    parcel = add_parcel(db_session, "BHP", D("100"), D("40"), date(2024, 3, 1))
    sell(db_session, "BHP", D("100"), D("50"), date(2025, 6, 1), D("9.95"))
    reopened = undo_sale(db_session, str(parcel.holding_id))
    assert reopened.is_open and reopened.sell_brokerage is None
    with pytest.raises(HoldingsError, match="hasn't been sold"):
        undo_sale(db_session, str(parcel.holding_id))


def test_archive_needs_everything_sold_and_blocks_trades(db_session):
    p = create_portfolio(db_session, "Old account")
    add_parcel(db_session, "BHP", D("10"), D("40"), date(2024, 3, 1), portfolio=p)
    with pytest.raises(HoldingsError, match="still holds 1 open parcel"):
        archive_portfolio(db_session, p)
    sell(db_session, "BHP", D("10"), D("50"), date(2025, 6, 1), portfolio=p)
    archive_portfolio(db_session, p)
    with pytest.raises(HoldingsError, match="archived"):
        add_parcel(db_session, "BHP", D("1"), D("40"), date(2025, 7, 1), portfolio=p)
    with pytest.raises(HoldingsError, match="archived"):
        undo_sale(db_session, str(sold_parcels(db_session, p.portfolio_id)[0].holding_id))
    assert default_portfolio(db_session).name == "My portfolio"  # archived ones don't count


def test_delete_refused_once_there_are_sales(db_session):
    p = create_portfolio(db_session, "Test")
    add_parcel(db_session, "BHP", D("10"), D("40"), date(2024, 3, 1), portfolio=p)
    add_parcel(db_session, "CBA", D("10"), D("100"), date(2024, 3, 1), portfolio=p)
    other = create_portfolio(db_session, "Test 2")
    add_parcel(db_session, "BHP", D("10"), D("40"), date(2024, 3, 1), portfolio=other)
    sell(db_session, "BHP", D("10"), D("50"), date(2025, 6, 1), portfolio=other)

    assert delete_portfolio(db_session, p) == 2
    assert db_session.get(Portfolio, p.portfolio_id) is None
    with pytest.raises(HoldingsError, match="archive it instead"):
        delete_portfolio(db_session, other)


def test_rename_and_change_tax_type(db_session):
    p = create_portfolio(db_session, "Mine")
    create_portfolio(db_session, "Theirs")
    update_portfolio(db_session, p, name="Ours", tax_type="trust")
    assert (p.name, p.tax_type) == ("Ours", "TRUST")
    with pytest.raises(HoldingsError, match="already a portfolio"):
        update_portfolio(db_session, p, name="theirs")


def test_cli_portfolio_option(db_session, capsys):
    import portfolio as cli

    assert cli.main(["portfolios", "create", "Super", "--tax-type", "smsf"]) == 0
    assert cli.main(["portfolios", "create", "Mine"]) == 0
    assert cli.main(["add", "BHP", "--units", "10", "--price", "40", "--date", "2024-01-10"]) == 1
    assert "say which one" in capsys.readouterr().err
    assert cli.main(["add", "BHP", "--units", "10", "--price", "40", "--date", "2024-01-10", "--portfolio", "super"]) == 0
    assert cli.main(["sell", "BHP", "--units", "10", "--price", "70", "--date", "2026-01-10", "-p", "Super"]) == 0
    capsys.readouterr()
    assert cli.main(["cgt"]) == 0
    out = capsys.readouterr().out
    assert "=== Super (Self-managed super fund (SMSF), CGT discount 33.3%) ===" in out
    assert "$200.00" in out  # $300 gain, one third off
    assert cli.main(["portfolios"]) == 0
    assert "Mine" in capsys.readouterr().out
