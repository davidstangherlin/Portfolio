"""ETF figures for the web GUI (docs/AS_BUILT.md §26): the ETF screener's
rows, and everything an ETF's own page shows. ETFs are presented apart
from shares throughout Sift, under their own heading, and judged on cost,
size, distributions and performance rather than valuation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from src.etf.performance import History, growth_index, load_history
from src.ingestion.dividend_history import add_months
from src.portfolio.holdings import position_summaries

RETURN_KEYS = ("return_1m", "return_3m", "return_6m", "return_1y", "return_3y", "return_5y", "return_10y",
               "return_since_inception")
REPORT_GAP = Decimal("2")       # points between Sift's 1-year return and the ASX's before it's flagged
UNCATEGORISED = "Uncategorised"
PRICE_DAYS = 365
DISTRIBUTION_YEARS = 10

_ROWS = text("""
    WITH latest AS (
        SELECT DISTINCT ON (company_id) * FROM etf_monthly ORDER BY company_id, report_month DESC
    ), closes AS (
        SELECT company_id, price_date, close_price,
               ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY price_date DESC) AS n
        FROM daily_prices WHERE company_id IN (SELECT company_id FROM companies WHERE security_type = 'ETF')
    )
    SELECT c.company_id, c.asx_code, COALESCE(m.fund_name, c.company_name) AS company_name,
           m.issuer, m.product_type, m.category, m.sub_category, m.benchmark, m.mer_percent, m.fum_aud,
           m.avg_spread_percent, m.net_flows_aud, m.value_traded_aud, m.distribution_frequency, m.listing_date,
           m.report_month, m.return_1m AS asx_return_1m, m.return_3m AS asx_return_3m,
           m.return_6m AS asx_return_6m, m.return_1y AS asx_return_1y, m.return_3y AS asx_return_3y,
           m.return_5y AS asx_return_5y, m.return_10y AS asx_return_10y,
           m.return_since_inception AS asx_return_since_inception, m.distribution_yield AS asx_distribution_yield,
           m.raw ? 'Invests in other ETFs' AS fund_of_funds,
           p1.close_price AS current_price, p1.price_date, p2.close_price AS previous_close,
           f.as_of_date, f.first_price_date, f.return_1m, f.return_3m, f.return_6m, f.return_1y, f.return_3y,
           f.return_5y, f.return_10y, f.return_since_inception, f.distributions_12m, f.distribution_yield_12m,
           f.check_month, f.check_return_1y, f.reported_return_1y
    FROM companies c
    LEFT JOIN latest m ON m.company_id = c.company_id
    LEFT JOIN closes p1 ON p1.company_id = c.company_id AND p1.n = 1
    LEFT JOIN closes p2 ON p2.company_id = c.company_id AND p2.n = 2
    LEFT JOIN etf_performance f ON f.company_id = c.company_id
    WHERE c.security_type = 'ETF' AND c.is_active = TRUE
    ORDER BY c.asx_code
""")


def etf_rows(session, today: date, watched: dict[str, list[str]] | None = None) -> list[dict]:
    """One row per active ETF: fund facts from its latest ASX report, Sift's
    performance, the latest close and day's move, and whether you hold or
    watch it."""
    positions = position_summaries(session, today)
    watched = watched or {}
    out = []
    for r in session.execute(_ROWS).mappings():
        row = dict(r)
        row["category"] = row["category"] or row["product_type"] or UNCATEGORISED
        before, now = row.pop("previous_close"), row["current_price"]
        row["day_change_percent"] = ((now - before) / before * 100).quantize(Decimal("0.01")) if before and now else None
        gap = (row["check_return_1y"] - row["reported_return_1y"]) if row["check_return_1y"] is not None \
            and row["reported_return_1y"] is not None else None
        row["report_gap"] = gap is not None and abs(gap) > REPORT_GAP
        position = positions.get(row["asx_code"])
        row["held"] = position.units if position else None
        row["watchlists"] = watched.get(row["asx_code"], [])
        row["security_type"] = "ETF"
        out.append(row)
    return out


def category_averages(rows: list[dict]) -> dict[str, dict]:
    """For each category: the number of ETFs, and the average of each
    return, fee and yield over the ETFs that have one."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["category"]].append(r)
    out = {}
    for category, members in groups.items():
        avg = {"category": category, "etfs": len(members)}
        for key in (*RETURN_KEYS, "mer_percent", "distribution_yield_12m"):
            values = [m[key] for m in members if m[key] is not None]
            avg[key] = (sum(values, Decimal("0")) / len(values)).quantize(Decimal("0.01")) if values else None
            avg[f"{key}_n"] = len(values)
        out[category] = avg
    return out


def default_reference(row: dict, rows: list[dict]) -> dict | None:
    """The largest other fund in the same category, or failing that the
    largest other fund: a sensible yardstick until you pick one."""
    others = [r for r in rows if r["asx_code"] != row["asx_code"]]
    size = lambda r: r["fum_aud"] or Decimal("0")  # noqa: E731
    same = [r for r in others if r["category"] == row["category"]]
    pool = same or others
    return max(pool, key=size) if pool else None


def weekly(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """The last point of each week, and the very last point."""
    out = []
    for i, (day, value) in enumerate(points):
        nxt = points[i + 1][0] if i + 1 < len(points) else None
        if nxt is None or nxt.isocalendar()[:2] != day.isocalendar()[:2]:
            out.append((day, round(value, 4)))
    return out


def _fy(day: date) -> int:
    """The financial year a date falls in, by its ending year (FY26 = 1 Jul 2025 to 30 Jun 2026)."""
    return day.year + 1 if day.month >= 7 else day.year


def distributions_by_year(h: History, today: date) -> list[dict]:
    """Cash distributions per unit for each of the last ten financial
    years, oldest first, including years with none (once the fund was
    trading)."""
    last_fy = _fy(today)
    first_fy = max(last_fy - DISTRIBUTION_YEARS + 1, _fy(h.dates[0]) if h.dates else last_fy)
    totals = {fy: 0.0 for fy in range(first_fy, last_fy + 1)}
    counts = dict.fromkeys(totals, 0)
    for day, amount in h.distributions:
        fy = _fy(day)
        if fy in totals:
            totals[fy] += amount
            counts[fy] += 1
    return [{"financial_year": f"FY{str(fy)[-2:]}", "amount": round(totals[fy], 4), "payments": counts[fy],
             "partial": fy == last_fy} for fy in totals]


def monthly_history(session, company_id) -> list[dict]:
    return [dict(r) for r in session.execute(text("""
        SELECT report_month, fum_aud, mer_percent, net_flows_aud, avg_spread_percent, return_1y
        FROM etf_monthly WHERE company_id = :c ORDER BY report_month
    """), {"c": company_id}).mappings()]


def etf_detail(session, code: str, today: date, compare: str | None = None,
               watched: dict[str, list[str]] | None = None) -> dict | None:
    """Everything the ETF page shows, or None if `code` isn't an active ETF."""
    rows = etf_rows(session, today, watched)
    by_code = {r["asx_code"]: r for r in rows}
    row = by_code.get(code)
    if row is None:
        return None
    averages = category_averages(rows)
    reference = by_code.get((compare or "").upper()) if compare and compare.upper() != code else None
    reference = reference or default_reference(row, rows)

    h = load_history(session, row["company_id"])
    since = add_months(today, -12)
    prices = [(d, c) for d, c in zip(h.dates, h.closes) if d >= since]
    ref_growth = weekly(growth_index(load_history(session, reference["company_id"]))) if reference else []
    position = position_summaries(session, today).get(code)
    options = sorted(rows, key=lambda r: (r["category"] != row["category"], -(r["fum_aud"] or 0), r["asx_code"]))
    return {
        "etf": row,
        "category_average": averages.get(row["category"]),
        "reference": reference,
        "reference_options": [{"asx_code": r["asx_code"], "company_name": r["company_name"], "category": r["category"]}
                              for r in options if r["asx_code"] != code],
        "growth": {"etf": weekly(growth_index(h)), "reference": ref_growth},
        "prices": prices,
        "distributions": [(d, a) for d, a in h.distributions if d >= since],
        "recent_distributions": [{"ex_date": d, "amount": a} for d, a in h.distributions[-12:]][::-1],
        "distributions_by_year": distributions_by_year(h, today) if h.dates else [],
        "monthly": monthly_history(session, row["company_id"]),
        "position": None if position is None else {"units": position.units, "cost_base": position.cost_base,
                                                    "next_discount_date": position.next_discount_date},
        "report_gap_points": REPORT_GAP,
    }


def screener_payload(session, today: date, watched: dict[str, list[str]], watchlist_names: list[str]) -> dict:
    rows = etf_rows(session, today, watched)
    return {
        "rows": rows,
        "categories": sorted({r["category"] for r in rows}),
        "issuers": sorted({r["issuer"] for r in rows if r["issuer"]}),
        "category_averages": category_averages(rows),
        "as_of": max((r["as_of_date"] for r in rows if r["as_of_date"]), default=None),
        "report_month": max((r["report_month"] for r in rows if r["report_month"]), default=None),
        "watchlists": [{"name": n} for n in watchlist_names],
    }
