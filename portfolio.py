#!/usr/bin/env python3
"""Record your share parcels and see their CGT position.

Each buy (including DRP allocations) is its own parcel, because Australian
CGT, including the 12-month discount, is assessed per parcel. Selling part
of a parcel splits it automatically. Figures are a record-keeping aid, not
tax advice - confirm anything you lodge with the ATO or your accountant.

Parcels belong to portfolios, each with its owner's tax type (individual,
trust, SMSF or company), which sets the CGT discount. With one active
portfolio there's nothing to choose; with several, name one with
--portfolio on add and sell (list and cgt show every portfolio unless you
name one). The web GUI (gui.py) records the same trades in the browser.

Usage:
    python portfolio.py portfolios                       # list portfolios
    python portfolio.py portfolios create "Super" --tax-type SMSF
    python portfolio.py portfolios archive "Old account" # all sold: keep the records, hide it
    python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95
    python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --portfolio Super
    python portfolio.py add BHP --units 3 --price 44.10 --date 2025-09-25 --method DRP
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --brokerage 9.95
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --order min-tax
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --parcel 1a2b3c4d
    python portfolio.py list             # open parcels with unrealised gains and CGT discount dates
    python portfolio.py list --all       # include sold parcels
    python portfolio.py cgt              # realised gains summarised per financial year
    python portfolio.py cgt --fy 2025-26
    python portfolio.py delete 1a2b3c4d  # remove a parcel entered by mistake
    python portfolio.py undo-sale 5e6f7a8b  # reverse a sale entered by mistake
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal

from tabulate import tabulate

from src.config import get_session
from src.portfolio import cgt
from src.portfolio.holdings import (
    ACQUISITION_METHODS,
    SELL_ORDERS,
    HoldingsError,
    add_parcel,
    archive_portfolio,
    create_portfolio,
    default_portfolio,
    delete_parcel,
    discount_rate,
    find_portfolio,
    latest_prices,
    list_portfolios,
    open_parcels,
    realised_gain,
    sell,
    sold_parcels,
    unarchive_portfolio,
    undo_sale,
)

DISCLAIMER = "Record-keeping aid only, not tax advice. Carried-forward losses from earlier years aren't included."


def _units(value: Decimal) -> str:
    return f"{value.normalize():f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record share parcels and report their CGT position.")
    sub = parser.add_subparsers(dest="command", required=True)
    which = argparse.ArgumentParser(add_help=False)
    which.add_argument("--portfolio", "-p", help="portfolio name (needed for add/sell once you have more than one)")

    pf = sub.add_parser("portfolios", help="list, create, archive or unarchive portfolios")
    pf.add_argument("action", nargs="?", default="list", choices=["list", "create", "archive", "unarchive"])
    pf.add_argument("name", nargs="?", help="portfolio name (create, archive, unarchive)")
    pf.add_argument("--tax-type", default="INDIVIDUAL", choices=cgt.TAX_TYPES, type=str.upper,
                    help="owner's tax type, which sets the CGT discount (default INDIVIDUAL)")

    add = sub.add_parser("add", parents=[which], help="record a buy, DRP allocation or transfer-in as a new parcel")
    add.add_argument("asx_code")
    add.add_argument("--units", type=Decimal, required=True)
    add.add_argument("--price", type=Decimal, required=True, help="price per share")
    add.add_argument("--date", type=date.fromisoformat, required=True, help="trade date, YYYY-MM-DD")
    add.add_argument("--brokerage", type=Decimal, default=Decimal("0"), help="brokerage paid (adds to the cost base)")
    add.add_argument("--method", default="PURCHASE", choices=ACQUISITION_METHODS, type=str.upper)
    add.add_argument("--broker", help="broker or account the parcel is held with")
    add.add_argument("--notes")

    sl = sub.add_parser("sell", parents=[which], help="record a sale against your open parcels")
    sl.add_argument("asx_code")
    sl.add_argument("--units", type=Decimal, required=True)
    sl.add_argument("--price", type=Decimal, required=True, help="price per share")
    sl.add_argument("--date", type=date.fromisoformat, required=True, help="trade date, YYYY-MM-DD")
    sl.add_argument("--brokerage", type=Decimal, default=Decimal("0"), help="brokerage paid (reduces capital proceeds)")
    sl.add_argument("--order", default="fifo", choices=SELL_ORDERS,
                    help="which parcels to sell first: fifo (oldest first, default) or min-tax "
                         "(the parcels giving the smallest taxable gain, counting the CGT discount)")
    sl.add_argument("--parcel", help="sell from one specific parcel (ID or its first 8 characters)")

    ls = sub.add_parser("list", parents=[which], help="show parcels")
    ls.add_argument("--all", action="store_true", help="include sold parcels")

    cg = sub.add_parser("cgt", parents=[which], help="realised capital gains per financial year")
    cg.add_argument("--fy", help="one financial year, e.g. 2025-26")

    dl = sub.add_parser("delete", help="remove a parcel entered by mistake")
    dl.add_argument("parcel_id")

    un = sub.add_parser("undo-sale", help="reverse a sale entered by mistake")
    un.add_argument("parcel_id", help="the sold parcel's ID (shown by list --all)")
    return parser.parse_args(argv)


def _chosen(session, args):
    return find_portfolio(session, args.portfolio) if args.portfolio else default_portfolio(session)


def _in_scope(session, args, include_archived=False):
    """The named portfolio, or every portfolio when none is named."""
    if args.portfolio:
        return [find_portfolio(session, args.portfolio)]
    return list_portfolios(session, include_archived=include_archived)


def cmd_portfolios(session, args) -> None:
    if args.action != "list":
        if not args.name:
            raise HoldingsError(f"portfolios {args.action} needs a portfolio name")
        if args.action == "create":
            portfolio = create_portfolio(session, args.name, args.tax_type)
            print(f"Created {portfolio.name} ({cgt.TAX_TYPE_LABELS[portfolio.tax_type]}).")
        elif args.action == "archive":
            portfolio = archive_portfolio(session, find_portfolio(session, args.name))
            print(f"Archived {portfolio.name}. Its sale records stay in the CGT report.")
        else:
            portfolio = unarchive_portfolio(session, find_portfolio(session, args.name))
            print(f"{portfolio.name} is active again.")
        session.commit()
        return
    rows = []
    for portfolio in list_portfolios(session):
        rows.append({"portfolio": portfolio.name, "tax_type": cgt.TAX_TYPE_LABELS[portfolio.tax_type],
                     "cgt_discount": f"{discount_rate(portfolio) * 100:.1f}%".replace(".0%", "%"),
                     "open_parcels": len(open_parcels(session, portfolio_id=portfolio.portfolio_id)),
                     "sales": len(sold_parcels(session, portfolio.portfolio_id)),
                     "status": "archived" if portfolio.is_archived else "active"})
    if rows:
        print(tabulate(rows, headers="keys", tablefmt="simple"))
    else:
        print('No portfolios yet. The first "add" creates "My portfolio", or: '
              'python portfolio.py portfolios create NAME --tax-type INDIVIDUAL')


def cmd_add(session, args) -> None:
    parcel = add_parcel(session, args.asx_code, args.units, args.price, args.date, args.brokerage,
                        args.method, args.broker, args.notes, portfolio=_chosen(session, args))
    session.commit()
    eligible = cgt.discount_eligible_from(parcel.buy_date)
    print(f"Added {parcel.asx_code} parcel {str(parcel.holding_id)[:8]}: {_units(parcel.units)} units @ "
          f"{parcel.buy_price} on {parcel.buy_date}, cost base "
          f"${cgt.cost_base(parcel.units, parcel.buy_price, parcel.buy_brokerage):,.2f}. "
          f"CGT discount applies to sales from {eligible:%d %b %Y}.")


def cmd_sell(session, args) -> None:
    portfolio = find_portfolio(session, args.portfolio) if args.portfolio else None
    if portfolio is None and not args.parcel:
        portfolio = default_portfolio(session)
    sold = sell(session, args.asx_code, args.units, args.price, args.date, args.brokerage, args.order, args.parcel,
                portfolio=portfolio)
    session.commit()
    rows = []
    for parcel in sold:
        g = realised_gain(parcel)
        rows.append({"parcel": str(parcel.holding_id)[:8], "units": _units(g.units), "bought": g.buy_date,
                     "cost_base": g.cost_base, "proceeds": g.proceeds, "gain": g.gain,
                     "cgt_discount": "Y" if g.discount_eligible else "N"})
    print(f"Recorded sale of {_units(args.units)} {args.asx_code.upper()} on {args.date} ({cgt.financial_year(args.date)}):")
    print(tabulate(rows, headers="keys", floatfmt=".2f", tablefmt="simple"))
    print(f"\n{DISCLAIMER}")


def cmd_list(session, args) -> None:
    portfolios = _in_scope(session, args, include_archived=args.all)
    if not portfolios:
        print("No open parcels. Add one with: python portfolio.py add <CODE> --units N --price P --date YYYY-MM-DD")
        return
    for portfolio in portfolios:
        if len(portfolios) > 1 or args.portfolio:
            print(f"\n=== {portfolio.name} ({cgt.TAX_TYPE_LABELS[portfolio.tax_type]}"
                  f"{', archived' if portfolio.is_archived else ''}) ===")
        _list_portfolio(session, args, portfolio)


def _list_portfolio(session, args, portfolio) -> None:
    today = date.today()
    parcels = open_parcels(session, portfolio_id=portfolio.portfolio_id)
    prices = latest_prices(session, {p.asx_code for p in parcels})
    no_discount = discount_rate(portfolio) == 0

    rows, total_cost, total_value = [], Decimal("0"), Decimal("0")
    for p in parcels:
        cost = cgt.cost_base(p.units, p.buy_price, p.buy_brokerage)
        price = prices.get(p.asx_code)
        value = cgt.to_cents(p.units * price) if price is not None else None
        total_cost += cost
        if value is not None:
            total_value += value
        eligible_from = cgt.discount_eligible_from(p.buy_date)
        rows.append({
            "parcel": str(p.holding_id)[:8], "asx_code": p.asx_code, "method": p.acquisition_method,
            "units": _units(p.units), "bought": p.buy_date, "buy_price": p.buy_price, "cost_base": cost,
            "price": price, "value": value, "gain": value - cost if value is not None else None,
            "days_held": (today - p.buy_date).days,
            "cgt_discount": "n/a" if no_discount else "Y" if today >= eligible_from else f"from {eligible_from}",
            "broker": p.broker,
        })

    if rows:
        print("Open parcels")
        print(tabulate(rows, headers="keys", floatfmt=".2f", tablefmt="simple"))
        print(f"\nTotal cost base ${total_cost:,.2f}, market value ${total_value:,.2f} "
              f"(parcels with a known price), unrealised gain ${total_value - total_cost:,.2f}")
    elif portfolio.is_archived:
        print("No open parcels (archived).")
    else:
        print("No open parcels. Add one with: python portfolio.py add <CODE> --units N --price P --date YYYY-MM-DD")

    if args.all:
        sold = []
        for p in sold_parcels(session, portfolio.portfolio_id):
            g = realised_gain(p)
            sold.append({"parcel": str(p.holding_id)[:8], "asx_code": p.asx_code, "units": _units(p.units),
                         "bought": p.buy_date, "sold": p.sell_date, "cost_base": g.cost_base,
                         "proceeds": g.proceeds, "gain": g.gain,
                         "cgt_discount": "n/a" if no_discount else "Y" if g.discount_eligible else "N",
                         "fy": cgt.financial_year(p.sell_date)})
        if sold:
            print("\nSold parcels")
            print(tabulate(sold, headers="keys", floatfmt=".2f", tablefmt="simple"))


def cmd_cgt(session, args) -> None:
    """One report per portfolio: each is a separate taxpayer (or at least
    may be), with its own CGT discount."""
    shown = False
    for portfolio in _in_scope(session, args, include_archived=True):
        by_fy: dict[str, list[cgt.RealisedGain]] = defaultdict(list)
        for p in sold_parcels(session, portfolio.portfolio_id):
            by_fy[cgt.financial_year(p.sell_date)].append(realised_gain(p))
        years = [args.fy] if args.fy else sorted(by_fy)
        if not any(by_fy.get(fy) for fy in years):
            continue
        shown = True
        rate = discount_rate(portfolio)
        print(f"\n=== {portfolio.name} ({cgt.TAX_TYPE_LABELS[portfolio.tax_type]}, "
              f"CGT discount {rate * 100:.1f}%) ===".replace(".0%", "%"))
        _cgt_years(by_fy, years, rate)
    if not shown:
        print("No realised sales" + (f" in {args.fy}." if args.fy else " recorded yet."))
        return
    print(f"\n{DISCLAIMER} Losses are applied to non-discountable gains first, the order most favourable to "
          "the taxpayer. Discount: 50% for individuals and trusts, 33 1/3% for super funds, nil for companies.")


def _cgt_years(by_fy, years, rate) -> None:
    for fy in years:
        gains = by_fy.get(fy, [])
        if not gains:
            continue
        print(f"\nFinancial year {fy}")
        print(tabulate([{"asx_code": g.asx_code, "units": _units(g.units), "bought": g.buy_date, "sold": g.sell_date,
                         "cost_base": g.cost_base, "proceeds": g.proceeds, "gain": g.gain,
                         "cgt_discount": "Y" if g.discount_eligible else "N"} for g in gains],
                       headers="keys", floatfmt=".2f", tablefmt="simple"))
        s = cgt.summarise(fy, gains, rate)
        print(f"  Gains eligible for the discount:  ${s.discountable_gains:,.2f}")
        print(f"  Gains not eligible:               ${s.non_discountable_gains:,.2f}")
        print(f"  Capital losses:                   ${s.capital_losses:,.2f}")
        print(f"  Net capital gain (after losses, then the discount): ${s.net_capital_gain:,.2f}")
        if s.unused_losses:
            print(f"  Losses to carry forward:          ${s.unused_losses:,.2f}")


def cmd_delete(session, args) -> None:
    parcel = delete_parcel(session, args.parcel_id)
    session.commit()
    print(f"Deleted {parcel.asx_code} parcel {str(parcel.holding_id)[:8]} "
          f"({_units(parcel.units)} units bought {parcel.buy_date}).")


def cmd_undo_sale(session, args) -> None:
    parcel = undo_sale(session, args.parcel_id)
    session.commit()
    print(f"Sale reversed: {parcel.asx_code} parcel {str(parcel.holding_id)[:8]} is open again with "
          f"{_units(parcel.units)} units bought {parcel.buy_date}.")


COMMANDS = {"portfolios": cmd_portfolios, "add": cmd_add, "sell": cmd_sell, "list": cmd_list, "cgt": cmd_cgt,
            "delete": cmd_delete, "undo-sale": cmd_undo_sale}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with get_session() as session:
        try:
            COMMANDS[args.command](session, args)
        except HoldingsError as exc:
            session.rollback()
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
