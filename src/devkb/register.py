"""The improvement register (§36): known issues, technical debt and ideas,
kept in docs/kb/improvements.json and shown in Admin, Developer.

Each item: id (IMP-001), title, type, priority, status, impact, raised,
updated, articles (knowledge base ids it touches) and notes. Checked by
tests/unit/test_devkb.py."""

from __future__ import annotations

import json
import re
from datetime import date

from src.devkb.articles import KB_DIR

REGISTER = KB_DIR / "improvements.json"
TYPES = {"issue": "Known issue", "debt": "Technical debt", "idea": "Improvement idea", "risk": "Risk"}
PRIORITIES = {"P1": "P1: now", "P2": "P2: next", "P3": "P3: later", "P4": "P4: maybe"}
STATUSES = {"open": "Open", "planned": "Planned", "in-progress": "In progress", "done": "Done", "wont": "Won't do",
            "by-design": "By design"}
FIELDS = ("id", "title", "type", "priority", "status", "impact", "raised", "updated", "articles", "notes")


class RegisterError(ValueError):
    pass


def load() -> list[dict]:
    items = json.loads(REGISTER.read_text(encoding="utf-8"))["items"]
    return items


def check(items: list[dict], article_ids: set[str]) -> None:
    """RegisterError for the first item that breaks a rule."""
    seen = set()
    for it in items:
        missing = [f for f in FIELDS if f not in it]
        if missing:
            raise RegisterError(f"{it.get('id', '?')}: missing {', '.join(missing)}")
        if not re.fullmatch(r"IMP-\d{3}", it["id"]) or it["id"] in seen:
            raise RegisterError(f"{it['id']}: ids are IMP-001, IMP-002... and unique")
        seen.add(it["id"])
        for key, allowed in (("type", TYPES), ("priority", PRIORITIES), ("status", STATUSES)):
            if it[key] not in allowed:
                raise RegisterError(f"{it['id']}: {key} must be one of {', '.join(allowed)}")
        for key in ("raised", "updated"):
            date.fromisoformat(it[key])
        unknown = [a for a in it["articles"] if a not in article_ids]
        if unknown:
            raise RegisterError(f"{it['id']}: no article {', '.join(unknown)}")


def summary(items: list[dict]) -> dict:
    live = [i for i in items if i["status"] not in ("done", "wont", "by-design")]
    return {"open": len(live), "p1": sum(1 for i in live if i["priority"] == "P1"),
            "by_type": {t: sum(1 for i in live if i["type"] == t) for t in TYPES}}
