"""Articles of the developer knowledge base (§36).

Each article is docs/kb/<category folder>/<id>.md: a header block between
"---" lines, then Markdown. The header fields (FIELDS) are checked by
tests/unit/test_devkb.py, so an article can't be published half-described.
Lists are written [a, b, c]."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from src.devkb import markdown

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "docs" / "kb"

# Shown in this order on the knowledge base home page.
CATEGORIES = {
    "start-here": "Start here",
    "features": "Features: how each part works",
    "data": "Data",
    "operations": "Operations and runbooks",
    "decisions": "Decision records",
    "reference": "Generated reference",
    "releases": "Release notes",
}
STATUSES = ("draft", "published", "retired")
REQUIRED = ("id", "title", "category", "summary", "version", "status", "owner", "published", "reviewed", "next_review")
OPTIONAL = ("related", "code", "tables", "source", "release", "decision_status")
DUE_SOON_DAYS = 30


@dataclass
class Article:
    id: str
    title: str
    category: str
    summary: str
    version: str
    status: str
    owner: str
    published: date
    reviewed: date
    next_review: date
    body: str
    path: str
    related: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    source: str | None = None
    release: str | None = None           # release notes: the Sift version they describe
    decision_status: str | None = None   # decision records: proposed, accepted, superseded

    def review_state(self, today: date) -> str:
        if self.next_review < today:
            return "overdue"
        if self.next_review <= today + timedelta(days=DUE_SOON_DAYS):
            return "due"
        return "ok"

    def info(self, today: date) -> dict:
        return {k: getattr(self, k) for k in ("id", "title", "category", "summary", "version", "status", "owner",
                                               "published", "reviewed", "next_review", "related", "code", "tables",
                                               "source", "release", "decision_status", "path")} | {
            "review": self.review_state(today)}


class ArticleError(ValueError):
    pass


def _value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [x.strip() for x in raw[1:-1].split(",") if x.strip()]
    return raw


def parse(text: str, path: str) -> Article:
    """An article from its file's text, or ArticleError naming what's wrong."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text.replace("\r\n", "\n"), re.S)
    if not m:
        raise ArticleError(f"{path}: no header block between --- lines")
    meta: dict = {}
    for line in m.group(1).split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ArticleError(f"{path}: header line without a colon: {line!r}")
        key = key.strip()
        if key not in REQUIRED and key not in OPTIONAL:
            raise ArticleError(f"{path}: unknown header field {key!r}")
        meta[key] = _value(value)
    missing = [k for k in REQUIRED if not meta.get(k)]
    if missing:
        raise ArticleError(f"{path}: missing {', '.join(missing)}")
    if meta["category"] not in CATEGORIES:
        raise ArticleError(f"{path}: category must be one of {', '.join(CATEGORIES)}")
    if meta["status"] not in STATUSES:
        raise ArticleError(f"{path}: status must be one of {', '.join(STATUSES)}")
    if not re.fullmatch(r"\d+\.\d+", meta["version"]):
        raise ArticleError(f"{path}: version is major.minor, e.g. 1.0")
    for k in ("published", "reviewed", "next_review"):
        try:
            meta[k] = date.fromisoformat(meta[k])
        except ValueError:
            raise ArticleError(f"{path}: {k} must be a date like 2026-10-09") from None
    if meta["next_review"] <= meta["reviewed"]:
        raise ArticleError(f"{path}: next_review must be after reviewed")
    for k in ("related", "code", "tables"):
        if isinstance(meta.get(k), str):
            meta[k] = [meta[k]]
    return Article(body=m.group(2).strip() + "\n", path=path, **meta)


@lru_cache(maxsize=4)
def _load(stamp: tuple) -> tuple[Article, ...]:
    found = []
    for f in sorted(KB_DIR.rglob("*.md")):
        found.append(parse(f.read_text(encoding="utf-8"), str(f.relative_to(ROOT)).replace("\\", "/")))
    return tuple(found)


def load() -> list[Article]:
    """Every article, read again only when a file has changed (a git pull)."""
    stamp = tuple((str(f), f.stat().st_mtime_ns) for f in sorted(KB_DIR.rglob("*.md")))
    return list(_load(stamp))


def by_id() -> dict[str, Article]:
    return {a.id: a for a in load()}


def rendered(article: Article) -> tuple[str, list[dict]]:
    return markdown.render(article.body)


def review_summary(articles: list[Article], today: date) -> dict:
    """Overdue and due-soon reviews, for the home page."""
    live = [a for a in articles if a.status != "retired"]
    pick = lambda state: sorted((a for a in live if a.review_state(today) == state), key=lambda a: a.next_review)  # noqa: E731
    return {"overdue": [a.info(today) for a in pick("overdue")], "due": [a.info(today) for a in pick("due")],
            "total": len(live), "drafts": sum(1 for a in live if a.status == "draft")}
