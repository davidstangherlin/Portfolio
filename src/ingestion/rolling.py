"""Weekly refresh spread across the week (docs/AS_BUILT.md §16, §29):
each night takes the seventh of a list whose data is oldest, never-fetched
first, so every item is refreshed about once a week and no single night
carries the whole load. A company fetched in the last six days is never due.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

REFRESH_DAYS = 7


def stale_before(today: date) -> date:
    """Data fetched before this date (midnight) is due again."""
    return today - timedelta(days=REFRESH_DAYS - 1)


def nightly_share(asx_codes: list[str], fetched: dict[str, datetime | None], today: date,
                  all_now: bool = False) -> list[str]:
    """Tonight's codes from `asx_codes`: those never fetched (missing from
    `fetched` or None) in list order, then the oldest, up to a seventh of
    the list; every due code with `all_now`."""
    cutoff = datetime.combine(stale_before(today), datetime.min.time())
    never = [c for c in asx_codes if fetched.get(c) is None]
    stale = sorted((c for c in asx_codes if fetched.get(c) is not None and _naive(fetched[c]) < cutoff),
                   key=lambda c: (_naive(fetched[c]), c))
    due = never + stale
    return due if all_now else due[:math.ceil(len(asx_codes) / REFRESH_DAYS)]


def _naive(moment: datetime) -> datetime:
    """Local wall-clock time, so a timestamp compares with a plain date."""
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment
