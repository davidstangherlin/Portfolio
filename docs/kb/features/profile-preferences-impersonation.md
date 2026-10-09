---
id: profile-preferences-impersonation
title: Profile, Preferences, Users and impersonation
category: features
summary: The avatar menu, Profile and Preferences pages, keyboard shortcuts, the Users admin tab and how admins impersonate members safely.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §35
related: [accounts-owners, web-gui]
code: [src/preferences.py, src/accounts.py, gui.py, web/app.js]
tables: [impersonations, ui_preferences]
---

## Purpose

People manage their own account and settings in one place, and an admin can see Sift exactly as a member does to help them, with every session logged.

## How it works

Modelled on ServiceNow's user menu, Preferences and user record (the user's screenshots), cut to what fits Sift. Language & Region (date format, time zone) comes later; Notifications waits for a sending service (Phase 4).

**Avatar menu.** The round avatar (initials) at the top right replaces the settings gear. Its card shows the name and role; then Profile, Preferences and Keyboard shortcuts; for admins Impersonate user, Users, Model and rules and What-if scenarios. Arrow keys move through it and Escape closes it. Log out arrives with sign-in (Phase 3).

**Profile** (`#/profile`, `PATCH /api/me`): display name (editable), email (read-only until sign-in), role, and related links (Preferences, Keyboard shortcuts, Users for admins).

**Preferences** (`#/preferences/{display|theme|accessibility|experience}`): a section list with a search box on the left, switch cards on the right, and Reset all to defaults. Settings are one JSON value in `ui_preferences` under `settings`, per owner; `src/preferences.py` `SETTINGS_SPEC` lists each with its default and allowed values, `clean_settings()` refuses unknown names and wrong values (400), and only differences from the defaults are stored. `GET /api/me` returns them filled in; `PUT /api/me/settings` merges changes; `DELETE` resets. In the page, `applySettings()` sets classes on `<html>` (style.css "Preferences applied to every page") so every page follows without being redrawn:

| Section | Setting | Effect |
|---|---|---|
| Display | compact, wrap_text, help_tips | tighter cards and table rows; long names wrap; the "i" help buttons and dotted underlines hidden when off |
| Theme | theme | dark (the default) or light, chosen on two tiles that show each theme's colours as thick stripes on black or white; still cached in the browser so the page opens in the right theme (dark until light is chosen), and a browser's earlier light choice is carried to the account once. A saved "system" theme from before 2026-10-09 counts as not chosen |
| Accessibility | reduce_motion, chart_patterns, chart_tables, show_hover_buttons, keyboard_shortcuts | no transitions; second and third line series dashed and bars hatched (legend keys too); each chart's data table open; "i" buttons and widget pins always shown; shortcuts off |
| User experience | start_page, search_scope, rows_shown | the page Sift opens on (only when no page was asked for); the search box's default scope (auto, everything, this page); rows before "Show more" (50, 100, 250) |

**Keyboard shortcuts:** `/` search, `?` the list (a dialog), `g` then d, s, e, l, w, p, t, c, h or f to go to a page. Ignored while typing in a field or a dialog is open.

**Users** (Admin, Users, `/api/admin/users`): every account with role, status, last seen and what it owns; add an account (email, name, role); Make admin or member; Disable or Enable. `accounts.update_user()` refuses removing your own admin role or disabling yourself, and keeping fewer than one active admin. Until sign-in, a new account is used only through Impersonate. On phones, role and status move under the name.

**Impersonation.** `impersonations` (admin, target, started, ended, how) is both the open session and the audit log; a partial unique index allows one open session per admin. `POST /api/admin/impersonate` starts one (ending any other: "replaced"); `DELETE /api/impersonation` ends it and is open to the impersonating admin whomever they're acting as. The middleware resolves the signed-in person, then `accounts.impersonating()` gives whom Sift acts for: every personal read and write is then that person's (src/accounts.py), and `/api/admin/` is closed meanwhile, as it is for them. Guardrails: only admins impersonate; not yourself, not another admin, not a disabled account; a session ends after `IMPERSONATION_HOURS` (8, "expired") or when the person is disabled or made an admin ("unavailable"). The page shows a banner on every page with End impersonation, and the avatar gets an amber ring. The open session belongs to the admin, so it applies in all of their browsers. The Users tab shows the last 50 sessions.

**Search:** Profile, Preferences and Users are in `PAGES`; `impersonations` is in `EXCLUDED` (a log). Help: `profile-preferences` and `users-impersonation` in `web/knowledge.json`.

**Tests.** `tests/integration/test_profile.py`: settings checked, merged, personal and reset; profile name; the Users tab keeps an admin and nobody demotes or disables themselves; impersonation acts as the member (a watchlist made while impersonating is theirs), closes the console, ends, and is logged; guardrails for self, unknown accounts, members, disabled accounts and the 8-hour limit.

## Code map

- `src/preferences.py`: SETTINGS_SPEC and the checks on saved settings
- `src/accounts.py`: user management and impersonation
- `gui.py`: /api/me, /api/admin/users, impersonation routes, the middleware
- `web/app.js`: avatar menu, Profile, Preferences, shortcuts, banner, Users

## Data

- `impersonations`: every impersonation session: the audit log and the open session
- `ui_preferences`: each person's settings under 'settings'

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- An admin is stuck as someone else: End impersonation on the banner; see [Impersonation](kb:rb-impersonation).
- A preference doesn't stick: check the PUT /api/me/settings response; unknown names are refused.

## Known limits

- Language and region, and notifications, aren't built yet (IMP-042).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_profile.py`
- `tests/unit/test_preferences.py`
