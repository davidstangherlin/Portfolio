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


# ---------- personal settings (Preferences, §35) ----------

USER_SETTINGS = "settings"
START_PAGES = {"dashboard": "Dashboard", "screener": "Screener", "etfs": "ETFs", "lics": "LICs",
               "watchlists": "Watchlists", "portfolios": "Portfolios", "track-record": "Track record",
               "coattail": "Coattail"}
# Each setting: its default and the values it can take (a bool, or one of a set).
SETTINGS_SPEC = {
    "theme": ("dark", ("light", "dark")),  # dark unless chosen otherwise
    "compact": (False, bool),              # tighter spacing in cards and tables
    "wrap_text": (False, bool),            # long names wrap in tables instead of being cut off
    "help_tips": (True, bool),             # the "i" help buttons beside terms
    "reduce_motion": (False, bool),
    "chart_patterns": (False, bool),       # dashes and hatching as well as colour in charts
    "chart_tables": (False, bool),         # open each chart's data table
    "show_hover_buttons": (False, bool),   # buttons that normally appear on hover are always shown
    "keyboard_shortcuts": (True, bool),
    "start_page": ("dashboard", tuple(START_PAGES)),
    "search_scope": ("auto", ("auto", "all", "page")),  # auto: the dashboard searches everything, other pages themselves
    "rows_shown": (100, (50, 100, 250)),   # rows shown before "Show more" in long tables
}
SETTINGS_DEFAULTS = {k: default for k, (default, _) in SETTINGS_SPEC.items()}


def clean_settings(body) -> dict:
    """The settings to store (only ones that differ from the defaults), or
    PreferenceError. Unknown keys are refused so a typo isn't silently kept."""
    if not isinstance(body, dict):
        raise PreferenceError("settings are a set of names and values")
    unknown = sorted(set(body) - set(SETTINGS_SPEC))
    if unknown:
        raise PreferenceError(f"unknown setting: {', '.join(unknown)}")
    out = {}
    for key, value in body.items():
        default, allowed = SETTINGS_SPEC[key]
        if not _valid(key, value):
            choices = "true or false" if allowed is bool else ", ".join(map(str, allowed))
            raise PreferenceError(f"{key} must be {choices}")
        if value != default:
            out[key] = value
    return out


def _valid(key, value) -> bool:
    default, allowed = SETTINGS_SPEC[key]
    return isinstance(value, bool) if allowed is bool else (value in allowed and type(value) is type(default))


def saved_settings(session) -> dict:
    """The settings this person chose (valid ones only). A value Sift no
    longer offers, such as the old "system" theme, counts as not chosen."""
    saved = get_preference(session, USER_SETTINGS) or {}
    return {k: v for k, v in saved.items() if k in SETTINGS_SPEC and _valid(k, v)}


def user_settings(session) -> dict:
    """The current user's settings, defaults filled in."""
    return SETTINGS_DEFAULTS | saved_settings(session)


def save_settings(session, changes) -> dict:
    """Merge `changes` into the current user's settings; returns them all."""
    merged = {k: v for k, v in user_settings(session).items()} | (changes if isinstance(changes, dict) else {})
    stored = clean_settings(merged)
    if stored:
        set_preference(session, USER_SETTINGS, stored)
    else:
        clear_preference(session, USER_SETTINGS)
    return SETTINGS_DEFAULTS | stored
