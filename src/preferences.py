"""Interface preferences kept in the database (docs/AS_BUILT.md §20), so
they follow you to any browser: for now, the dashboard's layout.

The dashboard layout is {"cards": [{"id", "hidden", "wide"}, ...]} in the
order you arranged the widgets. `wide` is true (full width), false (half)
or null (the widget's own default). Widgets the page doesn't know are
ignored there, and widgets missing from the list keep their default place,
so adding a widget to Sift never needs this changed.

Each person has their own (src/accounts.py, §33)."""

from __future__ import annotations

import json
import re

from sqlalchemy import text

from src.accounts import current_user_id

DASHBOARD_LAYOUT = "dashboard_layout"
MAX_CARDS = 40
_CARD_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class PreferenceError(ValueError):
    """A layout that doesn't have the expected shape: the page's mistake, shown as a 400."""


def clean_layout(body) -> dict:
    """The layout to store, or PreferenceError. Duplicated ids keep their first place."""
    cards = body.get("cards") if isinstance(body, dict) else None
    if not isinstance(cards, list) or len(cards) > MAX_CARDS:
        raise PreferenceError(f"a layout is a list of up to {MAX_CARDS} widgets")
    out, seen = [], set()
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not _CARD_ID.match(card["id"]):
            raise PreferenceError("each widget needs an id of lower-case letters, digits and hyphens")
        hidden, wide = card.get("hidden", False), card.get("wide")
        if not isinstance(hidden, bool) or not (wide is None or isinstance(wide, bool)):
            raise PreferenceError("hidden is true or false; wide is true, false or null")
        if card["id"] not in seen:
            seen.add(card["id"])
            out.append({"id": card["id"], "hidden": hidden, "wide": wide})
    return {"cards": out}


def get_preference(session, key: str):
    return session.execute(text("SELECT value FROM ui_preferences WHERE owner_id = :o AND pref_key = :k"),
                           {"o": current_user_id(session), "k": key}).scalar()


def set_preference(session, key: str, value) -> None:
    session.execute(text("""
        INSERT INTO ui_preferences (owner_id, pref_key, value) VALUES (:o, :k, CAST(:v AS JSONB))
        ON CONFLICT (owner_id, pref_key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
    """), {"o": current_user_id(session), "k": key, "v": json.dumps(value)})


def clear_preference(session, key: str) -> bool:
    return session.execute(text("DELETE FROM ui_preferences WHERE owner_id = :o AND pref_key = :k"),
                           {"o": current_user_id(session), "k": key}).rowcount > 0
