---
id: change-process
title: How changes are made
category: start-here
summary: The end-to-end process for changing Sift safely: from the idea in the register to code, tests, browser checks, documentation, version and release notes.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [kb-guide, testing-and-validation, release-2026-10-1]
code: [CLAUDE.md, src/version.py, docs/AS_BUILT.md]
---

## Purpose

One way of working for anyone changing Sift, so quality doesn't depend on who makes the change. `CLAUDE.md` holds the same rules in short form for AI assistants.

## The steps

1. **Start from the register.** Add or pick an item in the [Improvement register](#/admin/kb/register) so the reason is recorded. Set it to In progress.
2. **Read before changing.** Read the feature article and the decision records it links. If the change reverses a decision, write a new decision record that supersedes it.
3. **Change the code** following the conventions below.
4. **Test.** Run the whole suite. Add tests for the change: a unit test for logic, an integration test for anything stored, a two-user test for anything personal.
5. **Check pages in a browser** at desktop and phone widths, light and dark, for any page change.
6. **Document.** Update the feature article (or write one for a new feature), raise its `version`, set `reviewed`; add a row to the change log in `docs/AS_BUILT.md`; keep `README.md` and Help (`web/knowledge.json`) in step.
7. **Close the loop.** Set the register item to Done with the date.
8. **Commit and push** to `main` with a message that says what changed and why.
9. **Release.** When a set of changes is ready to call a release, bump `src/version.py` and write the release notes (below).

## Conventions that tests enforce

- New table: in the search registers (`SOURCES` or `EXCLUDED` in `src/search/indexer.py`).
- New menu page: in `PAGES`.
- No em dashes in Help or in this knowledge base.
- Every article header complete and valid; every release note matches a version.

## Conventions to follow

- Schema changes in `db/schema.sql`, idempotent (`IF NOT EXISTS`); they apply on start-up and each night.
- Personal data: `owner_id` set from `current_user_id(session)` and every read scoped in the data layer; lookups by id through the scoped getters.
- Admin-only routes under `/api/admin/`.
- Action buttons pink, links blue, deleting red: use the classes and tokens in `web/style.css`.
- Personal data and secrets never in git: ticker files, `.env`, `logs/`, `data/asx_reports/`, backups.

## Versions and release notes

Sift's version is year.month.release (`2026.10.1` is the first release of October 2026), in `src/version.py`. To release:

1. Set `VERSION` and `RELEASED` in `src/version.py`.
2. Copy the latest file in `docs/kb/releases/`, name it after the version (dots become hyphens in the id: `release-2026-10-2`), set `release:` to the version, and write Highlights, Changes, Upgrade steps, Known issues and Articles updated.
3. Run the tests: one checks the newest release note matches `src/version.py`.

## Hand-over checklist for a new helper

- Read: [System overview](kb:system-overview), [Architecture](kb:architecture), this article, [Setup](kb:setup-and-configuration).
- Get: a GitHub account added to the repository; a local database restored from a backup (never the live password in chat or email).
- Run the tests and start Sift locally.
- Pick a small P3 item from the register for a first change.
