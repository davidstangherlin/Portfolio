"""Apply db/schema.sql to the configured database (docs/AS_BUILT.md §16).

    python -m src.apply_schema

Uses the same DATABASE_URL / .env connection as the rest of the project,
so no psql or password prompt is needed. The schema is idempotent (CREATE
... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, CREATE OR REPLACE VIEW), so
running it against an up-to-date database changes nothing. It runs as a
single transaction: if any statement fails, nothing is applied.

scripts/daily_refresh.ps1 runs this before ingestion, so pulling new code
that adds a column can't leave the nightly job failing on every company
because the database hasn't caught up.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import Engine

from src.config import get_engine

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def apply_schema(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)  # no parameters, so % in comments is not interpolated
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = get_engine()
    try:
        apply_schema(engine)
    except Exception:
        logger.exception("Schema apply failed - no changes were made")
        return 1
    logger.info("Schema is up to date on database %r", engine.url.database)
    return 0


if __name__ == "__main__":
    sys.exit(main())
