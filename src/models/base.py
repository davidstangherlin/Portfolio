"""Shared declarative base for all ORM models.

These models map onto tables created by `db/schema.sql` - they do not
create or migrate the schema themselves (no `Base.metadata.create_all`
call is made anywhere in this package). Apply `db/schema.sql` with psql
first, as described in the README.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
