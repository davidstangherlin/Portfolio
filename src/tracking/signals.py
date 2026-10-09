"""Nightly signal snapshots: the record the track record is built on
(docs/AS_BUILT.md §21).

Each night, after valuation, every screened company's suggested action,
valuation status, estimate, scores and value tests are written to
`signal_snapshots`, dated by the price date the valuation used. Rows are
never edited: a second run for the same date leaves the first in place
(ON CONFLICT DO NOTHING), so the record is what Sift actually said at the
time, not what today's rules would have said.

Shared and personal (§34): `signal_snapshots` holds Sift's call for
someone who doesn't hold the share, the same for everyone. For each share
a person holds, their call on that holding is recorded in
`position_snapshots`. A person's view of a night is the shared row with
their own call laid over it (`person_nights`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from src import accounts
from src.ingestion.dividend_history import add_months
from src.models import DailyPrice, SignalSnapshot
from src.portfolio.holdings import position_summaries
from src.screening.actions import red_flags, suggest_action
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
    personal: int = 0  # people's calls on their holdings recorded (position_snapshots)


def snapshot_values(row: dict, rules_version: str = RULES_VERSION, analysts: tuple | None = None) -> dict:
    """One signal_snapshots row from an enriched screener row
    (src/screening/enriched.py), with the analysts' (mean target, count)
    in force that night."""
    scores = row["axis_scores"]
    target, count = analysts or (None, None)
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
        "graham_number": row.get("graham_number"),
        "analyst_target": target,
        "analyst_count": count,
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


_PERSONAL_INSERT = text("""
    INSERT INTO position_snapshots (owner_id, company_id, snapshot_date, units, action, action_reason, rules_version)
    VALUES (:owner, :company_id, :night, :units, :action, :reason, :version)
    ON CONFLICT DO NOTHING
""")


def record_signals(session, today: date, universe: Universe | None = None) -> RecordResult:
    """Write tonight's snapshot for every screened company whose valuation
    is up to date with its latest price, as Sift's shared call (for someone
    not holding it), then each active person's call on each share they
    hold. A company whose valuation failed tonight would otherwise pair
    yesterday's estimate with today's price, so it is skipped (and
    reported) rather than recorded wrongly."""
    universe = universe or load_universe(session, today, neutral=True)
    latest_price = _latest_price_dates(session)
    analysts = {c: (t, n) for c, t, n in session.execute(text(
        "SELECT company_id, target_mean, analyst_count FROM company_insights WHERE target_mean IS NOT NULL"))}
    result = RecordResult()
    recorded: dict[str, dict] = {}
    for row in universe.rows:
        if row["company_id"] is None or row["as_of_date"] is None:
            continue
        if latest_price.get(row["company_id"]) != row["as_of_date"]:
            result.stale.append(row["asx_code"])
            continue
        stmt = (insert(SignalSnapshot).values(**snapshot_values(row, analysts=analysts.get(row["company_id"])))
                .on_conflict_do_nothing(index_elements=["company_id", "snapshot_date"])
                .returning(SignalSnapshot.company_id))
        if session.execute(stmt).first() is None:
            result.already_recorded += 1
        else:
            result.recorded += 1
        result.dates.add(row["as_of_date"])
        recorded[row["asx_code"]] = row
    result.personal = record_positions(session, today, recorded)
    return result


def record_positions(session, today: date, recorded: dict[str, dict]) -> int:
    """Each active person's call on each share they hold, for the nights
    just recorded (`recorded`: shared rows by code). Returns rows written."""
    written = 0
    for user in accounts.all_users(session, active_only=True):
        with accounts.acting_as(user.user_id):
            positions = position_summaries(session, today)
        for code, position in positions.items():
            row = recorded.get(code)
            if row is None or position.units <= 0:
                continue
            action, reason = suggest_action(row, position, today)
            written += session.execute(_PERSONAL_INSERT, {
                "owner": user.user_id, "company_id": row["company_id"], "night": row["as_of_date"],
                "units": position.units, "action": action, "reason": reason, "version": RULES_VERSION,
            }).rowcount or 0
    return written


def person_nights(session, since: date | None = None, owner_id=None) -> list[dict]:
    """The record as one person sees it: every shared row from `since`,
    with their own call laid over it on nights they held the share
    (`held` true). Shared rows from before Phase 2 that were someone's held
    calls are left out unless they're this person's."""
    owner_id = owner_id or accounts.current_user_id(session)
    return [dict(r) for r in session.execute(text("""
        SELECT c.asx_code, c.company_name, s.company_id, s.snapshot_date, s.price,
               COALESCE(p.action, s.action) AS action, p.owner_id IS NOT NULL AS held,
               COALESCE(p.rules_version, s.rules_version) AS rules_version,
               s.margin_of_safety_percent, s.valuation_status,
               s.estimated_value, s.graham_number, s.analyst_target, s.analyst_count
        FROM signal_snapshots s
        JOIN companies c ON c.company_id = s.company_id
        LEFT JOIN position_snapshots p
               ON p.company_id = s.company_id AND p.snapshot_date = s.snapshot_date AND p.owner_id = :owner
        WHERE (CAST(:since AS DATE) IS NULL OR s.snapshot_date >= :since)
          AND (p.owner_id IS NOT NULL OR NOT s.held)
        ORDER BY c.asx_code, s.snapshot_date
    """), {"owner": owner_id, "since": since}).mappings()]


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
    snapshot dates, for the current user (their own call on shares they
    held), better first. Moves between actions of equal rank, and moves
    caused by buying or selling the shares, are left out."""
    dates = session.execute(
        select(SignalSnapshot.snapshot_date).distinct()
        .order_by(SignalSnapshot.snapshot_date.desc()).limit(2)
    ).scalars().all()
    if len(dates) < 2:
        return {"from_date": None, "to_date": dates[0] if dates else None, "changes": []}
    to_date, from_date = dates
    nights: dict[str, dict] = {}
    for r in person_nights(session, from_date):
        nights.setdefault(r["asx_code"], {})[r["snapshot_date"]] = r
    changes = []
    for code, by_date in nights.items():
        now, before = by_date.get(to_date), by_date.get(from_date)
        if now is None or before is None or now["action"] == before["action"] or now["held"] != before["held"]:
            continue
        rank, previous_rank = ACTION_RANK.get(now["action"], 4), ACTION_RANK.get(before["action"], 4)
        if rank == previous_rank:
            continue
        changes.append({
            "asx_code": code, "company_name": now["company_name"], "action": now["action"],
            "previous": before["action"], "held": now["held"], "direction": "up" if rank < previous_rank else "down",
            "margin_of_safety_percent": now["margin_of_safety_percent"], "valuation_status": now["valuation_status"],
        })
    changes.sort(key=lambda c: (c["direction"] != "up", ACTION_RANK.get(c["action"], 4), c["asx_code"]))
    return {"from_date": from_date, "to_date": to_date, "changes": changes}
