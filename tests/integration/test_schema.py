"""db/schema.sql - applies cleanly and idempotently against a real
PostgreSQL instance (docs/AS_BUILT.md §10.1)."""

import pytest
from sqlalchemy import text

from tests.conftest import SCHEMA_PATH, _connect

pytestmark = pytest.mark.integration


def test_schema_reapplies_without_error(_test_database):
    # The conftest session fixture already applied it once; re-applying
    # here proves the CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT
    # EXISTS / CREATE OR REPLACE VIEW statements are genuinely idempotent,
    # not just "happened to work on a fresh database" - this is exactly
    # how every schema migration in this project has actually been
    # validated (see docs/AS_BUILT.md §10.1, §10.9). Depending on
    # `_test_database` (rather than calling _connect() with no fixture at
    # all) is what makes this skip cleanly if Postgres isn't reachable,
    # instead of failing with a raw connection error.
    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    conn.close()


def test_asx_value_screener_view_exposes_every_valuation_metrics_column(db_session):
    # Regression for known-issue #14's lesson: payout_ratio/valuation_method/
    # margin_of_safety_trend/fundamentals_trend were all added to the view
    # after the fact, appended at the end of the SELECT list (CREATE OR
    # REPLACE VIEW can't insert a column mid-list). This confirms the view
    # actually exposes all of them, not just the original columns.
    expected_columns = {
        "asx_code", "company_name", "sector", "current_price",
        "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
        "grossed_up_dividend_yield", "dcf_intrinsic_value", "graham_number",
        "margin_of_safety_percent", "payout_ratio", "valuation_method",
        "margin_of_safety_trend", "fundamentals_trend",
    }
    result = db_session.execute(
        text("SELECT * FROM asx_value_screener LIMIT 0")
    )
    assert expected_columns.issubset(set(result.keys()))
