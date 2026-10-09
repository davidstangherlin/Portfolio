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


def update_user(session, user: User, by: User, display_name=None, role=None, status=None) -> User:
    """Change a name, role or status. Nobody can demote or disable
    themselves, and Sift always keeps at least one active admin."""
    fields = {}
    if display_name is not None:
        name = " ".join(str(display_name).split())
        if not name:
            raise AccountError("a display name can't be blank")
        if len(name) > 80:
            raise AccountError("display names can be at most 80 characters")
        fields["display_name"] = name
    if role is not None:
        if role not in ROLES:
            raise AccountError(f"role must be one of {', '.join(ROLES)}")
        fields["role"] = role
    if status is not None:
        if status not in ("active", "disabled"):
            raise AccountError("status must be active or disabled")
        fields["status"] = status
    losing_admin = user.is_admin and user.is_active and (fields.get("role", "admin") != "admin"
                                                         or fields.get("status", "active") != "active")
    if losing_admin and user.user_id == by.user_id:
        raise AccountError("you can't remove your own admin role or disable yourself")
    if losing_admin and sum(1 for u in all_users(session, active_only=True) if u.is_admin) <= 1:
        raise AccountError("Sift needs at least one active admin")
    if fields:
        session.execute(text(f"UPDATE users SET {', '.join(f'{k} = :{k}' for k in fields)} WHERE user_id = :u"),
                        fields | {"u": user.user_id})
    if fields.get("status") == "disabled" or fields.get("role") == "admin":
        end_impersonations_of(session, user.user_id, "unavailable")
    return get_user(session, user.user_id)


def user_list(session) -> list[dict]:
    """Every account with what it owns, for the admin Users tab."""
    return [dict(r) for r in session.execute(text("""
        SELECT u.user_id, u.email, u.display_name, u.role, u.status, u.created_at, u.last_seen_at,
               (SELECT count(*) FROM portfolios p WHERE p.owner_id = u.user_id) AS portfolios,
               (SELECT count(*) FROM watchlists w WHERE w.owner_id = u.user_id) AS watchlists
        FROM users u ORDER BY u.role, u.created_at, u.email
    """)).mappings()]


# ---------- impersonation (§35) ----------

IMPERSONATION_HOURS = 8  # an open session ends by itself after this long


def can_impersonate(admin: User, target: User | None) -> str | None:
    """Why `admin` can't act as `target`, or None if they can."""
    if not admin.is_admin:
        return "only an admin can impersonate"
    if target is None:
        return "no such account"
    if target.user_id == admin.user_id:
        return "you can't impersonate yourself"
    if target.is_admin:
        return "admins can't be impersonated"
    if not target.is_active:
        return f"{target.display_name}'s account is disabled"
    return None


def start_impersonation(session, admin: User, target: User | None) -> User:
    why = can_impersonate(admin, target)
    if why:
        raise AccountError(why)
    end_impersonation(session, admin.user_id, "replaced")
    session.execute(text("INSERT INTO impersonations (admin_id, target_id) VALUES (:a, :t)"),
                    {"a": admin.user_id, "t": target.user_id})
    return target


def end_impersonation(session, admin_id, how: str = "ended") -> bool:
    return (session.execute(text("""
        UPDATE impersonations SET ended_at = CURRENT_TIMESTAMP, ended_how = :how
        WHERE admin_id = :a AND ended_at IS NULL"""), {"a": admin_id, "how": how}).rowcount or 0) > 0


def end_impersonations_of(session, target_id, how: str) -> None:
    session.execute(text("""
        UPDATE impersonations SET ended_at = CURRENT_TIMESTAMP, ended_how = :how
        WHERE target_id = :t AND ended_at IS NULL"""), {"t": target_id, "how": how})


def impersonating(session, admin: User) -> User | None:
    """Whom this admin is acting as, ending a session that has run out or
    whose person can no longer be impersonated."""
    if not admin.is_admin:
        return None
    row = session.execute(text("""
        SELECT target_id, started_at < CURRENT_TIMESTAMP - make_interval(hours => :h) AS expired
        FROM impersonations WHERE admin_id = :a AND ended_at IS NULL"""),
        {"a": admin.user_id, "h": IMPERSONATION_HOURS}).first()
    if row is None:
        return None
    target = get_user(session, row.target_id)
    if row.expired or can_impersonate(admin, target):
        end_impersonation(session, admin.user_id, "expired" if row.expired else "unavailable")
        return None
    return target


def impersonation_log(session, limit: int = 50) -> list[dict]:
    return [dict(r) for r in session.execute(text("""
        SELECT i.impersonation_id, a.display_name AS admin, a.email AS admin_email, t.display_name AS target,
               t.email AS target_email, i.started_at, i.ended_at, i.ended_how
        FROM impersonations i JOIN users a ON a.user_id = i.admin_id JOIN users t ON t.user_id = i.target_id
        ORDER BY i.started_at DESC LIMIT :n"""), {"n": limit}).mappings()]
