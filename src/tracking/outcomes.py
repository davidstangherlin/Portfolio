"""Scoring signals against what happened next (docs/AS_BUILT.md §21).

Run nightly after signals are recorded (src/tracking/score_signals.py):

1. fill_outcomes(): for each scorecard signal whose 1, 3, 6 or 12 months
   have passed, the total return including dividends, the same-night
   universe average (benchmark) and the excess return. Scorecard signals
   are each company's first signal of each month (the monthly cohort, which
   feeds the scorecard) and any night its action changed (tracked
   separately, for "what happened after it changed").
2. refresh_monthly(): rebuild track_record_monthly for every month that
   still has detail rows. Months whose detail has been deleted keep their
   summary rows untouched, forever.
3. prune(): delete daily detail older than RETENTION_MONTHS whole months.
   It runs after the summary in the same transaction, so nothing is
   deleted before it's summarised.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from src.ingestion.dividend_history import add_months
from src.tracking.signals import HORIZONS_MONTHS

RETENTION_MONTHS = 14       # 12-month horizon plus two months to finish scoring it
STALE_PRICE_DAYS = 10       # no close this close to the horizon: treated as delisted, scored at its last price
MAX_PERCENT = Decimal("99999999")  # beyond the column size: stored as blank rather than overflowing
HUNDRED = Decimal("100")
CENT = Decimal("0.01")


def _pct(value: Decimal | None) -> Decimal | None:
    if value is None or abs(value) >= MAX_PERCENT:
        return None
    return value.quantize(CENT)


def total_return(start_price: Decimal, end_price: Decimal, dividends: Decimal) -> Decimal | None:
    """Percent: price change plus every dividend paid in the period, on the signal price."""
    if not start_price or start_price <= 0:
        return None
    return (end_price + dividends - start_price) / start_price * HUNDRED


def gap_closed(start_price: Decimal, end_price: Decimal, estimated_value: Decimal | None) -> Decimal | None:
    """Percent of the distance from price up to estimated value that the
    price covered. Only for signals priced below their estimate."""
    if estimated_value is None or estimated_value <= start_price:
        return None
    return (end_price - start_price) / (estimated_value - start_price) * HUNDRED


_SCORECARD_DUE = text("""
    WITH flagged AS (
        SELECT s.company_id, s.snapshot_date, s.action, s.held,
               ROW_NUMBER() OVER (PARTITION BY s.company_id, date_trunc('month', s.snapshot_date)
                                  ORDER BY s.snapshot_date) = 1 AS is_cohort,
               LAG(s.action) OVER w AS prev_action,
               LAG(s.held) OVER w AS prev_held
        FROM signal_snapshots s
        WINDOW w AS (PARTITION BY s.company_id ORDER BY s.snapshot_date)
    ), scorecard AS (
        SELECT company_id, snapshot_date, is_cohort,
               COALESCE(prev_action <> action AND prev_held = held, FALSE) AS is_change
        FROM flagged
    )
    SELECT c.company_id, c.snapshot_date, c.is_cohort, c.is_change, h.m AS horizon
    FROM scorecard c CROSS JOIN (VALUES (1), (3), (6), (12)) AS h(m)
    WHERE (c.is_cohort OR c.is_change)
      AND (c.snapshot_date + make_interval(months => h.m))::date <= :market_date
      AND NOT EXISTS (SELECT 1 FROM signal_outcomes o WHERE o.company_id = c.company_id
                      AND o.snapshot_date = c.snapshot_date AND o.horizon_months = h.m)
""")

_NIGHT_RESULTS = text("""
    SELECT s.company_id, s.price, s.estimated_value, e.price_date AS end_date, e.close_price AS end_price,
           COALESCE((SELECT SUM(d.amount) FROM dividend_payments d
                     WHERE d.company_id = s.company_id AND d.ex_date > s.snapshot_date AND d.ex_date <= :until), 0) AS dividends
    FROM signal_snapshots s
    LEFT JOIN LATERAL (
        SELECT p.price_date, p.close_price FROM daily_prices p
        WHERE p.company_id = s.company_id AND p.price_date <= :until
        ORDER BY p.price_date DESC LIMIT 1
    ) e ON TRUE
    WHERE s.snapshot_date = :night
""")


def market_date(session) -> date | None:
    return session.execute(text("SELECT MAX(price_date) FROM daily_prices")).scalar_one()


def fill_outcomes(session, as_at: date | None = None) -> int:
    """Score every scorecard signal whose horizon the market data has
    reached. Each night's benchmark uses every company screened that night,
    scored the same way. Returns the number of outcomes written."""
    as_at = as_at or market_date(session)
    if as_at is None:
        return 0
    due = session.execute(_SCORECARD_DUE, {"market_date": as_at}).mappings().all()
    groups: dict[tuple[date, int], list] = defaultdict(list)
    for row in due:
        groups[(row["snapshot_date"], row["horizon"])].append(row)

    written = 0
    for (night, months), wanted in sorted(groups.items()):
        until = add_months(night, months)
        results = {}
        for r in session.execute(_NIGHT_RESULTS, {"night": night, "until": until}).mappings():
            if r["end_price"] is None:
                continue
            tr = total_return(r["price"], r["end_price"], r["dividends"])
            if tr is not None:
                results[r["company_id"]] = (r, tr)
        if not results:
            continue
        benchmark = sum((tr for _, tr in results.values()), Decimal("0")) / len(results)
        for w in wanted:
            found = results.get(w["company_id"])
            if found is None:
                continue
            r, tr = found
            session.execute(text("""
                INSERT INTO signal_outcomes (company_id, snapshot_date, horizon_months, is_cohort, is_change,
                    end_date, end_price, dividends, total_return, benchmark_return, excess_return, gap_closed,
                    delisted, universe_size)
                VALUES (:company_id, :night, :months, :is_cohort, :is_change, :end_date, :end_price, :dividends,
                    :tr, :bench, :excess, :gap, :delisted, :size)
                ON CONFLICT DO NOTHING
            """), {
                "company_id": w["company_id"], "night": night, "months": months,
                "is_cohort": w["is_cohort"], "is_change": w["is_change"],
                "end_date": r["end_date"], "end_price": r["end_price"], "dividends": r["dividends"],
                "tr": _pct(tr), "bench": _pct(benchmark), "excess": _pct(tr - benchmark),
                "gap": _pct(gap_closed(r["price"], r["end_price"], r["estimated_value"])),
                "delisted": r["end_date"] < until - timedelta(days=STALE_PRICE_DAYS), "size": len(results),
            })
            written += 1
    return written


def refresh_monthly(session) -> int:
    """Rebuild the monthly summary for every month that still has scored
    monthly signals. Returns the number of summary rows written."""
    months = [m for (m,) in session.execute(text(
        "SELECT DISTINCT date_trunc('month', snapshot_date)::date FROM signal_outcomes WHERE is_cohort"))]
    if not months:
        return 0
    session.execute(text("DELETE FROM track_record_monthly WHERE month = ANY(:months)"), {"months": months})
    rows = session.execute(text("""
        SELECT date_trunc('month', o.snapshot_date)::date AS month, s.action, o.horizon_months, s.rules_version,
               o.total_return, o.excess_return
        FROM signal_outcomes o JOIN signal_snapshots s USING (company_id, snapshot_date)
        WHERE o.is_cohort AND o.excess_return IS NOT NULL
    """)).mappings().all()
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["month"], r["action"], r["horizon_months"], r["rules_version"])].append(r)
    for (month, action, months_ahead, version), items in groups.items():
        excess = [r["excess_return"] for r in items]
        returns = [r["total_return"] for r in items if r["total_return"] is not None]
        session.execute(text("""
            INSERT INTO track_record_monthly (month, action, horizon_months, rules_version, signals, beat_benchmark,
                avg_return, avg_excess, median_excess)
            VALUES (:month, :action, :horizon, :version, :signals, :beat, :avg_return, :avg_excess, :median_excess)
        """), {
            "month": month, "action": action, "horizon": months_ahead, "version": version, "signals": len(items),
            "beat": sum(1 for e in excess if e > 0),
            "avg_return": _pct(sum(returns, Decimal("0")) / len(returns)) if returns else None,
            "avg_excess": _pct(sum(excess, Decimal("0")) / len(excess)),
            "median_excess": _pct(Decimal(statistics.median(excess))),
        })
    return len(groups)


def retention_cutoff(today: date) -> date:
    """Daily detail before this date is deleted: whole months only, so a
    month is never left half-kept (which would change its first signal)."""
    return add_months(today.replace(day=1), -RETENTION_MONTHS)


def prune(session, today: date) -> int:
    """Delete snapshots (and, by cascade, their outcomes) older than the
    retention window. Call after refresh_monthly() in the same transaction."""
    result = session.execute(text("DELETE FROM signal_snapshots WHERE snapshot_date < :cutoff"),
                             {"cutoff": retention_cutoff(today)})
    return result.rowcount or 0


@dataclass
class TrackRecordRun:
    outcomes: int
    summary_rows: int
    pruned: int
    market_date: date | None


def update_track_record(session, today: date) -> TrackRecordRun:
    as_at = market_date(session)
    outcomes = fill_outcomes(session, as_at)
    summary = refresh_monthly(session)
    pruned = prune(session, today)
    return TrackRecordRun(outcomes, summary, pruned, as_at)


__all__ = ["HORIZONS_MONTHS", "RETENTION_MONTHS", "update_track_record", "fill_outcomes", "refresh_monthly", "prune"]
