"""Who Sift is acting for (docs/AS_BUILT.md §33, docs/MULTI_USER_PLAN.md).

Each person's portfolios, watchlists, scenarios and dashboard layout carry
their `owner_id`; market data, valuations and help are shared. Rather than
every route remembering to filter, the functions that read and write
personal data ask `current_user_id(session)` and scope themselves.

The current user is set per request by gui.py's middleware (`acting_as`).
With nobody set (the command line, the nightly run, tests) Sift acts for
the first active admin, the "owner", created on first use: so a
one-person Sift works exactly as it did before accounts."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import text

OWNER_EMAIL = "owner@sift.local"  # placeholder until logins are linked (Phase 3)
ROLES = ("admin", "member")

_current: ContextVar[uuid.UUID | None] = ContextVar("sift_current_user", default=None)


class AccountError(ValueError):
    """A request that breaks a rule; the message is written for the user."""


@dataclass(frozen=True)
class User:
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def info(self) -> dict:
        return {"user_id": str(self.user_id), "email": self.email, "display_name": self.display_name,
                "role": self.role, "admin": self.is_admin}


_COLUMNS = "user_id, email, display_name, role, status"


def _user(row) -> User | None:
    return User(*row) if row else None


def owner(session) -> User:
    """The first active admin, created if Sift has no admin yet."""
    row = session.execute(text(f"""
        SELECT {_COLUMNS} FROM users WHERE role = 'admin' AND status = 'active'
        ORDER BY created_at, email LIMIT 1""")).first()
    if row is None:
        row = session.execute(text(f"""
            INSERT INTO users (email, display_name, role) VALUES (:e, 'Owner', 'admin')
            ON CONFLICT (email) DO UPDATE SET role = 'admin', status = 'active'
            RETURNING {_COLUMNS}"""), {"e": OWNER_EMAIL}).first()
    return _user(row)


def current_user_id(session) -> uuid.UUID:
    """The user whose data is being read or written."""
    chosen = _current.get()
    if chosen is not None:
        return chosen
    cached = session.info.get("sift_owner")
    if cached is None:
        cached = session.info["sift_owner"] = owner(session).user_id
    return cached


@contextmanager
def acting_as(user_id):
    """Read and write as this user inside the block."""
    token = _current.set(uuid.UUID(str(user_id)) if user_id is not None else None)
    try:
        yield
    finally:
        _current.reset(token)


def get_user(session, user_id) -> User | None:
    try:
        key = uuid.UUID(str(user_id))
    except ValueError:
        return None
    return _user(session.execute(text(f"SELECT {_COLUMNS} FROM users WHERE user_id = :u"), {"u": key}).first())


def find_user(session, email: str) -> User | None:
    return _user(session.execute(text(f"SELECT {_COLUMNS} FROM users WHERE email = :e"),
                                 {"e": (email or "").strip().lower()}).first())


def current_user(session) -> User:
    return get_user(session, current_user_id(session))


def all_users(session, active_only: bool = False) -> list[User]:
    where = "WHERE status = 'active'" if active_only else ""
    return [_user(r) for r in session.execute(text(f"SELECT {_COLUMNS} FROM users {where} ORDER BY created_at, email"))]


def create_user(session, email: str, display_name: str, role: str = "member") -> User:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 255:
        raise AccountError("an account needs a valid email address")
    name = " ".join((display_name or "").split()) or email.split("@")[0]
    if len(name) > 80:
        raise AccountError("display names can be at most 80 characters")
    if role not in ROLES:
        raise AccountError(f"role must be one of {', '.join(ROLES)}")
    if find_user(session, email):
        raise AccountError(f"there is already an account for {email}")
    return _user(session.execute(text(f"""
        INSERT INTO users (email, display_name, role) VALUES (:e, :n, :r) RETURNING {_COLUMNS}"""),
        {"e": email, "n": name, "r": role}).first())


def touch(session, user_id) -> None:
    """Note when someone last used Sift (at most once a minute)."""
    session.execute(text("""
        UPDATE users SET last_seen_at = CURRENT_TIMESTAMP
        WHERE user_id = :u AND (last_seen_at IS NULL OR last_seen_at < CURRENT_TIMESTAMP - INTERVAL '1 minute')"""),
        {"u": user_id})
