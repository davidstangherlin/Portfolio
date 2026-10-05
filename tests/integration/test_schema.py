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


def test_apply_schema_command_is_idempotent(_test_database):
    # `python -m src.apply_schema` is what the nightly job now runs first;
    # it must be safe to run against an already up-to-date database.
    from src.apply_schema import apply_schema
    from src.config import get_engine

    apply_schema(get_engine())
    apply_schema(get_engine())


def test_apply_schema_adds_missing_columns_to_an_older_database(_test_database):
    from src.apply_schema import apply_schema
    from src.config import get_engine

    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE companies DROP COLUMN IF EXISTS country")
    conn.close()

    apply_schema(get_engine())

    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'companies' AND column_name = 'country'")
        assert cur.fetchone() is not None
    conn.close()


def test_existing_parcels_move_into_my_portfolio(_test_database):
    # A database from before portfolios existed: parcels with no portfolio.
    from src.apply_schema import apply_schema
    from src.config import get_engine

    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE holdings, portfolios CASCADE")
        cur.execute("ALTER TABLE holdings ALTER COLUMN portfolio_id DROP NOT NULL")
        cur.execute("INSERT INTO holdings (asx_code, units, buy_date, buy_price) VALUES ('BHP', 100, '2025-03-14', 42.5)")
    conn.close()

    apply_schema(get_engine())
    apply_schema(get_engine())  # and again: still one portfolio

    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT name, tax_type FROM portfolios")
        assert cur.fetchall() == [("My portfolio", "INDIVIDUAL")]
        cur.execute("SELECT count(*) FROM holdings h JOIN portfolios p USING (portfolio_id)")
        assert cur.fetchone() == (1,)
        cur.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name = 'holdings' AND column_name = 'portfolio_id'")
        assert cur.fetchone() == ("NO",)
        cur.execute("TRUNCATE holdings, portfolios CASCADE")
    conn.commit()
    conn.close()


def test_schema_builds_a_brand_new_database(_test_database):
    # Every other test runs against a database that already exists, which
    # hides a table created before one it refers to. Build one from nothing.
    conn = _connect("postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS asx_schema_fresh")
        cur.execute("CREATE DATABASE asx_schema_fresh")
    conn.close()
    fresh = _connect("asx_schema_fresh")
    try:
        with fresh.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text())
        fresh.commit()
    finally:
        fresh.close()
        conn = _connect("postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP DATABASE IF EXISTS asx_schema_fresh")
        conn.close()
