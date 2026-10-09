---
id: developer-kb
title: The developer knowledge base
category: features
summary: How this knowledge base is built: articles in git, the checked header, the safe Markdown renderer, generated reference pages, the register, versions, review reminders and admin-only search.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [kb-guide, adr-010-docs-in-git, search]
code: [src/devkb/articles.py, src/devkb/markdown.py, src/devkb/generated.py, src/devkb/register.py, src/version.py, gui.py, web/app.js]
tables: [search_index]
---

## Purpose

Keep Sift's design and operating knowledge where admins and helpers can find it, current with the code, and reviewed on a cycle. How to write articles is in [How this knowledge base works](kb:kb-guide); this article is how the feature itself works.

## How it works

- **Articles** are `docs/kb/<category>/<id>.md`. `src/devkb/articles.py` reads them (again only when a file changes), parses the header block and refuses a missing or wrong field (`ArticleError`).
- **Rendering:** `src/devkb/markdown.py` turns Markdown into HTML on the server. Every piece of text is escaped first, so an article can't inject markup; links are allowed only to Sift pages (`#/...`), other articles (`kb:id`) and `https://` sites (opened in a new tab). Headings get anchors and make the "On this page" list.
- **Generated reference** (`src/devkb/generated.py`): the data dictionary (live database plus the comments in `db/schema.sql`, with each table's search register entry and whether it's per person), the API reference (the app's routes and their docstrings), settings (model settings and preferences), dependencies (pinned against installed, the PostgreSQL version and extensions, outside services) and the test catalogue (every test file's docstring and count). Built each time they're opened, so they can't go stale.
- **Register** (`src/devkb/register.py`): `docs/kb/improvements.json`, items IMP-001 to IMP-036 carrying AS_BUILT's known issue numbers, later ones new. Type, priority, status, impact, dates, linked articles and notes.
- **Versions:** `src/version.py` holds Sift's version and release date; release notes are articles in `releases/` with a `release:` field.
- **Reviews:** each article's `next_review`; the home page lists overdue ones and those due within 30 days (`DUE_SOON_DAYS`).
- **Access:** the pages are under Admin (`#/admin/kb`, `#/admin/kb/<id>`, `#/admin/kb/register`) and the API under `/api/admin/kb`, which the middleware refuses to members. Search indexes every article (and the home page) in the `devkb` area with `audience` 'admin'. They're never in Everything: an admin picks **Developer knowledge base (admins)** in the search box's pink ▾ menu (the default on these pages), which sends `scope=devkb`; that scope searches only these rows and returns nothing for a member. On the home page and the register, **This page** types into their own filter box.

## Code map

- `src/devkb/articles.py`: loading, header checks, categories, review states
- `src/devkb/markdown.py`: the renderer
- `src/devkb/generated.py`: the generated reference pages
- `src/devkb/register.py`: the register's fields and checks
- `src/version.py`: Sift's version
- `gui.py`: `/api/admin/kb`, `/api/admin/kb/register`, `/api/admin/kb/{id}`
- `web/app.js`: `renderKb`, `renderKbArticle`, `renderKbRegister`

## Data

- Files in `docs/kb/` (articles, `improvements.json`).
- `search_index` rows with `area` 'devkb' and `audience` 'admin'.

## Diagnosing problems

- An article isn't found in Everything: by design; choose Developer knowledge base in the ▾ menu.
- The home page fails to load: an article has a bad header; the error names the file. `tests/unit/test_devkb.py` catches this before a push.
- A new article doesn't appear in search: restart Sift (the knowledge base is reindexed on start) or rebuild the devkb area in Admin, Search.

## Known limits

- Editing is in git, not in the browser (by design: [the decision](kb:adr-010-docs-in-git)).
- Review reminders show on the home page only; nothing is emailed (IMP-039).

## Tests

- `tests/unit/test_devkb.py`: every header, link, code path, register item and release note; the renderer's escaping and markup
- `tests/integration/test_devkb_api.py`: the API is admin-only, articles and generated pages render, articles are never in Everything and only admins find them in their own scope
