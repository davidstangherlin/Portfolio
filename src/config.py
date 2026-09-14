"""
Database connection configuration.

Resolution order for the connection string:
1. DATABASE_URL environment variable (or `.env` entry), used as-is.
2. Discrete PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD variables.

`db/schema.sql` must already have been applied to the target database
(see the project README) - this module only manages the connection, it
does not create the schema.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "asx_value")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Session:
    """Return a new SQLAlchemy Session. Caller is responsible for closing it
    (prefer `with get_session() as session:`)."""
    return get_session_factory()()
