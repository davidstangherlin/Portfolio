# Sift: working notes for Claude

Sift is an ASX value-investing tool: Python 3.11, FastAPI (`gui.py`), PostgreSQL, plain JavaScript pages in `web/`. The full design record is `docs/AS_BUILT.md`; read the relevant section before changing a feature.

## Conventions

- Australian English, no em dashes (a test enforces this in `web/knowledge.json`).
- Commit and push to `main`. Before pushing: run the whole test suite (`.venv/bin/python -m pytest -q`) and, for page changes, check the page in a browser at desktop and phone widths.
- Every change gets a row in the AS_BUILT change log (newest at the bottom of the table) and, for a new feature, its own numbered section. Keep `README.md` and the help articles in `web/knowledge.json` in step.
- Personal data stays out of git: `allords.txt` and other ticker files, `.env`, `logs/`, `data/asx_reports/`. Never ask for the database password in chat.
- Schema changes go in `db/schema.sql` and must be idempotent (`IF NOT EXISTS`); they apply on start-up and at the start of the nightly run.

## Search must keep up as Sift grows (§32)

Every new table, page or kind of content must be searchable, or deliberately not:

1. **New table:** add it to `SOURCES` in `src/search/indexer.py` and index it in that area's builder (or add a new area with its own builder), or add it to `EXCLUDED` with the reason. `tests/unit/test_search_coverage.py` fails until you do.
2. **New menu page:** add it to `PAGES` in `src/search/indexer.py` (the same test checks the menu).
3. **New kind of result:** give it a label in `KIND_LABELS` (`src/search/query.py`), and any facet it should filter by.
4. **New personal data** (anything a user saves): put it in the `personal` area so it's indexed on save, with an owner once Sift has user accounts.
5. **Help articles and settings** are indexed automatically from `web/knowledge.json` and `src/settings.py`.

## Multi-user readiness

Sift is heading to a hosted, multi-user service (test group first, public later). New personal data should be easy to scope to an owner; the search index already carries `owner_id`.
