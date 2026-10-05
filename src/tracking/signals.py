"""Nightly signal snapshots: the record the track record is built on
(docs/AS_BUILT.md §21).

Each night, after valuation, every screened company's suggested action,
valuation status, estimate, scores and value tests are written to
`signal_snapshots`, dated by the price date the valuation used. Rows are
never edited: a second run for the same date leaves the first in place
(ON CONFLICT DO NOTHING), so the record is what Sift actually said at the
time, not what today's rules would have said.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.ingestion.dividend_history import add_months
from src.models import Company, DailyPrice, SignalSnapshot
from src.screening.actions import red_flags
from src.screening.enriched import Universe, load_universe

# The date the screening rules (thresholds, actions, scores, valuation
# models) last changed. Bump it whenever they change, so the track record
# can judge each set of rules on its own results.
RULES_VERSION = "2026-10-05"

# For "What changed today": how attractive each action is, best first.
# A move between actions of equal rank (BUY to ACCUMULATE after buying,
# WATCH to HOLD) isn't a change in the signal.
ACTION_RANK = {
    "BUY": 1, "ACCUMULATE": 1,
    "INVESTIGATE": 2,
    "WATCH": 3, "HOLD": 3,
    "REVIEW": 4, "IGNORE": 4,
    "AVOID": 5, "SELL": 5,
}

# Outcome horizons the track record will measure, in months.
HORIZONS_MONTHS = (1, 3, 6, 12)


@dataclass
class RecordResult:
    recorded: int = 0
    already_recorded: int = 0
    stale: list[str] = field(default_factory=list)  # valuation older than the latest price: not recorded
    dates: set[date] = field(default_factory=set)


def snapshot_values(row: dict, rules_version: str = RULES_VERSION) -> dict:
    """One signal_snapshots row from an enriched screener row
    (src/screening/enriched.py)."""
    scores = row["axis_scores"]
    return {
        "company_id": row["company_id"],
        "snapshot_date": row["as_of_date"],
        "price": row["current_price"],
        "action": row["action"],
        "action_reason": row["action_reason"],
        "held": row["held"] is not None,
        "valuation_status": row["valuation_status"],
        "margin_of_safety_percent": row["margin_of_safety_percent"],
        "estimated_value": row["dcf_intrinsic_value"],
        "valuation_method": row["valuation_method"],
        "score_total": sum(scores.values()),
        "score_value": scores["Value"],
        "score_performance": scores["Performance"],
        "score_health": scores["Health"],
        "score_dividend": scores["Dividend"],
        "score_momentum": scores["Momentum"],
        "mos_ok": row["mos_ok"] == "Y",
        "roe_ok": row["roe_ok"] == "Y",
        "de_ok": row["de_ok"] == "Y",
        "yield_ok": row["yield_ok"] == "Y",
        "red_flags": red_flags(row),
        "rules_version": rules_version,
    }


def _latest_price_dates(session) -> dict:
    return dict(session.execute(
        select(DailyPrice.company_id, func.max(DailyPrice.price_date)).group_by(DailyPrice.company_id)
    ).all())


def record_signals(session, today: date, universe: Universe | None = None) -> RecordResult:
    """Write tonight's snapshot for every screened company whose valuation
    is up to date with its latest price. A company whose valuation failed
    tonight would otherwise pair yesterday's estimate with today's price,
    so it is skipped (and reported) rather than recorded wrongly."""
    universe = universe or load_universe(session, today)
    latest_price = _latest_price_dates(session)
    result = RecordResult()
    for row in universe.rows:
        if row["company_id"] is None or row["as_of_date"] is None:
            continue
        if latest_price.get(row["company_id"]) != row["as_of_date"]:
            result.stale.append(row["asx_code"])
            continue
        stmt = (insert(SignalSnapshot).values(**snapshot_values(row))
                .on_conflict_do_nothing(index_elements=["company_id", "snapshot_date"])
                .returning(SignalSnapshot.company_id))
        if session.execute(stmt).first() is None:
            result.already_recorded += 1
        else:
            result.recorded += 1
        result.dates.add(row["as_of_date"])
    return result


def tracking_status(session) -> dict:
    """How far the record has got, for the dashboard and the track record page."""
    first, latest, days, rows = session.execute(select(
        func.min(SignalSnapshot.snapshot_date), func.max(SignalSnapshot.snapshot_date),
        func.count(func.distinct(SignalSnapshot.snapshot_date)), func.count(),
    )).one()
    latest_count = 0
    if latest is not None:
        latest_count = session.execute(
            select(func.count()).where(SignalSnapshot.snapshot_date == latest)
        ).scalar_one()
    return {
        "first_date": first,
        "latest_date": latest,
        "days_recorded": days,
        "signals_recorded": rows,
        "companies_latest": latest_count,
        "rules_version": RULES_VERSION,
        "results_due": [{"months": m, "date": add_months(first, m)} for m in HORIZONS_MONTHS] if first else [],
    }


def signal_changes(session) -> dict:
    """Companies whose suggested action moved between the latest two
    snapshot dates, better first. Moves between actions of equal rank, and
    moves caused by buying or selling the shares, are left out."""
    dates = session.execute(
        select(SignalSnapshot.snapshot_date).distinct()
        .order_by(SignalSnapshot.snapshot_date.desc()).limit(2)
    ).scalars().all()
    if len(dates) < 2:
        return {"from_date": None, "to_date": dates[0] if dates else None, "changes": []}
    to_date, from_date = dates
    now, before = SignalSnapshot, SignalSnapshot.__table__.alias("before")
    rows = session.execute(
        select(Company.asx_code, Company.company_name, now.action, before.c.action.label("previous"),
               now.held, before.c.held.label("was_held"), now.margin_of_safety_percent, now.valuation_status)
        .join(now, now.company_id == Company.company_id)
        .join(before, (before.c.company_id == now.company_id) & (before.c.snapshot_date == from_date))
        .where(now.snapshot_date == to_date, now.action != before.c.action)
    ).mappings().all()
    changes = []
    for r in rows:
        if r["held"] != r["was_held"]:
            continue
        rank, previous_rank = ACTION_RANK.get(r["action"], 4), ACTION_RANK.get(r["previous"], 4)
        if rank == previous_rank:
            continue
        changes.append({
            "asx_code": r["asx_code"], "company_name": r["company_name"], "action": r["action"],
            "previous": r["previous"], "held": r["held"], "direction": "up" if rank < previous_rank else "down",
            "margin_of_safety_percent": r["margin_of_safety_percent"], "valuation_status": r["valuation_status"],
        })
    changes.sort(key=lambda c: (c["direction"] != "up", ACTION_RANK.get(c["action"], 4), c["asx_code"]))
    return {"from_date": from_date, "to_date": to_date, "changes": changes}
