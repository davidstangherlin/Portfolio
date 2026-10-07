"""ETF performance from Sift's own price and distribution history
(docs/AS_BUILT.md §25).

Total return: buy one unit at the close on the start date, reinvest each
distribution at the close on its ex-date (or the next close, if the ex-date
has none), and value the units at the end date's close. Periods of more
than a year are annualised over their nominal years (3, 5, 10); since
first price is annualised over its actual length once it's over a year.

A period is only measured when there's a close within STALE_DAYS of its
start, so an ETF younger than the period, or with a gap where its start
should be, shows nothing rather than a shorter period's return.

Closes are the prices actually traded (split-adjusted only), and
distributions are added in here; see YahooClient.get_price_history().
"""

from __future__ import annotations

import bisect
import calendar
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.ingestion.dividend_history import add_months
from src.models import Company, DailyPrice, DividendPayment, EtfMonthly, EtfPerformance

logger = logging.getLogger(__name__)

PERIODS = (("return_1m", 1), ("return_3m", 3), ("return_6m", 6), ("return_1y", 12),
           ("return_3y", 36), ("return_5y", 60), ("return_10y", 120))
STALE_DAYS = 10
DAYS_PER_YEAR = 365.25
CENT = Decimal("0.01")
JUMP_LIMIT = 0.4         # a one-day move beyond 40% that stays is a data fault, not a market move
JUMP_MIN_PRICE = 0.10    # under 10 cents one price step is several percent, so big daily moves are real
JUMP_WINDOW = 10         # closes either side compared, so a spike that reverses isn't counted
LISTING_MATCH_DAYS = 31  # prices starting within this of the listing date: since-inception is comparable


@dataclass
class History:
    dates: list[date]
    closes: list[float]
    distributions: list[tuple[date, float]]  # (ex-date, cash per unit), oldest first

    def close_on_or_before(self, day: date) -> tuple[date, float] | None:
        i = bisect.bisect_right(self.dates, day) - 1
        return (self.dates[i], self.closes[i]) if i >= 0 else None

    def close_on_or_after(self, day: date, limit: date) -> float | None:
        i = bisect.bisect_left(self.dates, day)
        return self.closes[i] if i < len(self.dates) and self.dates[i] <= limit else None


def growth(h: History, start: date, end: date) -> float | None:
    """Value at `end` of one unit bought at the close on or before
    `start`, distributions reinvested, as a multiple (1.10 = +10%). None
    without a close within STALE_DAYS of either date."""
    first, last = h.close_on_or_before(start), h.close_on_or_before(end)
    if not first or not last or (start - first[0]).days > STALE_DAYS or (end - last[0]).days > STALE_DAYS:
        return None
    if first[1] <= 0 or last[0] <= first[0]:
        return None
    units, cash = 1.0, 0.0
    for ex_date, amount in h.distributions:
        if first[0] < ex_date <= last[0]:
            price = h.close_on_or_after(ex_date, last[0])
            if price and price > 0:
                units *= 1 + amount / price
            else:
                cash += amount * units
    return (units * last[1] + cash) / first[1]


def growth_index(h: History) -> list[tuple[date, float]]:
    """The value each day of one unit bought at the first close, with
    every distribution reinvested the way growth() does it. Divide by the
    value on any start date to chart growth from that date."""
    out, units, i = [], 1.0, 0
    dists = [(d, a) for d, a in h.distributions if h.dates and d > h.dates[0]]
    for day, close in zip(h.dates, h.closes):
        while i < len(dists) and dists[i][0] <= day:
            if close > 0:
                units *= 1 + dists[i][1] / close
            i += 1
        out.append((day, units * close))
    return out


def _pct(multiple: float | None, years: float | None = None) -> Decimal | None:
    if multiple is None or multiple <= 0:
        return None
    rate = multiple ** (1 / years) - 1 if years and years > 1 else multiple - 1
    return Decimal(str(rate * 100)).quantize(CENT)


def returns_as_at(h: History, as_at: date) -> dict:
    """Every period's total return, in percent, as at `as_at`."""
    out = {}
    for key, months in PERIODS:
        out[key] = _pct(growth(h, add_months(as_at, -months), as_at), months / 12 if months > 12 else None)
    if h.dates:
        last = h.close_on_or_before(as_at)
        years = (last[0] - h.dates[0]).days / DAYS_PER_YEAR if last else 0
        out["return_since_inception"] = _pct(growth(h, h.dates[0], as_at), years) if years > 0 else None
    return out


def price_jump(h: History) -> tuple[date, Decimal] | None:
    """The latest one-day move beyond JUMP_LIMIT that looks like a data
    fault, as (date, percent): an unadjusted split or consolidation, or a
    currency change in the feed, which shifts the price level for good and
    makes every return measured across it wrong. Not counted (§26.1):
    - a price under JUMP_MIN_PRICE on either side (8IH at about a cent
      moves 50% on a few ticks);
    - a move that doesn't stay: the median of the JUMP_WINDOW closes after
      it must also differ from the median of those before by JUMP_LIMIT;
    - a drop that a distribution paid that day explains."""
    paid = dict(h.distributions)
    for i in range(len(h.closes) - 1, 0, -1):
        before, after = h.closes[i - 1], h.closes[i]
        if before <= 0 or abs(after / before - 1) <= JUMP_LIMIT or min(before, after) < JUMP_MIN_PRICE:
            continue
        if h.dates[i] in paid and abs((after + paid[h.dates[i]]) / before - 1) <= JUMP_LIMIT:
            continue
        prior = sorted(h.closes[max(0, i - JUMP_WINDOW):i])
        later = sorted(h.closes[i:i + JUMP_WINDOW])
        mid = lambda xs: xs[len(xs) // 2]  # noqa: E731
        if mid(prior) > 0 and abs(mid(later) / mid(prior) - 1) > JUMP_LIMIT:
            return h.dates[i], Decimal(str((after / before - 1) * 100)).quantize(CENT)
    return None


def report_checks(h: History, report: EtfMonthly) -> dict[str, list[float]]:
    """Each period's return measured by Sift to the report's month end,
    beside the ASX report's figure: {period: [sift, asx]}, for the periods
    both have. Since-inception only when Sift's prices start near the
    listing date, since the ASX measures it from listing."""
    end = month_end(report.report_month)
    out = {}
    for key, months in PERIODS:
        theirs = getattr(report, key)
        ours = _pct(growth(h, add_months(end, -months), end), months / 12 if months > 12 else None)
        if theirs is not None and ours is not None:
            out[key] = [float(ours), float(theirs)]
    if report.return_since_inception is not None and report.listing_date and h.dates \
            and abs((h.dates[0] - report.listing_date).days) <= LISTING_MATCH_DAYS:
        last = h.close_on_or_before(end)
        years = (last[0] - h.dates[0]).days / DAYS_PER_YEAR if last else 0
        ours = _pct(growth(h, h.dates[0], end), years) if years > 0 else None
        if ours is not None:
            out["return_since_inception"] = [float(ours), float(report.return_since_inception)]
    return out


def trailing_distributions(h: History, as_at: date) -> tuple[Decimal | None, Decimal | None]:
    """Cash distributions per unit with ex-dates in the 12 months to
    `as_at`, and that as a percent of the close (the trailing yield)."""
    last = h.close_on_or_before(as_at)
    if not last or (as_at - last[0]).days > STALE_DAYS:
        return None, None
    since = add_months(as_at, -12)
    total = sum(a for d, a in h.distributions if since < d <= as_at)
    yield_pct = Decimal(str(total / last[1] * 100)).quantize(CENT) if last[1] > 0 else None
    return Decimal(str(total)).quantize(Decimal("0.0001")), yield_pct


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def load_history(session, company_id) -> History:
    prices = session.execute(select(DailyPrice.price_date, DailyPrice.close_price)
                             .where(DailyPrice.company_id == company_id).order_by(DailyPrice.price_date)).all()
    dists = session.execute(select(DividendPayment.ex_date, DividendPayment.amount)
                            .where(DividendPayment.company_id == company_id).order_by(DividendPayment.ex_date)).all()
    return History([p[0] for p in prices], [float(p[1]) for p in prices], [(d, float(a)) for d, a in dists])


def update_performance(session, as_at: date | None = None) -> int:
    """Recalculate etf_performance for every active ETF as at the latest
    price date (or `as_at`). Also measures each ETF's 1-year return at the
    month end of its latest ASX report, beside the report's own figure.
    Returns the number of ETFs written."""
    if as_at is None:
        as_at = session.execute(select(DailyPrice.price_date).join(Company)
                                .where(Company.security_type.in_(("ETF", "LIC")))
                                .order_by(DailyPrice.price_date.desc()).limit(1)).scalar_one_or_none()
        if as_at is None:
            return 0
    etfs = session.execute(select(Company.company_id, Company.asx_code).where(
        Company.security_type.in_(("ETF", "LIC")), Company.is_active.is_(True)).order_by(Company.asx_code)).all()
    written = 0
    for company_id, code in etfs:
        h = load_history(session, company_id)
        if not h.dates:
            continue
        values = returns_as_at(h, as_at)
        values["distributions_12m"], values["distribution_yield_12m"] = trailing_distributions(h, as_at)
        report = session.execute(select(EtfMonthly).where(EtfMonthly.company_id == company_id)
                                 .order_by(EtfMonthly.report_month.desc()).limit(1)).scalar_one_or_none()
        check = {"check_month": None, "check_return_1y": None, "reported_return_1y": None, "report_checks": None}
        if report is not None:
            checks = report_checks(h, report)
            one_year = checks.get("return_1y")
            check = {"check_month": report.report_month, "report_checks": checks or None,
                     "check_return_1y": Decimal(str(one_year[0])) if one_year else None,
                     "reported_return_1y": report.return_1y if one_year else None}
        jump = price_jump(h)
        values |= check | {"company_id": company_id, "as_of_date": as_at, "first_price_date": h.dates[0],
                           "price_jump_date": jump[0] if jump else None, "price_jump_percent": jump[1] if jump else None}
        stmt = insert(EtfPerformance).values(**values)
        session.execute(stmt.on_conflict_do_update(
            index_elements=[EtfPerformance.company_id],
            set_={k: stmt.excluded[k] for k in values if k != "company_id"} | {"updated_at": func.current_timestamp()}))
        written += 1
    return written


def report_differences(session, threshold: Decimal = Decimal("2")) -> list[tuple[str, Decimal, Decimal]]:
    """ETFs whose 1-year return at the report's month end differs from
    the ASX report's by more than `threshold` points: a sign of a missing
    distribution, a bad price, or the report using a different basis."""
    rows = session.execute(select(Company.asx_code, EtfPerformance.check_return_1y, EtfPerformance.reported_return_1y)
                           .join(Company).where(EtfPerformance.check_return_1y.is_not(None),
                                                EtfPerformance.reported_return_1y.is_not(None))).all()
    return sorted(((c, ours, theirs) for c, ours, theirs in rows if abs(ours - theirs) > threshold),
                  key=lambda r: -abs(r[1] - r[2]))


def price_jumps(session) -> list[tuple[str, date, Decimal]]:
    """ETFs and LICs whose price history has a one-day jump beyond
    JUMP_LIMIT (see price_jump()), newest first, for the nightly log."""
    rows = session.execute(select(Company.asx_code, EtfPerformance.price_jump_date, EtfPerformance.price_jump_percent)
                           .join(Company).where(EtfPerformance.price_jump_date.is_not(None))
                           .order_by(EtfPerformance.price_jump_date.desc())).all()
    return [tuple(r) for r in rows]
