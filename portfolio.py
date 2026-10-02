#!/usr/bin/env python3
"""Record your share parcels and see their CGT position.

Each buy (including DRP allocations) is its own parcel, because Australian
CGT, including the 12-month discount, is assessed per parcel. Selling part
of a parcel splits it automatically. Figures are a record-keeping aid, not
tax advice - confirm anything you lodge with the ATO or your accountant.

Usage:
    python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95
    python portfolio.py add BHP --units 3 --price 44.10 --date 2025-09-25 --method DRP
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --brokerage 9.95
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --order min-tax
    python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --parcel 1a2b3c4d
    python portfolio.py list             # open parcels with unrealised gains and CGT discount dates
    python portfolio.py list --all       # include sold parcels
    python portfolio.py cgt              # realised gains summarised per financial year
    python portfolio.py cgt --fy 2025-26
    python portfolio.py delete 1a2b3c4d  # remove a parcel entered by mistake
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
    delete_parcel,
    latest_prices,
    open_parcels,
    realised_gain,
    sell,
    sold_parcels,
)

DISCLAIMER = "Record-keeping aid only, not tax advice. Carried-forward losses from earlier years aren't included."


def _units(value: Decimal) -> str:
    return f"{value.normalize():f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record share parcels and report their CGT position.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="record a buy, DRP allocation or transfer-in as a new parcel")
    add.add_argument("asx_code")
    add.add_argument("--units", type=Decimal, required=True)
    add.add_argument("--price", type=Decimal, required=True, help="price per share")
    add.add_argument("--date", type=date.fromisoformat, required=True, help="trade date, YYYY-MM-DD")
    add.add_argument("--brokerage", type=Decimal, default=Decimal("0"), help="brokerage paid (adds to the cost base)")
    add.add_argument("--method", default="PURCHASE", choices=ACQUISITION_METHODS, type=str.upper)
    add.add_argument("--broker", help="broker or account the parcel is held with")
    add.add_argument("--notes")

    sl = sub.add_parser("sell", help="record a sale against your open parcels")
    sl.add_argument("asx_code")
    sl.add_argument("--units", type=Decimal, required=True)
    sl.add_argument("--price", type=Decimal, required=True, help="price per share")
    sl.add_argument("--date", type=date.fromisoformat, required=True, help="trade date, YYYY-MM-DD")
    sl.add_argument("--brokerage", type=Decimal, default=Decimal("0"), help="brokerage paid (reduces capital proceeds)")
    sl.add_argument("--order", default="fifo", choices=SELL_ORDERS,
                    help="which parcels to sell first: fifo (oldest first, default) or min-tax "
                         "(the parcels giving the smallest taxable gain, counting the CGT discount)")
    sl.add_argument("--parcel", help="sell from one specific parcel (ID or its first 8 characters)")

    ls = sub.add_parser("list", help="show parcels")
    ls.add_argument("--all", action="store_true", help="include sold parcels")

    cg = sub.add_parser("cgt", help="realised capital gains per financial year")
    cg.add_argument("--fy", help="one financial year, e.g. 2025-26")

    dl = sub.add_parser("delete", help="remove a parcel entered by mistake")
    dl.add_argument("parcel_id")
    return parser.parse_args(argv)


def cmd_add(session, args) -> None:
    parcel = add_parcel(session, args.asx_code, args.units, args.price, args.date, args.brokerage,
                        args.method, args.broker, args.notes)
    session.commit()
    eligible = cgt.discount_eligible_from(parcel.buy_date)
    print(f"Added {parcel.asx_code} parcel {str(parcel.holding_id)[:8]}: {_units(parcel.units)} units @ "
          f"{parcel.buy_price} on {parcel.buy_date}, cost base "
          f"${cgt.cost_base(parcel.units, parcel.buy_price, parcel.buy_brokerage):,.2f}. "
          f"CGT discount applies to sales from {eligible:%d %b %Y}.")


def cmd_sell(session, args) -> None:
    sold = sell(session, args.asx_code, args.units, args.price, args.date, args.brokerage, args.order, args.parcel)
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
    today = date.today()
    parcels = open_parcels(session)
    prices = latest_prices(session, {p.asx_code for p in parcels})

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
            "cgt_discount": "Y" if today >= eligible_from else f"from {eligible_from}",
            "broker": p.broker,
        })

    if rows:
        print("Open parcels")
        print(tabulate(rows, headers="keys", floatfmt=".2f", tablefmt="simple"))
        print(f"\nTotal cost base ${total_cost:,.2f}, market value ${total_value:,.2f} "
              f"(parcels with a known price), unrealised gain ${total_value - total_cost:,.2f}")
    else:
        print("No open parcels. Add one with: python portfolio.py add <CODE> --units N --price P --date YYYY-MM-DD")

    if args.all:
        sold = []
        for p in sold_parcels(session):
            g = realised_gain(p)
            sold.append({"parcel": str(p.holding_id)[:8], "asx_code": p.asx_code, "units": _units(p.units),
                         "bought": p.buy_date, "sold": p.sell_date, "cost_base": g.cost_base,
                         "proceeds": g.proceeds, "gain": g.gain, "cgt_discount": "Y" if g.discount_eligible else "N",
                         "fy": cgt.financial_year(p.sell_date)})
        if sold:
            print("\nSold parcels")
            print(tabulate(sold, headers="keys", floatfmt=".2f", tablefmt="simple"))


def cmd_cgt(session, args) -> None:
    by_fy: dict[str, list[cgt.RealisedGain]] = defaultdict(list)
    for p in sold_parcels(session):
        by_fy[cgt.financial_year(p.sell_date)].append(realised_gain(p))
    years = [args.fy] if args.fy else sorted(by_fy)
    if not any(by_fy.get(fy) for fy in years):
        print("No realised sales" + (f" in {args.fy}." if args.fy else " recorded yet."))
        return

    for fy in years:
        gains = by_fy.get(fy, [])
        if not gains:
            continue
        print(f"\nFinancial year {fy}")
        print(tabulate([{"asx_code": g.asx_code, "units": _units(g.units), "bought": g.buy_date, "sold": g.sell_date,
                         "cost_base": g.cost_base, "proceeds": g.proceeds, "gain": g.gain,
                         "cgt_discount": "Y" if g.discount_eligible else "N"} for g in gains],
                       headers="keys", floatfmt=".2f", tablefmt="simple"))
        s = cgt.summarise(fy, gains)
        print(f"  Gains eligible for the discount:  ${s.discountable_gains:,.2f}")
        print(f"  Gains not eligible:               ${s.non_discountable_gains:,.2f}")
        print(f"  Capital losses:                   ${s.capital_losses:,.2f}")
        print(f"  Net capital gain (after losses, then 50% discount): ${s.net_capital_gain:,.2f}")
        if s.unused_losses:
            print(f"  Losses to carry forward:          ${s.unused_losses:,.2f}")
    print(f"\n{DISCLAIMER} Losses are applied to non-discountable gains first, the order most favourable to "
          "an individual. The 50% discount is for individuals and trusts (super funds 33 1/3%, companies nil).")


def cmd_delete(session, args) -> None:
    parcel = delete_parcel(session, args.parcel_id)
    session.commit()
    print(f"Deleted {parcel.asx_code} parcel {str(parcel.holding_id)[:8]} "
          f"({_units(parcel.units)} units bought {parcel.buy_date}).")


COMMANDS = {"add": cmd_add, "sell": cmd_sell, "list": cmd_list, "cgt": cmd_cgt, "delete": cmd_delete}


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
