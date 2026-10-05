"""Pure pieces of the dashboard: reading the nightly log, the stale-data
rule's weekday arithmetic, and the valuation status labels."""

from datetime import date, datetime
from decimal import Decimal

import gui
from src.screening.enriched import valuation_status

LOG = """===== Daily Refresh Started: 2026-10-05 18:00:02 =====

--- Ingestion ---
2026-10-05 18:01:00,000 INFO src.ingestion: BHP ok
{problem}
===== Daily Refresh Finished: 2026-10-05 18:42:10 =====
"""


def _write(tmp_path, name, body, encoding="utf-8"):
    (tmp_path / name).write_text(body, encoding=encoding)


def test_newest_log_wins_and_a_clean_run_is_ok(tmp_path):
    _write(tmp_path, "refresh_2026-10-04_180000.log", LOG.format(problem="Traceback (most recent call last):"))
    _write(tmp_path, "refresh_2026-10-05_180002.log", LOG.format(problem=""))
    run = gui.last_refresh(tmp_path, datetime(2026, 10, 6, 8, 0))
    assert run["file"] == "refresh_2026-10-05_180002.log"
    assert run["status"] == "ok" and run["errors"] == 0
    assert run["started"] == datetime(2026, 10, 5, 18, 0, 2) and run["finished"] == datetime(2026, 10, 5, 18, 42, 10)


def test_a_company_failing_is_an_error_not_a_crash(tmp_path):
    problem = ("2026-10-05 18:02:00,000 ERROR src.ingestion: XYZ failed - skipping\n"
               "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: no data")
    _write(tmp_path, "refresh_2026-10-05_180002.log", LOG.format(problem=problem), encoding="utf-16")
    run = gui.last_refresh(tmp_path, datetime(2026, 10, 6, 8, 0))
    assert run["status"] == "errors" and (run["errors"], run["crashes"]) == (1, 0)
    assert "XYZ failed" in run["first_error"]


def test_a_traceback_on_its_own_is_a_crashed_step(tmp_path):
    problem = "Traceback (most recent call last):\n  File \"x.py\", line 1\nModuleNotFoundError: No module named 'src'"
    _write(tmp_path, "refresh_2026-10-05_180002.log", LOG.format(problem=problem))
    run = gui.last_refresh(tmp_path, datetime(2026, 10, 6, 8, 0))
    assert run["status"] == "crashed" and run["crashes"] == 1


def test_unfinished_run_is_running_then_incomplete(tmp_path):
    _write(tmp_path, "refresh_2026-10-05_180002.log", LOG.format(problem="").split("===== Daily Refresh Finished")[0])
    assert gui.last_refresh(tmp_path, datetime(2026, 10, 5, 18, 30))["status"] == "running"
    assert gui.last_refresh(tmp_path, datetime(2026, 10, 6, 8, 0))["status"] == "incomplete"


def test_no_logs_yet(tmp_path):
    assert gui.last_refresh(tmp_path, datetime(2026, 10, 6)) is None


def test_previous_weekday_skips_the_weekend():
    assert gui._previous_weekday(date(2026, 10, 5)) == date(2026, 10, 2)  # Monday -> Friday
    assert gui._previous_weekday(date(2026, 10, 7)) == date(2026, 10, 6)
    assert gui._previous_weekday(date(2026, 10, 4)) == date(2026, 10, 2)  # Sunday -> Friday


def test_valuation_status_bands():
    t = Decimal("20")
    assert valuation_status(None, t) == "No estimate"
    assert valuation_status(Decimal("20.01"), t) == "Undervalued"
    assert valuation_status(Decimal("20"), t) == "Fair value"
    assert valuation_status(Decimal("0"), t) == "Fair value"
    assert valuation_status(Decimal("-0.01"), t) == "Overvalued"
