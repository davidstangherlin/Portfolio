"""Shared pytest fixtures.

Unit tests (tests/unit/) are pure - they build plain ORM objects in memory
and call functions directly, no database involved, so they run instantly
and need nothing installed beyond requirements-dev.txt.

Integration tests (tests/integration/) need a real local PostgreSQL
instance, matching how every fix in this project has actually been
validated throughout its history (see docs/AS_BUILT.md §10) - disposable
databases, never mocks, because the bugs this project has hit in practice
(numeric overflow, view column ordering, upsert/commit semantics) are
exactly the kind that a mocked session would not have caught. If no
database is reachable, integration tests are skipped (not failed) with a
clear reason, so `pytest` still runs cleanly on a machine that hasn't set
one up yet - set TEST_DATABASE_URL to point at a different instance.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import psycopg2
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:testpw@localhost:5432/asx_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # must be set before src.config is first imported

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"

# Truncated between every DB-backed test for isolation - children first,
# via CASCADE, same tables README.md's "Full teardown/reset" documents.
_TABLES = "companies, daily_prices, financial_reports, valuation_metrics, holdings, portfolios, dividend_payments, signal_snapshots, watchlists, watchlist_items"


def _connect(dbname: str | None = None):
    url = make_url(TEST_DATABASE_URL)
    return psycopg2.connect(
        host=url.host, port=url.port, user=url.username, password=url.password,
        dbname=dbname or url.database,
    )


def _database_reachable() -> tuple[bool, str]:
    try:
        conn = _connect("postgres")
        conn.close()
        return True, ""
    except Exception as exc:  # noqa: BLE001 - reported as a skip reason, not re-raised
        return False, str(exc)


@pytest.fixture(scope="session")
def _test_database():
    """Creates the test database (if missing) and applies db/schema.sql,
    once per test session. Deliberately NOT autouse: only `db_session`
    (and anything else that actually touches the database) depends on
    this, so a pure unit test that never requests `db_session` is
    completely unaffected by whether Postgres is even running - it must
    not skip just because an unrelated fixture would have needed a DB."""
    reachable, reason = _database_reachable()
    if not reachable:
        pytest.skip(f"Test PostgreSQL instance unreachable at {TEST_DATABASE_URL!r} ({reason}) - "
                     "start Postgres locally or set TEST_DATABASE_URL to point at one.")

    url = make_url(TEST_DATABASE_URL)
    admin_conn = _connect("postgres")
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{url.database}"')
    admin_conn.close()

    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    conn.close()
    yield


@pytest.fixture()
def db_session(_test_database):
    """A fresh SQLAlchemy session against the test database, with every
    table truncated before the test runs (not after - a failed test's data
    is left in place for post-mortem inspection, cleaned up by the next
    test's setup instead). Depending on `_test_database` here (rather than
    making it autouse) is what keeps pure unit tests from ever touching
    Postgres at all."""
    from src.config import get_session_factory

    conn = _connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    conn.close()

    session = get_session_factory()()
    yield session
    session.close()
