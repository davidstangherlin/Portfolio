# Sift multi-user plan

Sift today runs on one PC for one person. The aim is a hosted service: a small test group first (option B), then the public (option C). This file is the plan and its status; the design record for what is built is `docs/AS_BUILT.md` §33.

## Decisions made

| Question | Decision |
|---|---|
| Who first | A test group, built so a public service needs no rework |
| Logins | A hosted login service: Supabase Auth (email and password, magic links, Google) |
| Hosting | Supabase Postgres in Sydney, the app on Fly.io (Sydney) |
| Screener universe | One shared list of companies, ETFs and LICs for everyone |
| Approach | Plan first, then build in phases, each one shippable on its own |

## What is shared and what is personal

| Shared (everyone sees the same) | Personal (each person's own) |
|---|---|
| Companies, prices, reports, valuations | Portfolios and their parcels (holdings) |
| Screener, ETFs, LICs, Coattail | Watchlists and their entries |
| Help articles, model settings | What-if scenarios |
| Track record of Sift's suggestions | Dashboard layout |
| Search index for all of the above | Personal search rows, search votes |

## Phases

| Phase | What it delivers | Status |
|---|---|---|
| 1. Owners in the data | `users` table; an owner on every personal table; all personal reads and writes scoped to the current user; admin-only console; tests proving two people can't see each other's data. Sift looks and works exactly as before. | **Done** (2026-10-09) |
| 2. Per-person results | Each person's "held" flags and actions in the nightly snapshots and track record (today the nightly run acts as the owner); per-person dashboard history. | Not started |
| 3. Sign in | Supabase Auth: sign-in page, the login service's token checked on every request (replaces the single `GUI_PASSWORD`), invitations for testers, the owner's account linked to a real email. | Not started; needs a Supabase account |
| 4. Hosting | Database moved to Supabase (from the backup), app on Fly.io, nightly run as a scheduled job there, secrets in the host's store, backups. | Not started; needs Fly.io and Supabase accounts |
| 5. Tester readiness | Privacy note and terms, "not financial advice" wording on sign-up, usage limits, error monitoring, a feedback link, an admin page to invite and disable testers. | Not started |

## Phase 1 in brief

- `users` (email, display name, role `admin` or `member`, status `active` or `disabled`, and `auth_subject` waiting for Phase 3).
- The first admin, "Owner" (`owner@sift.local`), is created by `db/schema.sql` and owns everything from before accounts.
- `owner_id` on `portfolios`, `watchlists`, `scenarios` and `ui_preferences`. Parcels and watchlist entries belong to their portfolio or list. Names are unique per owner.
- `src/accounts.py` holds the current user for each request. The functions that read and write personal data scope themselves, so a route can't forget to.
- Command-line tools and the nightly run act as the owner.

## Before Phase 3

- Create a Supabase project (Sydney region) and share the project URL and the public "anon" key. Never paste the service key or the database password into chat; they go in `.env` on the PC or the host's secret store.
- Decide the tester invite list and the sign-in methods (email and password, magic link, Google).
