"""Rules versions (src/tracking/rules_versions.py): the version in use has
notes on what changed, so the admin console can say what each version is."""

from datetime import date

from src.tracking import rules_versions
from src.tracking.signals import RULES_VERSION


def test_the_version_in_use_says_what_changed():
    notes = {v: (title, changes) for v, title, changes in rules_versions.HISTORY}
    assert RULES_VERSION in notes, "bumped RULES_VERSION: add what changed to HISTORY in src/tracking/rules_versions.py"
    for v, (title, changes) in notes.items():
        date.fromisoformat(v)
        assert title and len(changes) > 40 and "—" not in title + changes


def test_history_is_oldest_first():
    versions = [v for v, _, _ in rules_versions.HISTORY]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
