"""Portfolio figures for the web GUI (gui.py): each portfolio valued at
the latest close, its positions, parcels and CGT by financial year. The
same arithmetic as portfolio.py (src/portfolio/cgt.py, holdings.py), only
shaped for the browser. Shares and ETFs are kept in separate sections with
their own subtotals (docs/AS_BUILT.md §26)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, text

from src.models import Company, Holding, Portfolio
from src.portfolio import cgt
from src.portfolio.holdings import (discount_rate, list_portfolios, open_parcels, owned_portfolio_ids, realised_gain,
                                    sold_parcels)

ZERO = Decimal("0")


def two_latest_closes(session, codes: set[str]) -> dict[str, list[Decimal]]:
    """Latest close first, then the one before, for each code with prices."""
    if not codes:
        return {}
    rows = session.execute(text("""
        SELECT asx_code, close_price FROM (
            SELECT c.asx_code, p.close_price, p.price_date,
                   ROW_NUMBER() OVER (PARTITION BY p.company_id ORDER BY p.price_date DESC) AS n
            FROM daily_prices p JOIN companies c ON c.company_id = p.company_id
            WHERE c.asx_code = ANY(:codes)
        ) ranked WHERE n <= 2 ORDER BY asx_code, price_date DESC
    """), {"codes": sorted(codes)}).all()
    out: dict[str, list[Decimal]] = {}
    for code, close in rows:
        out.setdefault(code, []).append(close)
    return out


def company_names(session, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    return dict(session.execute(
        select(Company.asx_code, Company.company_name).where(Company.asx_code.in_(codes))
    ).all())


def security_types(session, codes: set[str]) -> dict[str, str]:
    """SHARE or ETF for each code Sift knows; anything else counts as a share."""
    if not codes:
        return {}
    return dict(session.execute(
        select(Company.asx_code, Company.security_type).where(Company.asx_code.in_(codes))
    ).all())


ETF_FIELDS = ("category", "return_1y", "distribution_yield_12m", "mer_percent", "premium_now")
KINDS = ("SHARE", "ETF", "LIC")


def with_types(lines: list[dict], types: dict[str, str], funds: dict[str, dict]) -> list[dict]:
    """Mark each line SHARE, ETF or LIC; an ETF or LIC line also gets its
    category, 1-year return, yield, fee and (LICs) premium or discount to
    NTA, which its section shows instead of an action."""
    for line in lines:
        kind = types.get(line["asx_code"], "SHARE")
        line["security_type"] = kind
        if kind != "SHARE":
            fund = funds.get(line["asx_code"], {})
            line.update({k: fund.get(k) for k in ETF_FIELDS})
    return lines


def sections(lines: list[dict]) -> dict[str, dict]:
    """Totals for the shares, the ETFs and the LICs separately."""
    out = {}
    for kind in KINDS:
        mine = [line for line in lines if line.get("security_type", "SHARE") == kind]
        out[kind] = totals(mine) | {"holdings": len(mine)}
    return out


def portfolio_info(portfolio: Portfolio) -> dict:
    return {"portfolio_id": str(portfolio.portfolio_id), "name": portfolio.name, "tax_type": portfolio.tax_type,
            "tax_type_label": cgt.TAX_TYPE_LABELS[portfolio.tax_type], "discount_rate": discount_rate(portfolio),
            "archived": portfolio.is_archived, "archived_at": portfolio.archived_at}


def tax_types() -> list[dict]:
    return [{"tax_type": t, "label": cgt.TAX_TYPE_LABELS[t], "discount_rate": cgt.DISCOUNT_RATES[t]}
            for t in cgt.TAX_TYPES]


def positions(parcels: list[Holding], closes: dict[str, list[Decimal]], names: dict[str, str],
              rows_by_code: dict[str, dict], today: date, no_discount: set = frozenset()) -> list[dict]:
    """One line per company: units, cost base, value at the latest close,
    gain, the day's change and the screener's suggested action. Parcels in
    a portfolio listed in `no_discount` (a company's) never wait for a CGT
    discount date."""
    by_code: dict[str, list[Holding]] = defaultdict(list)
    for p in parcels:
        by_code[p.asx_code].append(p)
    out = []
    for code, group in sorted(by_code.items()):
        units = sum((p.units for p in group), ZERO)
        cost = sum((cgt.cost_base(p.units, p.buy_price, p.buy_brokerage) for p in group), ZERO)
        last = closes.get(code, [])
        price = last[0] if last else None
        value = cgt.to_cents(units * price) if price is not None else None
        pending = [p for p in group
                   if p.portfolio_id not in no_discount and not cgt.is_discount_eligible(p.buy_date, today)]
        next_date = min((cgt.discount_eligible_from(p.buy_date) for p in pending), default=None)
        row = rows_by_code.get(code)
        out.append({
            "asx_code": code, "company_name": names.get(code), "units": units, "cost_base": cost,
            "price": price, "value": value, "gain": value - cost if value is not None else None,
            "day_change": cgt.to_cents(units * (last[0] - last[1])) if len(last) == 2 else None,
            "action": row["action"] if row else None, "action_reason": row["action_reason"] if row else None,
            "valuation_status": row["valuation_status"] if row else None,
            "next_discount_date": next_date,
            "units_pending_discount": sum((p.units for p in pending
                                           if cgt.discount_eligible_from(p.buy_date) == next_date), ZERO),
        })
    return out


def totals(lines: list[dict]) -> dict:
    priced = [line for line in lines if line["value"] is not None]
    value = sum((line["value"] for line in priced), ZERO)
    cost = sum((line["cost_base"] for line in priced), ZERO)
    day = [line["day_change"] for line in priced if line["day_change"] is not None]
    return {
        "value": value if priced else None,
        "cost_base": cost if priced else None,
        "gain": value - cost if priced else None,
        "day_change": sum(day, ZERO) if day else None,
        "unpriced": [line["asx_code"] for line in lines if line["value"] is None],
    }


def no_discount_ids(session) -> set:
    return {p.portfolio_id for p in list_portfolios(session) if discount_rate(p) == 0}


def combined(session, rows_by_code: dict[str, dict], today: date, etfs: dict[str, dict] | None = None) -> dict:
    """Every open holding across all portfolios, one line per company or ETF."""
    parcels = open_parcels(session)
    codes = {p.asx_code for p in parcels}
    lines = positions(parcels, two_latest_closes(session, codes), company_names(session, codes), rows_by_code,
                      today, no_discount_ids(session))
    with_types(lines, security_types(session, codes), etfs or {})
    return {"holdings": lines, "sections": sections(lines)} | totals(lines)


def portfolio_summaries(session, rows_by_code: dict[str, dict], today: date) -> list[dict]:
    """Every portfolio, active first, with its totals."""
    portfolios = list_portfolios(session)
    parcels = open_parcels(session)
    closes = two_latest_closes(session, {p.asx_code for p in parcels})
    types = security_types(session, {p.asx_code for p in parcels})
    sales = dict(session.execute(
        select(Holding.portfolio_id, func.count())
        .where(Holding.sell_date.is_not(None), Holding.portfolio_id.in_(owned_portfolio_ids(session)))
        .group_by(Holding.portfolio_id)
    ).all())
    out = []
    for portfolio in portfolios:
        mine = [p for p in parcels if p.portfolio_id == portfolio.portfolio_id]
        lines = with_types(positions(mine, closes, {}, rows_by_code, today), types, {})
        out.append(portfolio_info(portfolio) | totals(lines) | {"sections": sections(lines)} | {
            "holdings": len(lines), "open_parcels": len(mine), "sales": sales.get(portfolio.portfolio_id, 0)})
    return out


def _parcel(p: Holding, closes: dict[str, list[Decimal]], gets_discount: bool) -> dict:
    cost = cgt.cost_base(p.units, p.buy_price, p.buy_brokerage)
    last = closes.get(p.asx_code, [])
    value = cgt.to_cents(p.units * last[0]) if last else None
    return {"holding_id": str(p.holding_id), "short_id": str(p.holding_id)[:8], "asx_code": p.asx_code,
            "units": p.units, "method": p.acquisition_method, "buy_date": p.buy_date, "buy_price": p.buy_price,
            "buy_brokerage": p.buy_brokerage, "cost_base": cost, "value": value,
            "gain": value - cost if value is not None else None,
            "discount_from": cgt.discount_eligible_from(p.buy_date) if gets_discount else None,
            "broker": p.broker, "notes": p.notes}


def _sale(p: Holding, gets_discount: bool) -> dict:
    g = realised_gain(p)
    return {"holding_id": str(p.holding_id), "short_id": str(p.holding_id)[:8], "asx_code": p.asx_code,
            "units": p.units, "buy_date": p.buy_date, "sell_date": p.sell_date, "sell_price": p.sell_price,
            "cost_base": g.cost_base, "proceeds": g.proceeds, "gain": g.gain,
            "discount_eligible": g.discount_eligible and gets_discount,
            "financial_year": cgt.financial_year(p.sell_date)}


def cgt_by_year(sold: list[Holding], rate: Decimal) -> list[dict]:
    """The portfolio's CGT summary for each financial year with a sale, newest first."""
    by_fy: dict[str, list[cgt.RealisedGain]] = defaultdict(list)
    for p in sold:
        by_fy[cgt.financial_year(p.sell_date)].append(realised_gain(p))
    out = []
    for fy in sorted(by_fy, reverse=True):
        s = cgt.summarise(fy, by_fy[fy], rate)
        out.append({"financial_year": fy, "sales": len(by_fy[fy]), "discountable_gains": s.discountable_gains,
                    "non_discountable_gains": s.non_discountable_gains, "capital_losses": s.capital_losses,
                    "net_capital_gain": s.net_capital_gain, "unused_losses": s.unused_losses})
    return out


def portfolio_detail(session, portfolio: Portfolio, rows_by_code: dict[str, dict], today: date,
                     etfs: dict[str, dict] | None = None) -> dict:
    rate = discount_rate(portfolio)
    gets_discount = rate > 0
    parcels = open_parcels(session, portfolio_id=portfolio.portfolio_id)
    sold = sold_parcels(session, portfolio.portfolio_id)
    codes = {p.asx_code for p in parcels} | {p.asx_code for p in sold}
    closes = two_latest_closes(session, {p.asx_code for p in parcels})
    lines = positions(parcels, closes, company_names(session, codes), rows_by_code, today,
                      set() if gets_discount else {portfolio.portfolio_id})
    types = security_types(session, codes)
    with_types(lines, types, etfs or {})
    etf_codes = {c for c, t in types.items() if t == "ETF"}
    lic_codes = {c for c, t in types.items() if t == "LIC"}
    return {
        "portfolio": portfolio_info(portfolio),
        "totals": totals(lines),
        "sections": sections(lines),
        "etf_codes": sorted(etf_codes),
        "lic_codes": sorted(lic_codes),
        "positions": lines,
        "parcels": [_parcel(p, closes, gets_discount) for p in parcels],
        "sales": [_sale(p, gets_discount) for p in reversed(sold)],
        "cgt": cgt_by_year(sold, rate),
        "tax_types": tax_types(),
    }
