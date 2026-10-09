---
id: architecture
title: Architecture
category: start-here
summary: The running parts of Sift (database, nightly job, web server, pages), how a request flows through the server, and how this changes when Sift is hosted.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [system-overview, nightly-run, web-gui, accounts-owners, adr-001-local-postgres, adr-002-fastapi-plain-js, adr-008-supabase-flyio]
code: [gui.py, src/accounts.py, src/config.py, scripts/daily_refresh.ps1, web/app.js]
---

## Purpose

A map of what runs where and how the parts talk to each other. Read it before changing anything that crosses parts (a new page with a new table, a new nightly step), and when diagnosing which part a problem is in.

## The parts

| Part | What it is | Runs |
|---|---|---|
| PostgreSQL database | Every stored fact: market data, valuations, the track record, people's portfolios and settings, the search index | Always (Windows service on the owner's PC) |
| Nightly job | `scripts/daily_refresh.ps1`: schema, ingestion, valuation, recording, scoring, search index | 6 pm each evening, Windows Task Scheduler |
| Web server | `gui.py`: FastAPI on uvicorn, serving `/api/...` JSON and the page files | While `start_sift.bat` (or `python gui.py`) is open |
| Pages | `web/index.html`, `web/app.js`, `web/style.css` and two helpers: plain JavaScript, no build step | In the browser |
| Command-line tools | `screen_asx.py`, `portfolio.py`, `python -m src....` commands | On demand |
| Outside services | Yahoo Finance (through yfinance) and the ASX's monthly investment products report | Read by the nightly job only |

Everything runs on one PC today. The pages load nothing from other sites.

## Layers in the code

1. **Data access:** `src/config.py` (one engine per process, sessions per request), `src/models/` (ORM), raw SQL where it's clearer.
2. **Domain logic:** `src/ingestion/`, `src/valuation/`, `src/screening/`, `src/tracking/`, `src/portfolio/`, `src/watchlist/`, `src/etf/`, `src/coattail/`, `src/search/`, `src/admin/`, `src/accounts.py`, `src/preferences.py`.
3. **Delivery:** `gui.py` (routes and payloads) and the command-line entry points. Routes stay thin: they call domain functions and shape JSON.
4. **Pages:** one JavaScript file builds every page from the JSON.

The same row loader feeds the command line, the pages and the nightly record (`screen_asx.load_annotated_rows`, `src/screening/enriched.load_universe`), so they can't disagree.

## A request, step by step

1. The browser calls `/api/...` with the `X-Sift` header on any change.
2. Middleware in `gui.py` (`require_password`): checks the password if set (`GUI_PASSWORD`), refuses changes not from Sift's own pages, then works out **who is signed in** and **whom Sift acts for** (the same person, unless an admin is impersonating), refuses disabled accounts, and refuses members on `/api/admin/`.
3. The middleware sets the current person (`src/accounts.acting_as`) for the request. Every personal read and write is scoped to that person in the domain code, not the route.
4. The route opens a session, calls domain functions, and returns JSON. Changes go through `change()`: one transaction, the personal search rows refreshed, a rule broken by the person becomes a 400 with a readable message.
5. Any unexpected error becomes a 500 with a readable message on the page; the traceback goes to the server window.

## How it changes when hosted

The multi-user plan (`docs/MULTI_USER_PLAN.md`) moves the database to Supabase Postgres in Sydney and the server to Fly.io (Phase 4), and replaces the single password with Supabase Auth sign-in (Phase 3). The layers above don't change: the request resolver (`resolve_user` in `create_app`) is the one seam built for it. See [Supabase and Fly.io](kb:adr-008-supabase-flyio).
