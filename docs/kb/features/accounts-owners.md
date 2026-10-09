---
id: accounts-owners
title: Accounts and owners (multi-user Phase 1)
category: features
summary: The users table, owner_id on every table of personal data, how the current person is known for each request, and the rules for adding personal data safely.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §33
related: [profile-preferences-impersonation, personal-nightly-results, adr-007-owner-scoping, adr-008-supabase-flyio]
code: [src/accounts.py, gui.py, db/schema.sql]
tables: [users]
---

## Purpose

Sift is heading to a hosted service. Every person's data must be theirs alone, and the rule is enforced where data is read and written so a new page can't leak it.

## How it works

The first step towards a hosted Sift for a test group and later the public (plan and status: `docs/MULTI_USER_PLAN.md`). Each person's portfolios, watchlists, scenarios and dashboard layout belong to them; market data, valuations, help and the track record of Sift's suggestions are shared. Nothing changes in use until sign-in (Phase 3).

**Data.** `users` (`user_id`, `email` unique in lower case, `display_name`, `role` admin or member, `status` active or disabled, `auth_subject` for the login service's id in Phase 3, `created_at`, `last_seen_at`). `db/schema.sql` creates the first admin, "Owner" (`owner@sift.local`, a placeholder until a real login is linked), when there are no users, then adds `owner_id` (not null, cascading delete) to `portfolios`, `watchlists`, `scenarios` and `ui_preferences` and gives every existing row to the first admin. Holdings and watchlist entries belong to their portfolio or list, so they need no column of their own. The single-column name rules became unique indexes on `(owner_id, lower(name))`, so two people can each have "Income ideas"; `ui_preferences` is keyed by `(owner_id, pref_key)`. All of it is idempotent and re-runs safely on start-up and each night. The older migration that creates "My portfolio" for parcels from before portfolios now gives it the first admin as owner when owners exist.

**Who Sift acts for.** `src/accounts.py` keeps the current user in a context variable. `current_user_id(session)` returns it, or, when none is set (command line, nightly run, tests), the first active admin, created if missing. `acting_as(user_id)` sets it for a block. Scoping lives where personal data is read and written, not in the 40-odd routes, so a new route can't forget it:

- `src/portfolio/holdings.py`: `list_portfolios`, `find_portfolio`, the new `get_portfolio`, name checks and `create_portfolio` use the owner; parcel queries (`open_parcels`, `sold_parcels`, `find_parcel`, so `position_summaries` and the "held" flags everywhere) only reach the owner's portfolios (`owned_portfolio_ids`); recording a trade in someone else's portfolio is refused.
- `src/watchlist/lists.py`: lists, `get_watchlist`, names, entries and `watched_codes`. `src/admin/scenarios.py`: new `list_scenarios` and `get_scenario`, names and saving. `src/preferences.py`: the owner's layout.
- `src/tracking/report.py`: "you bought it" in the track record counts only your purchases.
- Search ([§32](kb:search)): personal rows carry `owner_id`; see [§32](kb:search), Owners.
- `gui.py`: `portfolio_or_404`, `parcel_or_404` and `scenario_or_404` use the scoped getters, so someone else's ID is a 404 ("No such portfolio"), not a leak.

**Requests.** `create_app(password, resolve_user)`. `resolve_user(request, session)` says who an `/api/` request is from: until Phase 3 that's `owner_user` (the owner, behind `GUI_PASSWORD` when set); tests use `test_header_user` (the `X-Test-User` header, never used by `python gui.py`). The middleware answers 401 with no user, 403 for a disabled account, and 403 "Only an admin can do that." for a member on `/api/admin/`; otherwise it runs the request as that user and notes `last_seen_at` (at most once a minute). Static files and the page itself aren't personal and need no user. `/api/me` and the `user` in `/api/status` say who Sift is acting for; the page hides the gear menu's Admin links for members.

**Phase 2** ([§34](kb:personal-nightly-results)) made the nightly record per person; until then the nightly run acted as the owner.

**Tests.** `tests/integration/test_accounts.py`: the owner is the default and unique; the data layer scopes lists, parcels, positions, layout and names to the current user; through the API another person's lists and portfolios are empty and their IDs 404 on read and delete, screener watchlist flags are per person, and the same name is fine for two people; personal search results are each person's own, and a save rebuilds only the saver's rows; the admin console refuses members, an unknown user gets 401, a disabled one 403; with no resolver everything is the owner's as before. `tests/conftest.py` truncates `users` and re-creates the owner before each test.

## Code map

- `src/accounts.py`: users, the current person (context variable), acting_as(), impersonation
- `gui.py`: the request middleware that sets the current person
- `db/schema.sql`: section 7: users and owners

## Data

- `users`: email, display name, role (admin or member), status, the login service's id (Phase 3)

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Someone sees another person's data: a read isn't scoped; every personal read must filter by current_user_id(session). Add a two-user test.
- A page returns 'Sign in to use Sift' (401) or 'This account is disabled' (403): the request user couldn't be resolved or is disabled.

## Known limits

- Until Phase 3 every request is the owner (or whom an admin impersonates).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_accounts.py`
