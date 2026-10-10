"""Rules versions, as people see them (docs/kb/features/track-record.md).

Each recorded call carries the date its screening rules last changed
(`RULES_VERSION` in src/tracking/signals.py), so the track record can judge
each set of rules on its own results. People never need that date: admins
see each version as "Version 1", "Version 2" and so on, in date order, with
what changed, in Admin, Model and rules.

When you change the rules: bump RULES_VERSION to the date and add an entry
here saying what changed (tests/unit/test_rules_versions.py checks it)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from src.tracking.signals import RULES_VERSION

# (version, title, what changed), oldest first.
HISTORY: list[tuple[str, str, str]] = [
    ("2026-10-05", "The first rules the track record judges",
     "Recording began with these rules: the four value tests (margin of safety, ROE, debt to equity, grossed-up "
     "dividend yield), the 30-check score wheel, red flags, and the actions BUY, INVESTIGATE, WATCH, AVOID and IGNORE "
     "(and, for shares held, ACCUMULATE, HOLD, REVIEW and SELL). Changes made that day before recording began: "
     "the dividend trend flags only a cut that still stands, foreign companies are treated as unfranked, and "
     "ACCUMULATE was added for held shares that pass all four tests with no red flags."),
]
_NOTES = {v: (title, changes) for v, title, changes in HISTORY}


def all_versions(session) -> list[str]:
    """Every version with calls or results, and the current one, oldest first."""
    found = {v for (v,) in session.execute(text("""
        SELECT rules_version FROM signal_snapshots UNION SELECT rules_version FROM track_record_monthly
        UNION SELECT rules_version FROM position_snapshots"""))}
    return sorted(found | {RULES_VERSION} | set(_NOTES))


def label(session, version: str | None) -> str | None:
    """ "Version 2" for a version date; None for None (all versions)."""
    if version is None:
        return None
    versions = all_versions(session)
    return f"Version {versions.index(version) + 1}" if version in versions else None


def listing(session) -> list[dict]:
    """Each version for the admin console: its number, when it took effect,
    what changed, and how much of the track record it holds, newest first."""
    counts = {r["version"]: r for r in session.execute(text("""
        SELECT rules_version AS version, count(*) AS calls, count(DISTINCT snapshot_date) AS nights,
               min(snapshot_date) AS first_night, max(snapshot_date) AS last_night
        FROM signal_snapshots WHERE NOT held GROUP BY rules_version""")).mappings()}
    results = dict(session.execute(text(
        "SELECT rules_version, sum(signals) FROM track_record_monthly GROUP BY rules_version")).all())
    out = []
    for i, v in enumerate(all_versions(session), start=1):
        title, changes = _NOTES.get(v, (None, None))
        c = counts.get(v) or {}
        out.append({"version": v, "label": f"Version {i}", "in_use_from": date.fromisoformat(v), "current": v == RULES_VERSION,
                    "title": title or "No notes recorded", "changes": changes,
                    "calls": c.get("calls", 0), "nights": c.get("nights", 0), "first_night": c.get("first_night"),
                    "last_night": c.get("last_night"), "scored": int(results.get(v) or 0)})
    return list(reversed(out))
