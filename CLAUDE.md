# Sift: working notes for Claude

Sift is an ASX value-investing tool: Python 3.11, FastAPI (`gui.py`), PostgreSQL, plain JavaScript pages in `web/`. How each part is designed and works is in the developer knowledge base, `docs/kb/` (shown to admins in Sift at Admin, Developer); read the feature article and its decision records before changing a feature. `docs/AS_BUILT.md` keeps the change log and the original design record.

## Conventions

- Australian English, no em dashes (a test enforces this in `web/knowledge.json`).
- Commit and push to `main`. Before pushing: run the whole test suite (`.venv/bin/python -m pytest -q`) and, for page changes, check the page in a browser at desktop and phone widths.
- Every change gets a row in the AS_BUILT change log (newest at the bottom of the table). Keep `README.md` and the help articles in `web/knowledge.json` in step.
- Developer knowledge base (`docs/kb/`, guide: `docs/kb/start-here/kb-guide.md`): update the feature article a change touches (raise its `version`, set `reviewed`); a new feature gets a new article on the feature template; a significant design choice gets a decision record (`decisions/adr-...`); a fix for a recurring problem gets a runbook (`operations/rb-...`); known issues and ideas go in `docs/kb/improvements.json`. `tests/unit/test_devkb.py` checks every header, link and code path.
- Releases: bump `src/version.py` and add `docs/kb/releases/release-<version>.md` (the test checks they match).
- Personal data stays out of git: `allords.txt` and other ticker files, `.env`, `logs/`, `data/asx_reports/`. Never ask for the database password in chat.
- UI colour: every action button is pink (`--action`: `.btn`, `.btn.primary` for the main one, `.icon-btn`), links are blue (`--accent`), deleting is red (`.btn.danger`). Use the classes or tokens, never raw colours (`web/style.css`, "Action colour").
- Schema changes go in `db/schema.sql` and must be idempotent (`IF NOT EXISTS`); they apply on start-up and at the start of the nightly run.

## Search must keep up as Sift grows (§32)

Every new table, page or kind of content must be searchable, or deliberately not:

1. **New table:** add it to `SOURCES` in `src/search/indexer.py` and index it in that area's builder (or add a new area with its own builder), or add it to `EXCLUDED` with the reason. `tests/unit/test_search_coverage.py` fails until you do.
2. **New menu page:** add it to `PAGES` in `src/search/indexer.py` (the same test checks the menu).
3. **New kind of result:** give it a label in `KIND_LABELS` (`src/search/query.py`), and any facet it should filter by.
4. **New personal data** (anything a user saves): put it in the `personal` area so it's indexed on save, with an owner once Sift has user accounts.
5. **Help articles and settings** are indexed automatically from `web/knowledge.json` and `src/settings.py`.
6. **AI-ready:** give every indexed row meaningful `title`, `subtitle` and `body` text; that text is what's embedded when meaning-based search is on (`src/search/embeddings.py`). Don't stuff rows with numbers: they don't embed well.
7. **Learning tables** (`search_queries`, `search_clicks`, `search_feedback`, `search_synonyms`) are logs, not content: keep them in `EXCLUDED`.

## AI and graph readiness (docs/kb/features/ai-and-graph.md)

- PostgreSQL is the source of truth; the graph is an export (`src/graph/export.py`) and AI reaches Sift only through the read-only tools in `src/ai/tools.py` (MCP server and `/api/ai/tools`).
- New data people will ask about: add or extend a tool (scoped to the current user, plain JSON, reasons in words, the not-advice note where actions appear) and a test in `tests/integration/test_ai_graph.py`. New entities or relationships worth exploring: add them to the export and `load.cypher`.
- Tools never write. Keep `mcp` optional (`requirements-ai.txt`).

## Multi-user readiness

Sift is heading to a hosted, multi-user service (test group first, public later); the plan and status are in `docs/MULTI_USER_PLAN.md`, the design in AS_BUILT §33. Phase 1 is built: a `users` table, and `owner_id` on every table of personal data.

- **New personal table:** give it `owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE` (or hang it off an owned table, as parcels hang off portfolios), set it from `current_user_id(session)` (`src/accounts.py`) on insert, and filter every read by it in the data layer, not in routes. Make names unique per owner.
- **Looking something up by ID** from a request: use the scoped getter (`get_portfolio`, `get_watchlist`, `get_scenario`) so someone else's row is a 404, never `session.get` alone.
- **Shared data** (market, valuations, help) has no owner. Personal search rows carry `owner_id`.
- **Admin-only** routes live under `/api/admin/`; the middleware refuses members there.
- **New preference:** add it to `SETTINGS_SPEC` (`src/preferences.py`) and `SETTING_DEFAULTS` and `PREFS` (`web/app.js`), and apply it in `applySettings()`, usually as a class on `<html>` (AS_BUILT §35).
- **Impersonation:** routes read `request.state.user` (who is signed in) and `request.state.acting` (whom Sift acts for); personal data always follows the acting user.
- **Tests:** add a two-user case to `tests/integration/test_accounts.py` for anything personal (`gui.create_app(resolve_user=gui.test_header_user)` and the `X-Test-User` header).
